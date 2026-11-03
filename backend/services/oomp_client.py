"""Optional official SDK client; each sync call owns one async loop and lifecycle."""
from __future__ import annotations
import asyncio
import json
import logging
from contextvars import ContextVar
from threading import BoundedSemaphore

from .oomp_contracts import RetrieveWire
from .oomp_context_contracts import ContextResult, CONTEXT_VERSION

_SLOTS = BoundedSemaphore(4)
_PRIVATE_OPERATION = ContextVar("trace_private_mcp_operation", default=False)


class _SDKLogFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE_OPERATION.get():
            record.msg = "MCP transport diagnostic redacted; consult TRACE integration status codes"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


_SDK_LOG_FILTER = _SDKLogFilter()


def _protect_sdk_logs():
    # SDK parser exceptions can include remote validation input. Apply only
    # during this adapter's context, retaining other callers' normal logging.
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("mcp.") and isinstance(logger, logging.Logger):
            if _SDK_LOG_FILTER not in logger.filters:
                logger.addFilter(_SDK_LOG_FILTER)



class OOMPError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _error_code(error):
    if isinstance(error, OOMPError):
        return error.code
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(error, BaseExceptionGroup):
        for child in error.exceptions:
            code = _error_code(child)
            if code != "unavailable":
                return code
    return "unavailable"


