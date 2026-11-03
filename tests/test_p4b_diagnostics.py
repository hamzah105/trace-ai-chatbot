"""Offline administration and actual client-discovery boundary controls.

Only SDK context/transport seams are replaced. Client dispatch, JSON-schema and
independent context-wire validation still execute; no MCP server is started.
"""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.services.oomp_client import OOMPClient, OOMPError
from backend.services.oomp_config import OOMPConfiguration
from backend.services.oomp_diagnostics import diagnose
from p4b_support import SERVER, context_response
from stage8_support import configuration


def diagnostic_client(monkeypatch, *, tools=(), status=None):
    calls = []
    status = status if status is not None else {
        "capabilities": ["read"], "mind_worker_started_by_server": False}
    def call(name, arguments, token=None):
        calls.append((name, arguments, token))
        if name != "memory.status":
            raise AssertionError("Diagnostics attempted a retrieval or mutation")
        return dict(status)
    client = SimpleNamespace(last_protocol_version="synthetic-mcp-protocol",
                             last_tool_names=tools, call=call)
    constructor = Mock(return_value=client)
    monkeypatch.setattr("backend.services.oomp_diagnostics.OOMPClient", constructor)
    return constructor, calls


def test_off_diagnostics_report_selection_without_constructing_client(monkeypatch):
    constructor, calls = diagnostic_client(monkeypatch)
    report = diagnose(OOMPConfiguration())
    constructor.assert_not_called()
    assert calls == []
    assert report["mode"] == "off" and report["retrieval_api"] == "retrieve"
    assert report["configuration_valid"] and not report["connected"]
    assert "context_capability_available" not in report
    assert "context_contract_expected" not in report


@pytest.mark.parametrize("available", [True, False])
def test_context_diagnostics_discover_tool_without_claiming_contract_negotiation(monkeypatch, available):
    tools = ("memory.context", "memory.retrieve", "memory.status") if available else (
        "memory.retrieve", "memory.status")
    _, calls = diagnostic_client(monkeypatch, tools=tools)
    config = configuration(SERVER, mode="retrieve", retrieval_api="context_v1")
    report = diagnose(config)
    assert calls == [("memory.status", {}, None)]
    assert report["connected"] and report["retrieval_api"] == "context_v1"
    assert report["context_capability_available"] is available
    assert report["context_contract_expected"] == "oomp.context.v1"
    assert report["protocol"] == "synthetic-mcp-protocol"
    # Discovery proves a tool name, not a negotiated or returned wire version.
    assert "context_contract_version" not in report
    assert "context_contract_negotiated" not in report
    assert "read_token" not in report and "owner_key" not in report


def test_legacy_diagnostics_keep_existing_fields_and_status_only_behavior(monkeypatch):
    _, calls = diagnostic_client(monkeypatch, tools=("memory.retrieve", "memory.status"))
    config = configuration(SERVER, mode="retrieve")
    report = diagnose(config)
    expected_legacy = {
        "mode": "retrieve", "configuration_valid": True, "connected": True,
        "evidence_budget_bytes": 1200, "max_results": 5, "max_prompt_bytes": 7000,
        "timeout_seconds": 5, "ingestion_ready": False,
        "protocol": "synthetic-mcp-protocol", "worker_started_by_server": False,
    }
    assert {key: report[key] for key in expected_legacy} == expected_legacy
    assert calls == [("memory.status", {}, None)]
    assert report["retrieval_api"] == "retrieve"
    assert report["context_contract_expected"] is None
    assert report["context_capability_available"] is False


def test_ingestion_diagnostics_still_check_each_actual_writer_grant(monkeypatch):
    calls = []
    def call(name, arguments, token=None):
        calls.append((name, arguments, token))
        assert name == "memory.status" and arguments == {}
        return {"capabilities": ["read", "ingest"] if token else ["read"],
                "mind_worker_started_by_server": False}
    client = SimpleNamespace(call=call, last_tool_names=("memory.context", "memory.status"),
                             last_protocol_version="synthetic-mcp-protocol")
    monkeypatch.setattr("backend.services.oomp_diagnostics.OOMPClient", lambda config: client)
    config = configuration(SERVER, retrieval_api="context_v1")
    report = diagnose(config)
    assert report["connected"] and report["ingestion_ready"]
    assert calls == [("memory.status", {}, None)] + [
        ("memory.status", {}, grant.credential()) for grant in config.writers.values()]


