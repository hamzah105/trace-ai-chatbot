"""Offline allocator controls; no MCP, MongoDB, Ollama or generated answers."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from backend.services.oomp_allocator import (
    AllocationError, MAX_EXCHANGES, MAX_HINT_BYTES, SAFETY_OVERHEAD,
    STATUSES, compose, prepare,
)


def config(**changes):
    values = dict(max_prompt_bytes=7000, num_ctx=8192, generation_reserve=512,
                  evidence_budget=1200, max_results=20)
    values.update(changes)
    return SimpleNamespace(**values)


def row(number=0, *, user=None, assistant=None):
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=number)
    return {
        "_id": f"{number + 1:024x}",
        "user_message": user if user is not None else f"Original user source {number}.",
        "llama_response": assistant if assistant is not None else f"Original assistant source {number}.",
        "timestamp": stamp, "request_start_time": stamp,
        "feedback": {"submitted": True, "rating": 2, "correctness": "Partial",
                     "length_type": "Lengthy"},
    }


@dataclass(frozen=True)
class Reference:
    def model_dump(self, *, mode):
        assert mode == "json"
        return {"source_system": "trace-ai", "external_event_id": "000000000000000000000099",
                "timestamp": "2026-10-01T00:00:00Z", "session_id": "trace-session-synthetic",
                "turn_id": "trace-user-000000000000000000000099", "locator": None}


def validated_unit(content="I am developing the Atlas project.", *, number=0, role="user",
                   span=None, derived=False, uncertain=False):
    start, end = span or (0, len(content))
    evidence = SimpleNamespace(
        unit_id=f"unit-{number}", resolution="direct_source", derived=derived,
        uncertain=uncertain, temporal_status="uncertain",
        assertion_kinds=("explicit_statement",),
        content="FORGED_PARAPHRASE_THE_USER_HAS_COMPLETED_THE_MOVE",
        retrieval_score=1.0, memory_ids=(f"memory-{number}",),
    )
    source = SimpleNamespace(
        role=role, interaction_id="000000000000000000000099",
        event_id=f"trace-event-{number}", memory_id=f"memory-{number}",
        source_reference=Reference(), span_start=start, span_end=end,
        excerpt=content[start:end], source_content=content,
    )
    return SimpleNamespace(evidence=evidence, sources=(source,))


def data(prompt):
    return json.loads(prompt.split("JSON DATA:\n", 1)[1].rsplit("\nTRACE RESPONSE:\n", 1)[0])


def assert_bounds(prompt, diagnostic, settings):
    actual = len(prompt.encode("utf-8"))
    assert diagnostic["prompt_bytes"] == diagnostic["prompt_token_upper_bound"] == actual
    assert actual <= settings.max_prompt_bytes
    assert actual + settings.generation_reserve + SAFETY_OVERHEAD <= settings.num_ctx


def test_same_long_eight_sources_fit_by_complete_suffix_without_starving_evidence():
    settings = config()
    rows = [row(index, user=f"user-{index} " + "u" * 500,
                assistant=f"assistant-{index} " + "a" * 500) for index in range(8)]
    # The legacy formatter includes all of these verbatim before its own overhead.
    assert sum(len(item["user_message"]) + len(item["llama_response"]) for item in rows) > 7000
    allocation = prepare(settings, "What is the Atlas project?", rows)
    prompt, diagnostic = compose(allocation, (validated_unit(),),
                                 status="found_relevant_evidence", coverage="partial")
    payload = data(prompt)
    recent = payload["RECENT_SESSION_CONTEXT"]["complete_exchanges"]
    assert 1 <= len(recent) < 8
    assert [item["source_interaction_id"] for item in recent] == [
        item["_id"] for item in rows[-len(recent):]
    ]
    for original, selected in zip(rows[-len(recent):], recent):
        assert selected["user_message"] == original["user_message"]
        assert selected["assistant_message"] == original["llama_response"]
        assert selected["submitted_feedback"] == original["feedback"]
    assert diagnostic["omitted_recent_interactions"] == 8 - len(recent)
    assert payload["RECENT_SESSION_CONTEXT"]["excluded_complete_exchanges_in_loaded_window"] == 8 - len(recent)
    assert allocation.evidence_budget > 0
    assert diagnostic["selected_context_units"] == 1
    assert_bounds(prompt, diagnostic, settings)


@pytest.mark.parametrize("message", [
    'Preserve quotes: "\\", newline:\n and JSON: {"x":"y"}.',
    "اردو کی اصل عبارت۔ 漢字 e\u0301 café 🙂",
])
def test_full_current_message_and_utf8_json_overhead_are_measured(message):
    settings = config(max_prompt_bytes=4500)
    original = row(user='Do not remove "not".\n漢字🙂', assistant="I have not confirmed it.")
    allocation = prepare(settings, message, [original])
    prompt, diagnostic = compose(allocation, status="no_relevant_evidence", coverage="unknown")
    payload = data(prompt)
    assert payload["CURRENT_USER_MESSAGE"] == message
    assert payload["RECENT_SESSION_CONTEXT"]["complete_exchanges"][0]["user_message"] == original["user_message"]
    assert len(prompt.encode("utf-8")) >= len(prompt)
    assert_bounds(prompt, diagnostic, settings)


@pytest.mark.parametrize("oversized", ["message", "latest_user", "latest_assistant"])
def test_impossible_mandatory_sources_are_rejected_without_clipping(oversized):
    message = "字" * 3000 if oversized == "message" else "Question?"
    original = row(user="u" * 9000 if oversized == "latest_user" else "User.",
                   assistant="a" * 9000 if oversized == "latest_assistant" else "Assistant.")
    with pytest.raises(AllocationError) as failure:
        prepare(config(), message, [original])
    assert failure.value.code == "mandatory_context_limit"


def test_newest_feedback_stays_attached_through_unavailable_fallback():
    rows = [row(index, assistant="a" * 1600) for index in range(8)]
    original = rows[-1]
    allocation = prepare(config(max_prompt_bytes=5000), "Current question.", rows)
    prompt, diagnostic = compose(allocation, status="timeout")
    latest = data(prompt)["RECENT_SESSION_CONTEXT"]["complete_exchanges"][-1]
    assert latest["source_interaction_id"] == original["_id"]
    assert latest["user_message"] == original["user_message"]
    assert latest["assistant_message"] == original["llama_response"]
    assert latest["submitted_feedback"] == original["feedback"]
    assert diagnostic["context_status"] == "timeout"
    assert data(allocation.fallback_prompt)["HISTORICAL_CONTEXT"]["status"] == "unavailable"


def test_older_relevant_whole_user_source_compacts_without_removing_negation():
    settings = config(max_prompt_bytes=5000)
    older = row(0, user="For the Atlas project I have not moved to Berlin; it is only a tentative plan.",
                assistant="ASSISTANT_ONLY_OLDER " + "a" * 6000)
    newest = row(1, user="Latest unrelated source.", assistant="Latest complete response.")
    allocation = prepare(settings, "Have I moved the Atlas project to Berlin?", [older, newest])
    prompt, diagnostic = compose(allocation, status="no_relevant_evidence")
    payload = data(prompt)["RECENT_SESSION_CONTEXT"]
    assert len(payload["complete_exchanges"]) == 1
    assert payload["complete_exchanges"][0]["source_interaction_id"] == newest["_id"]
    view, = payload["older_extractive_user_sources"]
    assert view["user_source_content"] == older["user_message"]
    assert view["source_span"] == {"start": 0, "end": len(older["user_message"])}
    assert view["source_interaction_id"] == older["_id"]
    assert view["source_timestamp"] == older["request_start_time"].isoformat()
    assert view["submitted_feedback"] == older["feedback"]
    assert "assistant response omitted" in view["attribution"]
    assert "unverified" in view["attribution"]
    assert "ASSISTANT_ONLY_OLDER" not in prompt
    assert diagnostic["compacted_user_sources"] == 1
    assert diagnostic["omitted_recent_interactions"] == 1
    assert allocation.evidence_budget > 0
    assert_bounds(prompt, diagnostic, settings)


def test_compaction_is_bounded_relevant_and_chronological():
    rows = [row(index, user=f"Atlas project original claim {index}.", assistant="a" * 6000)
            for index in range(3)]
    rows.append(row(3, user="Latest source.", assistant="Complete latest reply."))
    allocation = prepare(config(max_prompt_bytes=5500), "Explain the Atlas project.", rows)
    prompt, diagnostic = compose(allocation, status="coverage_unknown")
    views = data(prompt)["RECENT_SESSION_CONTEXT"]["older_extractive_user_sources"]
    assert [view["source_interaction_id"] for view in views] == [rows[1]["_id"], rows[2]["_id"]]
    assert diagnostic["compacted_user_sources"] == 2


@pytest.mark.parametrize("older_text", [
    "A separate subject with no matching referent.",
    "Atlas " + "x" * 4500,
])
def test_irrelevant_or_oversized_older_source_is_omitted_whole(older_text):
    older = row(0, user=older_text, assistant="a" * 6000)
    newest = row(1)
    allocation = prepare(config(max_prompt_bytes=4500), "Explain Atlas.", [older, newest])
    prompt, diagnostic = compose(allocation, status="coverage_unknown")
    assert data(prompt)["RECENT_SESSION_CONTEXT"]["older_extractive_user_sources"] == []
    assert diagnostic["compacted_user_sources"] == 0
    assert diagnostic["omitted_recent_interactions"] == 1


def test_hints_use_at_most_two_complete_authorized_user_sources():
    rows = [row(0, user="First complete hint.", assistant="ASSISTANT CANNOT BECOME A USER HINT"),
            row(1, user="Second complete hint."),
            row(2, user="🙂" * 600)]
    allocation = prepare(config(), "Current message is not a hint source.", rows)
    assert allocation.recent_user_turns == ("First complete hint.", "Second complete hint.")
    assert len(allocation.recent_user_turns) <= 2
    assert sum(len(text.encode("utf-8")) for text in allocation.recent_user_turns) <= MAX_HINT_BYTES
    assert all(text in {original["user_message"] for original in rows}
               for text in allocation.recent_user_turns)
    assert "Current message is not a hint source." not in allocation.recent_user_turns


def test_full_authoritative_source_keeps_negation_around_malicious_claimed_span():
    content = "I have not moved to Berlin. A completed move is only hypothetical."
    start = content.index("moved")
    unit = validated_unit(content, span=(start, start + len("moved")), derived=True, uncertain=True)
    allocation = prepare(config(), "Have I moved?", [row()])
    prompt, diagnostic = compose(allocation, (unit,), status="candidate_uncertain", coverage="partial")
    rendered = data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"][0]
    assert rendered["authoritative_sources"][0]["source_content"] == content
    assert rendered["authoritative_sources"][0]["validated_source_span"] == {
        "start": start, "end": start + len("moved")
    }
    assert rendered["derived"] is True and rendered["uncertain"] is True
    assert rendered["temporal_status"] == "uncertain"
    assert "FORGED_PARAPHRASE" not in prompt
    assert diagnostic["context_status"] == "candidate_uncertain"


@pytest.mark.parametrize("role", ["user", "assistant", "feedback"])
def test_actual_source_role_and_provenance_are_rendered(role):
    unit = validated_unit("Original attributed source.", role=role)
    prompt, _ = compose(prepare(config(), "Question.", []), (unit,),
                        status="found_relevant_evidence", coverage="unknown")
    source = data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"][0]["authoritative_sources"][0]
    assert source["role"] == role
    assert source["source_interaction_id"] == unit.sources[0].interaction_id
    assert source["event_id"] == unit.sources[0].event_id
    assert source["memory_id"] == unit.sources[0].memory_id
    assert source["source_reference"] == unit.sources[0].source_reference.model_dump(mode="json")


def test_oversized_authoritative_source_drops_entire_unit_and_reports_budget():
    allocation = prepare(config(max_prompt_bytes=4000), "Question.", [row()])
    unit = validated_unit("Whole source " + "z" * 6000)
    prompt, diagnostic = compose(allocation, (unit,), status="found_relevant_evidence", coverage="complete")
    context = data(prompt)["HISTORICAL_CONTEXT"]
    assert context["authoritative_source_units"] == []
    assert context["excluded_whole_units"] == 1
    assert context["status"] == diagnostic["context_status"] == "budget_excluded"
    assert diagnostic["retrieval_status"] == "found_relevant_evidence"
    assert diagnostic["selected_context_units"] == 0
    assert "Whole source" not in prompt


def test_a_later_smaller_whole_unit_can_fit_after_an_oversized_unit():
    allocation = prepare(config(max_prompt_bytes=4500), "Question.", [row()])
    units = (validated_unit("Too large " + "x" * 6000, number=0),
             validated_unit("A complete useful source.", number=1))
    prompt, diagnostic = compose(allocation, units, status="found_relevant_evidence", coverage="partial")
    selected = data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"]
    assert [unit["unit_id"] for unit in selected] == ["unit-1"]
    assert diagnostic["omitted_context_units"] == 1


@pytest.mark.parametrize("status", sorted(STATUSES - {"found_relevant_evidence"}))
def test_empty_and_failure_outcomes_remain_distinct_and_bounded(status):
    settings = config(max_prompt_bytes=3500)
    allocation = prepare(settings, "What did I say earlier?", [row()])
    prompt, diagnostic = compose(allocation, status=status, coverage="unknown")
    assert data(prompt)["HISTORICAL_CONTEXT"]["status"] == status
    assert diagnostic["context_status"] == status
    assert data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"] == []
    assert "does not mean no prior conversation exists" in prompt
    assert_bounds(prompt, diagnostic, settings)


def test_empty_found_claim_is_not_presented_as_successful_evidence():
    prompt, diagnostic = compose(prepare(config(), "Question.", []),
                                 status="found_relevant_evidence", coverage="unknown")
    assert diagnostic["context_status"] == "invalid_evidence"
    assert data(prompt)["HISTORICAL_CONTEXT"]["status"] == "invalid_evidence"


def test_model_allowance_can_tighten_prompt_ceiling_with_output_reserve():
    settings = config(max_prompt_bytes=7000, num_ctx=4000)
    allocation = prepare(settings, "Question.", [row()])
    prompt, diagnostic = compose(allocation, status="source_validation_unavailable")
    assert allocation.prompt_limit == 4000 - 512 - SAFETY_OVERHEAD
    assert_bounds(prompt, diagnostic, settings)


def test_worst_case_status_and_exclusion_metadata_is_reserved_before_retrieval():
    settings = config(max_prompt_bytes=3500)
    allocation = prepare(settings, "Question.", [row()])
    oversized = tuple(validated_unit("x" * 5000, number=index) for index in range(20))
    prompt, diagnostic = compose(allocation, oversized, status="candidate_uncertain",
                                 coverage="complete", degraded=True)
    assert diagnostic["omitted_context_units"] == 20
    assert diagnostic["context_status"] == "budget_excluded"
    assert_bounds(prompt, diagnostic, settings)


def test_allocator_is_deterministic_and_bounded_by_source_and_unit_counts():
    rows = [row(index, assistant="a" * 3500) for index in range(MAX_EXCHANGES)]
    settings = config(max_prompt_bytes=7000)
    assert prepare(settings, "Question.", rows) == prepare(settings, "Question.", rows)
    with pytest.raises(ValueError, match="Too many loaded"):
        prepare(settings, "Question.", rows + [row(33)])
    allocation = prepare(settings, "Question.", [])
    with pytest.raises(ValueError, match="Too many validated"):
        compose(allocation, tuple(validated_unit(number=index) for index in range(21)),
                status="found_relevant_evidence")
    with pytest.raises(ValueError, match="bounded sequence"):
        prepare(settings, "Question.", iter(rows))


def test_unknown_status_and_failure_sources_fail_closed():
    allocation = prepare(config(), "Question.", [])
    with pytest.raises(ValueError, match="Invalid context outcome"):
        compose(allocation, status="provider's private exception text")
    with pytest.raises(ValueError, match="Unavailable context"):
        compose(allocation, (validated_unit(),), status="unauthorized")



def test_truncated_history_discloses_unknown_rows_beyond_loaded_window():
    rows = [row(index, assistant="a" * 3500) for index in range(MAX_EXCHANGES)]
    allocation = prepare(config(), "Question.", rows, history_truncated=True)
    prompt, diagnostic = compose(allocation, status="coverage_unknown", coverage="unknown")
    recent = data(prompt)["RECENT_SESSION_CONTEXT"]
    assert recent["history_window_limit"] == MAX_EXCHANGES
    assert recent["history_scan_truncated"] is True
    assert recent["older_interaction_count_outside_window"] == "unknown"
    assert recent["exclusion_count_scope"] == "loaded_window_only"
    assert recent["excluded_complete_exchanges_in_loaded_window"] == MAX_EXCHANGES - len(allocation.recent)
    assert diagnostic["history_scan_truncated"] is True
    assert diagnostic["recent_exclusion_count_scope"] == "loaded_window_only"


def test_duplicate_full_source_proof_sets_are_one_evidence_unit_with_uncertainty():
    first = validated_unit("I have not moved to Berlin.", number=0)
    second = validated_unit("I have not moved to Berlin.", number=1, derived=True, uncertain=True)
    second.sources[0].event_id = first.sources[0].event_id
    second.evidence.temporal_status = "superseded"
    allocation = prepare(config(), "Have I moved?", [])
    prompt, diagnostic = compose(allocation, (first, second),
                                 status="candidate_uncertain", coverage="partial")
    context = data(prompt)["HISTORICAL_CONTEXT"]
    selected, = context["authoritative_source_units"]
    assert selected["uncertain"] is True and selected["derived"] is True
    assert selected["authoritative_sources"][0]["source_content"] == first.sources[0].source_content
    assert selected["duplicate_evidence_annotations"][0]["unit_id"] == "unit-1"
    assert selected["duplicate_evidence_annotations"][0]["temporal_status"] == "superseded"
    assert diagnostic["selected_context_units"] == 1
    assert diagnostic["received_context_units"] == 2
    assert diagnostic["deduplicated_context_units"] == context["deduplicated_units"] == 1
    assert diagnostic["omitted_context_units"] == 0


def test_opposing_full_source_claims_are_both_retained():
    units = (validated_unit("I have moved to Berlin.", number=0),
             validated_unit("Correction: I have not moved to Berlin.", number=1))
    prompt, diagnostic = compose(prepare(config(), "Have I moved?", []), units,
                                 status="candidate_uncertain", coverage="partial")
    selected = data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"]
    assert [item["authoritative_sources"][0]["source_content"] for item in selected] == [
        unit.sources[0].source_content for unit in units
    ]
    assert diagnostic["selected_context_units"] == 2
    assert diagnostic["deduplicated_context_units"] == 0


def test_repeated_original_source_within_one_unit_renders_body_once():
    unit = validated_unit("Original whole source.")
    duplicate = SimpleNamespace(**vars(unit.sources[0]))
    duplicate.memory_id = "memory-duplicate-path"
    unit.sources = (unit.sources[0], duplicate)
    prompt, diagnostic = compose(prepare(config(), "Question.", []), (unit,),
                                 status="found_relevant_evidence")
    selected = data(prompt)["HISTORICAL_CONTEXT"]["authoritative_source_units"][0]
    source, = selected["authoritative_sources"]
    assert source["source_content"] == "Original whole source."
    assert source["additional_source_proofs"][0]["memory_id"] == "memory-duplicate-path"
    assert diagnostic["selected_context_units"] == 1


def test_exact_mandatory_boundary_can_have_zero_remaining_evidence_budget():
    settings = config(evidence_budget=32768)
    initial = prepare(settings, "Question.", [])
    mandatory_ceiling = settings.max_prompt_bytes - initial.evidence_budget
    bounded = config(max_prompt_bytes=mandatory_ceiling, evidence_budget=32768)
    allocation = prepare(bounded, "Question.", [])
    assert allocation.evidence_budget == 0
    prompt, diagnostic = compose(allocation, status="budget_excluded", coverage="unknown")
    assert diagnostic["context_status"] == "budget_excluded"
    assert_bounds(prompt, diagnostic, bounded)