class OOMPClient:
    def __init__(self, config):
        self.config = config
        self.last_protocol_version = None
        self.last_tool_names = ()

    def _sync(self, coroutine_factory):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise OOMPError("sync_boundary")
        if not _SLOTS.acquire(blocking=False):
            raise OOMPError("busy")
        try:
            return asyncio.run(coroutine_factory())
        finally:
            _SLOTS.release()

    def retrieve(self, query):
        if not query.strip() or len(query) > 4096:
            raise OOMPError("query_limit")
        args = {"query": query, "max_results": self.config.max_results,
                "token_budget": self.config.evidence_budget, "mode": self.config.retrieval_mode,
                "allow_degraded": self.config.allow_degraded, "graph_depth": 0}
        data = self._sync(lambda: self.call_async("memory.retrieve", args))
        try:
            result = RetrieveWire.model_validate(data)
            if (result.token_budget != self.config.evidence_budget
                    or len(result.memories) > self.config.max_results
                    or (result.degraded and not self.config.allow_degraded)):
                raise ValueError()
            return result
        except Exception:
            raise OOMPError("invalid_evidence") from None

    def context(self, query, *, token_budget, recent_user_turns=()):
        """Explicit context.v1 retrieval; no legacy downgrade or raw-source request.

        Hints are supplied only by TRACE's owner/session-scoped recent loader.
        This boundary accepts no client-selected source IDs, scope or anchors.
        """
        if not isinstance(query, str) or not query.strip() or len(query) > 4096:
            raise OOMPError("query_limit")
        if type(token_budget) is not int or not 1 <= token_budget <= 32768:
            raise OOMPError("budget_limit")
        if not isinstance(recent_user_turns, (tuple, list)) or len(recent_user_turns) > 2:
            raise OOMPError("recent_hint_limit")
        hints = tuple(recent_user_turns)
        try:
            if (any(not isinstance(turn, str) or not turn.strip() or len(turn) > 4096
                    or "\0" in turn for turn in hints)
                    or sum(len(turn.encode("utf-8")) for turn in hints) > 2048):
                raise ValueError()
        except (ValueError, UnicodeEncodeError):
            raise OOMPError("recent_hint_limit") from None
        try:
            query.encode("utf-8")
        except UnicodeEncodeError:
            raise OOMPError("query_limit") from None
        args = {"query": query, "recent_user_turns": list(hints),
                "max_results": self.config.max_results, "token_budget": token_budget,
                "mode": self.config.retrieval_mode, "allow_degraded": self.config.allow_degraded,
                "graph_depth": 0, "explain": False}
        # include_source_content is deliberately omitted: the server default is
        # false, and TRACE never upgrades the existing read grant to read_source.
        data = self._sync(lambda: self.call_async("memory.context", args))
        if isinstance(data, dict) and data.get("context_contract_version") != CONTEXT_VERSION:
            raise OOMPError("unsupported")
        try:
            result = ContextResult.model_validate(data)
            if (result.token_budget != token_budget
                    or (result.evidence_packets and result.retrieval_status in {
                        "no_relevant_evidence", "budget_excluded", "unavailable", "unauthorized"})
                    or (result.retrieval_status == "found_relevant_evidence"
                        and not result.evidence_packets)
                    or any(unit.temporal_status.casefold() == "retracted"
                           or (unit.temporal_status.casefold() == "superseded"
                               and result.retrieval_intent != "historical_correction")
                           for unit in result.evidence_packets)
                    or len(result.evidence_packets) > self.config.max_results
                    or (result.degraded and not self.config.allow_degraded)
                    or result.query_plan is not None
                    or any(unit.resolution == "source_evidence"
                           or any(proof.quote is not None for proof in unit.source_proofs)
                           for unit in result.evidence_packets)):
                raise ValueError()
            return result
        except Exception:
            raise OOMPError("invalid_evidence") from None

    def call(self, name, arguments, token=None):
        return self._sync(lambda: self.call_async(name, arguments, token=token))

    async def call_async(self, name, arguments, token=None):
        try:
            import httpx2
            from mcp import Client
            from mcp.client.streamable_http import streamable_http_client
            from jsonschema import Draft202012Validator
        except ImportError:
            raise OOMPError("dependency_missing") from None

        class LimitedStream(httpx2.AsyncByteStream):
            def __init__(self, stream):
                self.stream = stream

            async def __aiter__(self):
                count = 0
                async for chunk in self.stream:
                    count += len(chunk)
                    if count > 1048576:
                        raise OOMPError("response_limit")
                    yield chunk

            async def aclose(self):
                await self.stream.aclose()

        class LocalTransport(httpx2.AsyncBaseTransport):
            def __init__(self):
                self.inner = httpx2.AsyncHTTPTransport(retries=0)

            async def handle_async_request(self, request):
                response = await self.inner.handle_async_request(request)
                if response.status_code in (401, 403):
                    await response.aclose()
                    raise OOMPError("authorization_failed")
                if response.status_code in (301, 302, 303, 307, 308):
                    await response.aclose()
                    raise OOMPError("redirect_rejected")
                return httpx2.Response(response.status_code, headers=response.headers,
                    extensions=response.extensions, stream=LimitedStream(response.stream))

            async def aclose(self):
                await self.inner.aclose()

        _protect_sdk_logs()
        private_token = _PRIVATE_OPERATION.set(True)
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with httpx2.AsyncClient(
                    transport=LocalTransport(), trust_env=False, follow_redirects=False,
                    headers={"Authorization": "Bearer " + (token or self.config.read_token.get_secret_value())},
                    timeout=self.config.timeout_seconds,
                ) as http:
                    async with Client(streamable_http_client(self.config.url, http_client=http)) as client:
                        catalog = (await client.list_tools()).tools
                        if client.server_info is None or client.server_info.name != "OOMP":
                            raise OOMPError("server_mismatch")
                        self.last_protocol_version = client.protocol_version
                        tools = {tool.name: tool for tool in catalog}
                        self.last_tool_names = tuple(sorted(tools))
                        if name not in tools:
                            raise OOMPError("capability_missing")
                        if name not in {"memory.retrieve", "memory.status", "memory.ingest", "memory.context"}:
                            raise OOMPError("capability_missing")
                        tool = tools[name]
                        Draft202012Validator(tool.input_schema).validate(arguments)
                        result = await client.call_tool(name, arguments)
                        data = result.structured_content
                        if result.is_error:
                            code = data.get("error", {}).get("code") if isinstance(data, dict) else None
                            allowed = {"forbidden", "unauthorized", "conflict", "busy", "resource_limit",
                                       "storage_unavailable", "embedding_unavailable", "invalid_parameters"}
                            if name == "memory.context":
                                allowed |= {"not_found", "unsupported", "unavailable", "timeout"}
                            raise OOMPError(code if code in allowed else "tool_failed")
                        if not isinstance(data, dict) or not tool.output_schema:
                            raise OOMPError("invalid_response")
                        if len(json.dumps(data, allow_nan=False).encode()) > 524288:
                            raise OOMPError("response_limit")
                        try:
                            Draft202012Validator(tool.output_schema).validate(data)
                        except Exception:
                            raise OOMPError("invalid_response") from None
                        return data
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise OOMPError(_error_code(error)) from None
        finally:
            _PRIVATE_OPERATION.reset(private_token)