@pytest.fixture
def sdk_boundary(monkeypatch):
    """Mock external SDK lifecycle, retaining OOMPClient.call_async itself."""
    import httpx2
    import mcp
    import mcp.client.streamable_http as streamable

    state = SimpleNamespace(
        tools=("memory.context", "memory.status"), server_name="OOMP",
        calls=[], discovery_calls=0, error_code=None, mutate=None, cancelled=False,
    )

    class NoNetworkTransport:
        def __init__(self, *args, **kwargs):
            pass
        async def handle_async_request(self, request):
            raise AssertionError("A mocked client attempted network access")
        async def aclose(self):
            pass

    @asynccontextmanager
    async def fake_http(**settings):
        assert settings["trust_env"] is False and settings["follow_redirects"] is False
        assert settings["headers"]["Authorization"].startswith("Bearer ")
        try:
            yield object()
        finally:
            await settings["transport"].aclose()

    @asynccontextmanager
    async def fake_streamable(url, http_client):
        assert url == SERVER.url
        yield object()

    class FakeSDKClient:
        def __init__(self, transport):
            self.server_info = SimpleNamespace(name=state.server_name)
            self.protocol_version = "synthetic-mcp-protocol"
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def list_tools(self):
            state.discovery_calls += 1
            return SimpleNamespace(tools=[SimpleNamespace(
                name=name, input_schema={"type": "object"}, output_schema={"type": "object"})
                for name in state.tools])
        async def call_tool(self, name, arguments):
            state.calls.append((name, dict(arguments)))
            if state.cancelled:
                raise asyncio.CancelledError()
            if state.error_code is not None:
                return SimpleNamespace(is_error=True,
                    structured_content={"error": {"code": state.error_code}})
            data = context_response(arguments)
            if state.mutate is not None:
                state.mutate(data)
            return SimpleNamespace(is_error=False, structured_content=data)

    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", NoNetworkTransport)
    monkeypatch.setattr(httpx2, "AsyncClient", fake_http)
    monkeypatch.setattr(streamable, "streamable_http_client", fake_streamable)
    monkeypatch.setattr(mcp, "Client", FakeSDKClient)
    return state


def test_context_uses_actual_discovery_dispatch_and_independent_wire_validation(sdk_boundary):
    client = OOMPClient(configuration(SERVER, mode="retrieve", retrieval_api="context_v1"))
    result = client.context("A fictional context lookup.", token_budget=1200)
    assert result.context_contract_version == "oomp.context.v1"
    assert sdk_boundary.discovery_calls == 1
    assert [name for name, _ in sdk_boundary.calls] == ["memory.context"]
    assert client.last_tool_names == ("memory.context", "memory.status")
    assert client.last_protocol_version == "synthetic-mcp-protocol"


def test_missing_context_tool_stops_before_any_tool_call_or_legacy_downgrade(sdk_boundary):
    sdk_boundary.tools = ("memory.retrieve", "memory.status")
    client = OOMPClient(configuration(SERVER, mode="retrieve", retrieval_api="context_v1"))
    with pytest.raises(OOMPError, match="capability_missing"):
        client.context("A fictional context lookup.", token_budget=1200)
    assert sdk_boundary.calls == [] and sdk_boundary.discovery_calls == 1


def test_wrong_mcp_server_cannot_supply_context(sdk_boundary):
    sdk_boundary.server_name = "UnrelatedServer"
    with pytest.raises(OOMPError, match="server_mismatch"):
        OOMPClient(configuration(SERVER, mode="retrieve")).context(
            "A fictional context lookup.", token_budget=1200)
    assert sdk_boundary.calls == []


@pytest.mark.parametrize("code,expected", [
    ("not_found", "not_found"), ("unsupported", "unsupported"),
    ("unavailable", "unavailable"), ("timeout", "timeout"),
    ("forbidden", "forbidden"), ("PRIVATE-REMOTE-ERROR", "tool_failed"),
])
def test_actual_context_dispatch_preserves_finite_server_error_codes(sdk_boundary, code, expected):
    sdk_boundary.error_code = code
    with pytest.raises(OOMPError) as failure:
        OOMPClient(configuration(SERVER, mode="retrieve")).context(
            "A fictional context lookup.", token_budget=1200)
    assert failure.value.code == expected
    assert [name for name, _ in sdk_boundary.calls] == ["memory.context"]


@pytest.mark.parametrize("version", [None, "oomp.context.v2"])
def test_discovered_tool_does_not_bypass_returned_context_version(sdk_boundary, version):
    def mutate(value):
        if version is None:
            value.pop("context_contract_version")
        else:
            value["context_contract_version"] = version
    sdk_boundary.mutate = mutate
    with pytest.raises(OOMPError, match="unsupported"):
        OOMPClient(configuration(SERVER, mode="retrieve")).context(
            "A fictional context lookup.", token_budget=1200)


def test_sdk_cancellation_propagates_without_fallback_or_second_request(sdk_boundary):
    sdk_boundary.cancelled = True
    with pytest.raises(asyncio.CancelledError):
        OOMPClient(configuration(SERVER, mode="retrieve")).context(
            "A fictional context lookup.", token_budget=1200)
    assert [name for name, _ in sdk_boundary.calls] == ["memory.context"]