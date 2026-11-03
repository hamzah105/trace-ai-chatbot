"""Synthetic context protocol/provenance tests; no real MCP, Mongo or inference."""
from copy import deepcopy
from datetime import datetime, timezone
import json

from bson import ObjectId
import mongomock
import pytest
from pydantic import ValidationError

from backend.services.oomp_client import OOMPClient, OOMPError
from backend.services.oomp_config import OOMPConfiguration
from backend.services.oomp_context_contracts import ContextResult
from backend.services.oomp_context_provenance import validate_context_provenance
from backend.services.oomp_contracts import event_identity, session_identity


OWNER = "fictional-p4b-owner"
INTERACTION = "a" * 24
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
ORIGINAL = "I have not moved. I am considering Lahore. 🙂 e\u0301 اردو 中文"


def configuration(**overrides):
    values = {"mode": "retrieve", "owner_id": OWNER, "read_token": "R" * 43,
              "owner_key": "O" * 43, "retrieval_api": "context_v1"}
    values.update(overrides)
    return OOMPConfiguration(**values)


def source_reference(role="user"):
    return {"source_system": "trace-ai", "external_event_id": INTERACTION,
            "timestamp": NOW.isoformat(), "session_id": session_identity("synthetic-session"),
            "turn_id": "trace-" + role + "-" + INTERACTION, "locator": None}


def evidence(**overrides):
    unit = {"unit_id": "synthetic-unit", "resolution": "canonical_fact",
            "content": "UNVERIFIED OOMP PARAPHRASE: the person moved.",
            "memory_ids": ["synthetic-memory"],
            "source_proofs": [{"memory_id": "synthetic-memory",
                "event_id": event_identity(OWNER, INTERACTION, "user"),
                "source_reference": source_reference(), "span_start": 11, "span_end": 16}],
            "assertion_kinds": ["tentative"], "temporal_status": "uncertain",
            "retrieval_score": 1, "derived": True, "uncertain": True}
    unit.update(overrides)
    return unit


def response(units=None, budget=4000, **overrides):
    units = [evidence()] if units is None else units
    packet = ""
    measured = 0
    if units:
        wrapper = {"context_contract_version": "oomp.context.v1", "evidence_packets": units,
                   "token_budget": budget, "counting_method": "utf8_bytes_upper_bound_v1",
                   "selected_context_bytes": 0}
        for _ in range(16):
            packet = json.dumps(wrapper, ensure_ascii=False, separators=(",", ":"))
            measured = len(packet.encode("utf-8"))
            if wrapper["selected_context_bytes"] == measured:
                break
            wrapper["selected_context_bytes"] = measured
        else:
            raise AssertionError("synthetic packet did not converge")
    references = []
    for unit in units:
        for proof in unit["source_proofs"]:
            if proof["source_reference"] not in references:
                references.append(proof["source_reference"])
    value = {"context_contract_version": "oomp.context.v1", "retrieval_intent": "plan_followup",
             "retrieval_status": "found_relevant_evidence" if units else "no_relevant_evidence",
             "evidence_packets": units, "source_references": references, "context_packet": packet,
             "selected_context_bytes": measured, "token_budget": budget,
             "counting_method": "utf8_bytes_upper_bound_v1", "source_data_untrusted": True,
             "budget_scope": "context_packet_only"}
    value.update(overrides)
    return value


def database():
    db = mongomock.MongoClient()["synthetic_p4b_protocol"]
    db.sessions.insert_one({"session_id": "synthetic-session", "user_id": OWNER})
    db.chat_history.insert_one({"_id": ObjectId(INTERACTION), "user_id": OWNER,
        "session_id": "synthetic-session", "user_message": ORIGINAL,
        "request_start_time": NOW, "llama_response": "A fictional assistant response.",
        "response_end_time": NOW, "oomp_publication": {"excluded": False}})
    return db


def test_selector_defaults_and_publication_identity_are_compatible():
    legacy = configuration(retrieval_api="retrieve")
    assert legacy.policy_id == configuration().policy_id
    assert OOMPConfiguration().retrieval_api == "retrieve"
    with pytest.raises(ValidationError):
        configuration(retrieval_api="automatic")


def test_context_client_requests_actual_budget_and_only_authorized_hints(monkeypatch):
    client = OOMPClient(configuration(evidence_budget=1200))
    seen = []

    async def fake_call(name, arguments, token=None):
        seen.append((name, arguments))
        return response(budget=1900)

    monkeypatch.setattr(client, "call_async", fake_call)
    result = client.context("What did I consider?", token_budget=1900,
                            recent_user_turns=("A complete fictional user hint.",))
    name, arguments = seen[0]
    assert name == "memory.context"
    assert arguments["token_budget"] == result.token_budget == 1900
    assert arguments["recent_user_turns"] == ["A complete fictional user hint."]
    assert arguments["explain"] is False and arguments["graph_depth"] == 0
    assert "include_source_content" not in arguments
    assert not {"tenant_id", "namespace", "principal_id", "owner_id", "anchors"} & arguments.keys()


