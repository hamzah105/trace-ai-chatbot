"""Local fictional P4B route fixtures; never start services or read gold data.

These fixed security/regression examples are separate from the frozen benchmark
source/gold fixtures. MCP is replaced at call_async and inference is always fake.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId

from backend.services.oomp_client import OOMPClient, OOMPError
from backend.services.oomp_config import get_configuration
from backend.services.oomp_contracts import event_identity, session_identity
from stage8_support import OWNER, SESSION, activate, chat_row

SERVER = SimpleNamespace(url="http://127.0.0.1:9/mcp")
HISTORICAL_SESSION = "p4b-fictional-historical-session"
SOURCE_TEXT = "I have not moved to Lahore. I am only considering that possibility."
FORGED_PARAPHRASE = "The user has completed a move to Lahore."
FAKE_ANSWER = "Synthetic P4B response; no model was called."


def activate_context(monkeypatch, tmp_path, *, mode="retrieve", **changes):
    activate(monkeypatch, SERVER, tmp_path, mode=mode, retrieval_api="context_v1", **changes)
    # The unchanged Stage 8 activate helper intentionally knows only old fields.
    monkeypatch.setenv("TRACE_OOMP_RETRIEVAL_API", "context_v1")
    for field in ("evidence_budget", "max_results", "max_prompt_bytes", "num_ctx", "generation_reserve"):
        if field in changes:
            monkeypatch.setenv("TRACE_OOMP_" + field.upper(), str(changes[field]))
    return get_configuration()


def fixed_row(number=0, *, text=None, owner=OWNER, session=SESSION, assistant=None):
    row = chat_row(number, owner=owner, session=session,
                   text=text if text is not None else "A complete fictional current-session user source.")
    row["_id"] = ObjectId(f"{4096 + number:024x}")
    if assistant is not None:
        row["llama_response"] = assistant
    return row


def insert_rows(database, rows):
    """Insert test-owned rows and explicit owner/session links into mongomock."""
    for row in rows:
        if not database["sessions"].find_one(
                {"session_id": row["session_id"], "user_id": row["user_id"]}):
            database["sessions"].insert_one({
                "session_id": row["session_id"], "user_id": row["user_id"],
                "status": "active", "message_count": 0,
                "created_at": row["timestamp"], "updated_at": row["timestamp"], "topics": ["General"],
            })
        database["chat_history"].insert_one(deepcopy(row))


def original_content(row, role):
    if role == "user":
        return row["user_message"], row["request_start_time"]
    if role == "assistant":
        return row["llama_response"], row["response_end_time"]
    feedback = row["feedback"]
    return (json.dumps({key: feedback[key] for key in ("rating", "correctness", "length_type")},
                       sort_keys=True, separators=(",", ":")), feedback["submitted_at"])


def context_unit(row, *, role="user", span=None, quote=None, content=FORGED_PARAPHRASE,
                 unit_id="p4b-unit-1", memory_id="p4b-memory-1"):
    original, occurred = original_content(row, role)
    start, end = span if span is not None else (0, len(original))
    identifier = str(row["_id"])
    proof = {"memory_id": memory_id, "event_id": event_identity(row["user_id"], identifier, role),
             "source_reference": {"source_system": "trace-ai", "external_event_id": identifier,
                 "timestamp": occurred.isoformat(), "session_id": session_identity(row["session_id"]),
                 "turn_id": "trace-" + role + "-" + identifier, "locator": None},
             "span_start": start, "span_end": end}
    if quote is not None:
        proof["quote"] = quote
    return {"unit_id": unit_id, "resolution": "canonical_fact", "content": content,
            "memory_ids": [memory_id], "source_proofs": [proof], "assertion_kinds": ["tentative"],
            "temporal_status": "uncertain", "retrieval_score": 1.0, "derived": True, "uncertain": True}


def context_response(arguments, *, units=(), status="no_relevant_evidence", coverage="complete",
                     degraded=False):
    """Build one deterministic MCP response with exact complete packet accounting."""
    budget = arguments["token_budget"]
    units = list(deepcopy(units))
    packet, measured = "", 0
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
            raise AssertionError("Synthetic context packet accounting did not converge")
        if measured > budget:
            raise AssertionError("Fixed test evidence exceeds the requested transport budget")
    references = []
    for unit in units:
        for proof in unit["source_proofs"]:
            if proof["source_reference"] not in references:
                references.append(proof["source_reference"])
    return {"context_contract_version": "oomp.context.v1", "retrieval_intent": "plan_followup",
            "retrieval_status": status, "evidence_packets": units, "source_references": references,
            "context_packet": packet, "selected_context_bytes": measured, "token_budget": budget,
            "counting_method": "utf8_bytes_upper_bound_v1", "degraded": degraded,
            "coverage": coverage, "source_data_untrusted": True, "budget_scope": "context_packet_only"}


@contextmanager
def synthetic_mcp(*, units=(), status="no_relevant_evidence", coverage="complete", degraded=False,
                  error=None, mutate=None):
    calls = []

    async def fake_call(client, name, arguments, token=None):
        calls.append((name, deepcopy(arguments), token))
        if name != "memory.context":
            raise AssertionError("Context mode attempted a legacy, status or write tool")
        if error is not None:
            raise OOMPError(error)
        result = context_response(arguments, units=units, status=status,
                                  coverage=coverage, degraded=degraded)
        if mutate is not None:
            mutate(result)
        return result

    with patch.object(OOMPClient, "call_async", fake_call):
        yield calls


def prompt_data(prompt):
    return json.loads(prompt.split("JSON DATA:\n", 1)[1].rsplit("\nTRACE RESPONSE:\n", 1)[0])


def saved_interaction(database, response):
    return database["chat_history"].find_one({"_id": ObjectId(response["interaction_id"])})


def assert_prompt_capacity(prompt, diagnostics, config):
    measured = len(prompt.encode("utf-8"))
    assert measured == diagnostics["prompt_bytes"] <= config.max_prompt_bytes
    assert measured == diagnostics["prompt_token_upper_bound"]
    assert measured + config.generation_reserve + diagnostics["safety_overhead"] <= config.num_ctx
