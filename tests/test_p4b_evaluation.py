"""Frozen fictional evaluation: source retention, budget, and 33 negative controls."""
from copy import deepcopy
import json
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from backend.routes.chat import ChatRequest
from backend.services.oomp_allocator import AllocationError, prepare
from backend.services.oomp_config import OOMPConfiguration
from p4b_evaluation import (
    enable, evaluate_long_eight, evaluate_scenarios, fixtures, make_units,
    orchestrate, rendered_sources, run_negative_control, source_database, source_row,
)


def write_report(tmp_path, name, report, record_property):
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (tmp_path / name).write_text(text, encoding="utf-8")
    record_property(name, text)


def test_frozen_three_session_source_retention(monkeypatch, tmp_path, record_property):
    report = evaluate_scenarios(monkeypatch, tmp_path)
    write_report(tmp_path, "p4b-frozen-scenarios.json", report, record_property)
    assert len(report["cases"]) == 12
    assert report["source_recall"]["matched"] == report["source_recall"]["gold_pairs"] == 16
    assert report["source_recall"]["macro_recall"] == 1
    assert report["source_precision"]["relevant_included"] == report["source_precision"]["included_pairs"] == 16
    assert report["prompt_integrity"]["valid"] == report["prompt_integrity"]["included"] == 16
    assert report["continuity_prompt_claims"] == {"retained": 5, "opportunities": 5}
    assert report["temporal_correction_prompt"] == {"preserved": 1, "cases": 1}
    assert report["fake_stub_personal_abstention"] == {"successes": 4, "cases": 4, "false_assertions": 0}
    assert report["cross_owner"] == {"included": 0, "foreign_injected": 2, "foreign_rejected": 2}


def test_frozen_identical_long_eight_old_413_new_finite(monkeypatch, tmp_path, record_property):
    report = evaluate_long_eight(monkeypatch, tmp_path)
    write_report(tmp_path, "p4b-frozen-long-eight.json", report, record_property)
    assert report["legacy_http_status"] == 413 and report["context_http_status"] == 200
    assert report["legacy_prompt_bytes"] > 32768 >= report["context_prompt_bytes"]
    assert report["selected_recent"] >= 1 and report["omitted_recent"] > 0
    assert report["selected_recent"] + report["omitted_recent"] == 8
    assert report["selected_context_units"] == 3
    assert report["generation_reserve"] == 512 and report["num_predict"] == 140


CONTROL_IDS = [control["control_id"] for control in fixtures()["negative-controls"]["controls"]]
assert len(CONTROL_IDS) == len(set(CONTROL_IDS)) == 33


@pytest.mark.parametrize("control_id", CONTROL_IDS)
def test_each_frozen_negative_control(control_id, monkeypatch, tmp_path, record_property):
    report = run_negative_control(control_id, monkeypatch, tmp_path)
    write_report(tmp_path, "p4b-control-" + control_id + ".json", report, record_property)
    assert report["passed"] is True


def test_frozen_boundary_inputs_preserve_public_admission_guards(monkeypatch, tmp_path, record_property):
    data = fixtures()
    config = enable(monkeypatch, tmp_path, data)
    boundaries = {case["id"]: case for case in data["workloads"]["boundary_workloads"]}
    # This frozen 88,000-character workload precedes the allocator at public
    # ChatRequest validation. Its true public result is 422, not a claimed 413.
    with pytest.raises(ValidationError):
        ChatRequest(message=boundaries["oversized-current"]["current_message"],
                    session_id="p4b-session-2", user_id=config.owner_id)
    # Frozen cap256 intentionally cannot form a valid deployed configuration.
    # Keep that guard; demonstrate the pure allocator minimum separately.
    with pytest.raises(ValidationError):
        OOMPConfiguration(max_prompt_bytes=boundaries["mandatory-minimum"]["max_prompt_bytes"])
    tiny = SimpleNamespace(**{field: getattr(config, field) for field in (
        "max_prompt_bytes", "num_ctx", "generation_reserve", "max_results", "evidence_budget")})
    tiny.max_prompt_bytes = boundaries["mandatory-minimum"]["max_prompt_bytes"]
    with pytest.raises(AllocationError):
        prepare(tiny, "Keep this complete current instruction.", [])
    db, rows = source_database(data)
    prompt, diagnostics, _ = orchestrate(db, config,
        boundaries["unicode-json-overhead"]["current_message"], units=make_units([rows["p4b-source-unicode"]]))
    assert rendered_sources(prompt)[0]["source_content"] == rows["p4b-source-unicode"]["user_message"]
    write_report(tmp_path, "p4b-frozen-boundaries.json", {
        "oversized_current": {"public_status": 422, "stage": "ChatRequest", "model_calls": 0},
        "mandatory_minimum": {"public_configuration": "rejected", "pure_allocator": "AllocationError", "model_calls": 0},
        "unicode_json": {"prompt_bytes": diagnostics["prompt_bytes"], "exact_source_preserved": True},
        "valid_public_request_413": "covered by test_impossible_unicode_current_message_stops_before_mcp_or_model",
    }, record_property)