@pytest.mark.parametrize("change", [
    lambda: response(budget=1800),
    lambda: response(query_plan={"retrieval_intent": "factual_recall"}),
    lambda: response([evidence(resolution="source_evidence")]),
    lambda: response([dict(evidence(), source_proofs=[dict(evidence()["source_proofs"][0], quote="moved")])]),
])
def test_context_client_rejects_changed_budget_and_unsolicited_detail(monkeypatch, change):
    client = OOMPClient(configuration())
    monkeypatch.setattr(client, "_sync", lambda factory: change())
    with pytest.raises(OOMPError, match="invalid_evidence"):
        client.context("A fictional recall query", token_budget=4000)


@pytest.mark.parametrize("version", [None, "oomp.context.v2"])
def test_context_client_reports_unsupported_version(monkeypatch, version):
    value = response(units=[])
    if version is None:
        value.pop("context_contract_version")
    else:
        value["context_contract_version"] = version
    client = OOMPClient(configuration())
    monkeypatch.setattr(client, "_sync", lambda factory: value)
    with pytest.raises(OOMPError, match="unsupported"):
        client.context("Fictional query", token_budget=4000)


@pytest.mark.parametrize("hints", [("🙂" * 513,), ("one", "two", "three"), ("\0",), (True,)])
def test_context_client_rejects_invalid_hints_before_transport(hints):
    with pytest.raises(OOMPError, match="recent_hint_limit"):
        OOMPClient(configuration()).context("Fictional query", token_budget=1000, recent_user_turns=hints)


def test_provenance_returns_original_full_source_and_preserves_role_uncertainty():
    units = validate_context_provenance(ContextResult.model_validate(response()), configuration(), database())
    source = units[0].sources[0]
    assert source.role == "user" and source.source_content == ORIGINAL
    assert source.excerpt == ORIGINAL[11:16] == "moved"
    assert "not moved" in source.source_content
    assert units[0].evidence.uncertain and units[0].evidence.derived
    assert units[0].evidence.content not in source.source_content
    assert "not moved" not in repr(source)


@pytest.mark.parametrize("mutation", [
    {"user_id": "foreign-owner"}, {"session_id": "foreign-session"},
    {"oomp_publication": {"excluded": True}},
])
def test_provenance_rejects_owner_session_and_exclusion(mutation):
    db = database()
    db.chat_history.update_one({"_id": ObjectId(INTERACTION)}, {"$set": mutation})
    with pytest.raises(OOMPError, match="scope_rejected"):
        validate_context_provenance(ContextResult.model_validate(response()), configuration(), db)


@pytest.mark.parametrize("field,value", [
    ("timestamp", "2026-01-03T03:04:05+00:00"), ("source_system", "foreign-source"),
    ("turn_id", "trace-assistant-" + INTERACTION), ("locator", "https://invalid.example/source"),
    ("session_id", session_identity("foreign-session")),
])
def test_provenance_rejects_forged_reference(field, value):
    unit = evidence()
    unit["source_proofs"][0]["source_reference"][field] = value
    with pytest.raises(OOMPError, match="scope_rejected"):
        validate_context_provenance(ContextResult.model_validate(response([unit])), configuration(), database())


def test_provenance_exact_unicode_code_point_offsets_and_quote():
    unit = evidence()
    proof = unit["source_proofs"][0]
    proof["span_start"] = ORIGINAL.index("🙂")
    proof["span_end"] = len(ORIGINAL)
    proof["quote"] = ORIGINAL[proof["span_start"]:]
    checked = validate_context_provenance(ContextResult.model_validate(response([unit])), configuration(), database())
    assert checked[0].sources[0].excerpt == "🙂 e\u0301 اردو 中文"
    proof["quote"] = "x" * len(proof["quote"])
    with pytest.raises(OOMPError, match="scope_rejected"):
        validate_context_provenance(ContextResult.model_validate(response([unit])), configuration(), database())


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(selected_context_bytes=value["selected_context_bytes"] + 1),
    lambda value: value.update(token_budget=1),
    lambda value: value.update(source_references=[]),
    lambda value: value.update(source_data_untrusted=1),
    lambda value: value.update(trace={"private_text": "not a counter"}),
    lambda value: value.update(unknown_scope="foreign-tenant"),
])
def test_wire_rejects_invalid_accounting_scope_and_types(mutate):
    value = response()
    mutate(value)
    with pytest.raises(ValidationError):
        ContextResult.model_validate(value)