def test_frozen_large_source_excluded_whole_and_disclosed(monkeypatch, tmp_path, record_property):
    data = fixtures()
    config = enable(monkeypatch, tmp_path, data)
    # Exact frozen long-eight source, rendered independently at a finite7000
    # deployment cap. The small wire proof fits while its whole source does not.
    monkeypatch.setenv("TRACE_OOMP_MAX_PROMPT_BYTES", "7000")
    monkeypatch.setenv("TRACE_OOMP_NUM_CTX", "8192")
    from backend.services.oomp_config import get_configuration
    config = get_configuration()
    db, _ = source_database(data)
    source = source_row(data["workloads"]["long_eight"]["interactions"][0])
    db.sessions.insert_one({"session_id": source["session_id"], "user_id": config.owner_id})
    db.chat_history.insert_one(deepcopy(source))
    prompt, diagnostics, _ = orchestrate(db, config, "Which historical engineering note is available?",
                                        units=make_units([source]))
    assert rendered_sources(prompt) == []
    assert diagnostics["context_status"] == "budget_excluded"
    assert diagnostics["omitted_context_units"] == 1
    assert source["user_message"] not in prompt
    write_report(tmp_path, "p4b-frozen-whole-unit.json", {
        "source_code_points": len(source["user_message"]), "status": diagnostics["context_status"],
        "excluded_units": diagnostics["omitted_context_units"], "prompt_bytes": diagnostics["prompt_bytes"],
        "wire_bytes": diagnostics["evidence_budget_used"],
    }, record_property)

def test_context_mode_completed_exchange_feedback_publication_idempotency(monkeypatch, tmp_path, record_property):
    from bson import ObjectId
    from unittest.mock import patch
    from backend.routes.chat import chat
    from backend.routes.feedback import FeedbackRequest, submit_feedback
    from backend.services.oomp_contracts import event_identity
    from backend.services.oomp_publisher import Publisher
    from p4b_support import activate_context, synthetic_mcp
    from stage8_support import http_request, route_database

    data = fixtures()
    db, _ = source_database(data)
    config = activate_context(monkeypatch, tmp_path, mode="retrieve_and_ingest",
                              owner_id=data["sources"]["owner_id"])
    before = list(db.chat_history.find({}).sort("_id", 1))
    with route_database(db), synthetic_mcp() as reads, \
         patch("backend.routes.chat.generate_response", return_value="Synthetic adapter answer; no inference."):
        response = chat(ChatRequest(message="Continue the fictional ORBIT42 discussion.",
                       user_id=config.owner_id, session_id="p4b-session-2"),
                       http_request(owner=config.owner_id))
    identifier = response["interaction_id"]
    assert [name for name, _, _ in reads] == ["memory.context"]
    accepted = []

    class ReceiptClient:
        def call(self, name, arguments, token=None):
            assert name == "memory.ingest"
            accepted.append(deepcopy(arguments))
            return {"acceptance": "durably_stored", "event_id": arguments["event_id"],
                    "worker_started_by_request": False}

    publisher = Publisher(db, config, client=ReceiptClient())
    assert publisher.deliver(identifier, "feedback") == "not_claimed"
    for role in ("user", "assistant"):
        assert publisher.deliver(identifier, role) == "delivered"
        assert publisher.deliver(identifier, role) == "not_claimed"
    with route_database(db):
        result = submit_feedback(FeedbackRequest(interaction_id=identifier, rating=4,
            correctness="Correct", length_type="To the Point", user_id=config.owner_id,
            session_id="p4b-session-2"))
    assert result["success"] is True
    assert publisher.deliver(identifier, "feedback") == "delivered"
    assert publisher.deliver(identifier, "feedback") == "not_claimed"
    row = db.chat_history.find_one({"_id": ObjectId(identifier)})
    states = row["oomp_publication"]["events"]
    assert set(states) == {"user", "assistant", "feedback"}
    assert all(state["status"] == "delivered" and state["attempts"] == 1 for state in states.values())
    identities = [delivery["event_id"] for delivery in accepted]
    assert len(identities) == len(set(identities)) == 3
    assert set(identities) == {event_identity(config.owner_id, identifier, role)
                               for role in ("user", "assistant", "feedback")}
    assert row["oomp_publication"]["policy_id"] == config.model_copy(update={"retrieval_api": "retrieve"}).policy_id
    assert db.chat_history.count_documents({}) == len(before) + 1
    for original in before:
        assert db.chat_history.find_one({"_id": original["_id"]}) == original
    write_report(tmp_path, "p4b-publication-idempotency.json", {
        "mock_context_calls": 1, "completed_new_interactions": 1, "accepted_ingest_calls": len(accepted),
        "unique_event_ids": len(set(identities)), "stored_outbox_roles": len(states),
        "duplicate_accepted_delivery_writes": len(identities) - len(set(identities)),
        "retry_attempts": 0, "repeated_deliveries_not_claimed": 3,
        "feedback_before_submission_not_claimed": True,
    }, record_property)