def test_wire_rejects_duplicate_proof_and_boolean_score():
    for unit in [evidence(retrieval_score=True), evidence()]:
        if unit["retrieval_score"] is not True:
            unit["source_proofs"].append(deepcopy(unit["source_proofs"][0]))
        with pytest.raises(ValidationError):
            ContextResult.model_validate(response([unit]))


def test_empty_packet_and_denied_disclosure_rules():
    assert ContextResult.model_validate(response([])).selected_context_bytes == 0
    with pytest.raises(ValidationError):
        ContextResult.model_validate(response([], context_packet="{}", selected_context_bytes=2))
    with pytest.raises(ValidationError):
        ContextResult.model_validate(response([], retrieval_status="unauthorized", trace={"private_count": 1}))

@pytest.mark.parametrize("change", [
    {"span_end": len(ORIGINAL) + 1}, {"event_id": "forged-source-event"},
])
def test_provenance_rejects_out_of_range_span_and_wrong_event(change):
    unit = evidence()
    unit["source_proofs"][0].update(change)
    with pytest.raises(OOMPError, match="scope_rejected"):
        validate_context_provenance(ContextResult.model_validate(response([unit])), configuration(), database())


def test_provenance_rejects_noncanonical_source_identity_and_malformed_exclusion():
    unit = evidence()
    proof = unit["source_proofs"][0]
    proof["source_reference"]["external_event_id"] = INTERACTION.upper()
    proof["source_reference"]["turn_id"] = "trace-user-" + INTERACTION.upper()
    proof["event_id"] = event_identity(OWNER, INTERACTION.upper(), "user")
    with pytest.raises(OOMPError, match="scope_rejected"):
        validate_context_provenance(ContextResult.model_validate(response([unit])), configuration(), database())
    db = database()
    db.chat_history.update_one({"_id": ObjectId(INTERACTION)}, {"$set": {"oomp_publication.excluded": 1}})
    with pytest.raises(OOMPError, match="scope_rejected"):
        validate_context_provenance(ContextResult.model_validate(response()), configuration(), db)


@pytest.mark.parametrize("status", [
    "no_relevant_evidence", "budget_excluded", "unavailable", "unauthorized",
])
def test_context_client_rejects_sources_with_empty_or_denied_outcomes(monkeypatch, status):
    client = OOMPClient(configuration())
    value = response(retrieval_status=status)
    monkeypatch.setattr(client, "_sync", lambda factory: value)
    with pytest.raises(OOMPError, match="invalid_evidence"):
        client.context("A fictional lookup", token_budget=4000)


def test_context_client_rejects_empty_claim_of_found_evidence(monkeypatch):
    client = OOMPClient(configuration())
    value = response([], retrieval_status="found_relevant_evidence")
    monkeypatch.setattr(client, "_sync", lambda factory: value)
    with pytest.raises(OOMPError, match="invalid_evidence"):
        client.context("A fictional lookup", token_budget=4000)


@pytest.mark.parametrize("temporal_status,intent", [
    ("retracted", "factual_recall"), ("retracted", "historical_correction"),
    ("RETRACTED", "historical_correction"), ("superseded", "factual_recall"),
])
def test_context_client_rejects_retracted_and_current_use_superseded_units(
        monkeypatch, temporal_status, intent):
    client = OOMPClient(configuration())
    value = response([evidence(temporal_status=temporal_status)], retrieval_intent=intent)
    monkeypatch.setattr(client, "_sync", lambda factory: value)
    with pytest.raises(OOMPError, match="invalid_evidence"):
        client.context("A fictional lookup", token_budget=4000)


def test_context_client_allows_explicit_historical_supersession_without_current_claim(monkeypatch):
    client = OOMPClient(configuration())
    value = response([evidence(temporal_status="superseded")],
                     retrieval_intent="historical_correction")
    monkeypatch.setattr(client, "_sync", lambda factory: value)
    result = client.context("What was the fictional plan before correction?", token_budget=4000)
    assert result.retrieval_intent == "historical_correction"
    assert result.evidence_packets[0].temporal_status == "superseded"

@pytest.mark.parametrize("marker", [[], "", False, 0])
def test_provenance_rejects_falsy_malformed_publication_markers(marker):
    db = database()
    db.chat_history.update_one({"_id": ObjectId(INTERACTION)},
                               {"$set": {"oomp_publication": marker}})
    with pytest.raises(OOMPError, match="scope_rejected"):
        validate_context_provenance(ContextResult.model_validate(response()), configuration(), db)


@pytest.mark.parametrize("missing", [True, False])
def test_provenance_allows_absent_or_null_publication_metadata(missing):
    db = database()
    change = {"$unset": {"oomp_publication": ""}} if missing else {"$set": {"oomp_publication": None}}
    db.chat_history.update_one({"_id": ObjectId(INTERACTION)}, change)
    checked = validate_context_provenance(ContextResult.model_validate(response()), configuration(), db)
    assert checked[0].sources[0].source_content == ORIGINAL