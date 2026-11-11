"""Actual chat-route regressions with fictional Mongo/MCP and fake inference.

No external_server fixture, OOMP provider, real MongoDB, network or model is used.
These controls validate orchestration/source boundaries, not answer quality.
"""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from backend.routes.chat import ChatRequest, build_context_prompt, chat
from backend.services.oomp_client import OOMPClient, OOMPError
from backend.services.oomp_config import get_configuration
from p4b_support import (
    FAKE_ANSWER, FORGED_PARAPHRASE, HISTORICAL_SESSION, SERVER, SOURCE_TEXT,
    activate_context, assert_prompt_capacity, context_unit, fixed_row,
    insert_rows, original_content, prompt_data, saved_interaction, synthetic_mcp,
)
from stage8_support import OWNER, OTHER, SESSION, activate, http_request, route_database


@pytest.mark.parametrize("mode", ["off", "retrieve"])
def test_default_off_and_legacy_paths_keep_exact_original_prompt(database, monkeypatch, tmp_path, mode):
    row = fixed_row(1, text="The fictional user requested a short reply.")
    insert_rows(database, [row])
    if mode == "off":
        monkeypatch.setenv("TRACE_OOMP_MODE", "off")
        # Off mode must still ignore optional integration selectors/settings.
        monkeypatch.setenv("TRACE_OOMP_RETRIEVAL_API", "context_v1")
    else:
        activate(monkeypatch, SERVER, tmp_path, mode="retrieve")
        monkeypatch.delenv("TRACE_OOMP_RETRIEVAL_API", raising=False)
    assert get_configuration().retrieval_api == "retrieve"
    message = "Repeat the fictional request."
    with route_database(database):
        expected = build_context_prompt(SESSION, OWNER, message)
        with patch.object(OOMPClient, "context") as adaptive, \
             patch.object(OOMPClient, "retrieve", side_effect=OOMPError("unavailable")) as legacy, \
             patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
            response = chat(ChatRequest(message=message, session_id=SESSION, user_id=OWNER), http_request())
    model.assert_called_once_with(expected)
    adaptive.assert_not_called()
    if mode == "off":
        legacy.assert_not_called()
        assert "oomp_diagnostics" not in saved_interaction(database, response)
    else:
        legacy.assert_called_once_with(message)
        assert saved_interaction(database, response)["oomp_diagnostics"]["error_code"] == "unavailable"
    assert database["chat_history"].count_documents({}) == 2


@pytest.mark.parametrize("guard,expected", [
    ("pending", 409), ("ended", 409), ("session_owner", 403), ("http_owner", 403),
])
def test_context_route_guards_precede_every_mcp_and_model_call(
        database, monkeypatch, tmp_path, guard, expected):
    activate_context(monkeypatch, tmp_path)
    if guard == "pending":
        row = fixed_row(1)
        row["feedback"]["submitted"] = False
        row["feedback"]["submitted_at"] = None
        insert_rows(database, [row])
    elif guard == "ended":
        database["sessions"].update_one({"session_id": SESSION}, {"$set": {"status": "ended"}})
    elif guard == "session_owner":
        database["sessions"].update_one({"session_id": SESSION}, {"$set": {"user_id": OTHER}})
    count = database["chat_history"].count_documents({})
    owner = OTHER if guard == "http_owner" else OWNER
    with route_database(database), patch.object(OOMPClient, "context") as adaptive, \
         patch.object(OOMPClient, "retrieve") as legacy, \
         patch.object(OOMPClient, "call_async") as transport, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        with pytest.raises(HTTPException) as failure:
            chat(ChatRequest(message="A guarded fictional question.", session_id=SESSION, user_id=OWNER),
                 http_request(owner=owner))
    assert failure.value.status_code == expected
    adaptive.assert_not_called()
    legacy.assert_not_called()
    transport.assert_not_called()
    model.assert_not_called()
    assert database["chat_history"].count_documents({}) == count


def test_identical_long_eight_legacy_413_and_adaptive_complete_suffix(
        database, monkeypatch, tmp_path):
    rows = []
    for number in range(8):
        user = ("u" + str(number) + ":").ljust(500, "u")
        assistant = ("a" + str(number) + ":").ljust(500, "a")
        rows.append(fixed_row(number, text=user, assistant=assistant))
    rows[-1]["feedback"].update(rating=1, correctness="Incorrect", length_type="Short")
    insert_rows(database, rows)
    before = list(database["chat_history"].find({}).sort("_id", 1))
    activate(monkeypatch, SERVER, tmp_path, mode="retrieve")
    monkeypatch.delenv("TRACE_OOMP_RETRIEVAL_API", raising=False)
    message = "Continue the fictional conversation with all necessary qualifications."
    request = ChatRequest(message=message, session_id=SESSION, user_id=OWNER)
    with route_database(database), patch.object(OOMPClient, "retrieve") as legacy, \
         patch.object(OOMPClient, "context") as adaptive, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        with pytest.raises(HTTPException) as failure:
            chat(request, http_request())
    assert failure.value.status_code == 413
    legacy.assert_not_called()
    adaptive.assert_not_called()
    model.assert_not_called()
    assert list(database["chat_history"].find({}).sort("_id", 1)) == before

    config = activate_context(monkeypatch, tmp_path)
    with route_database(database), synthetic_mcp() as calls, \
         patch.object(OOMPClient, "retrieve") as legacy, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        response = chat(request, http_request())
    legacy.assert_not_called()
    assert len(calls) == 1 and calls[0][0] == "memory.context"
    prompt = model.call_args.args[0]
    data = prompt_data(prompt)
    saved = saved_interaction(database, response)
    diagnostics = saved["oomp_diagnostics"]
    assert data["CURRENT_USER_MESSAGE"] == message
    recent = data["RECENT_SESSION_CONTEXT"]
    retained = recent["complete_exchanges"]
    assert 1 <= len(retained) < 8
    assert [entry["source_interaction_id"] for entry in retained] == [
        str(row["_id"]) for row in rows[-len(retained):]]
    for entry, original in zip(retained, rows[-len(retained):]):
        assert entry["user_message"] == original["user_message"]
        assert entry["assistant_message"] == original["llama_response"]
    assert retained[-1]["submitted_feedback"] == {
        "submitted": True, "rating": 1, "correctness": "Incorrect", "length_type": "Short"}
    assert recent["excluded_complete_exchanges_in_loaded_window"] == 8 - len(retained)
    assert diagnostics["omitted_recent_interactions"] == 8 - len(retained)
    assert_prompt_capacity(prompt, diagnostics, config)
    assert len(prompt.encode("utf-8")) <= 7000
    assert database["chat_history"].count_documents({}) == 9
    for original in before:
        assert database["chat_history"].find_one({"_id": original["_id"]}) == original


def test_impossible_unicode_current_message_stops_before_mcp_or_model(database, monkeypatch, tmp_path):
    activate_context(monkeypatch, tmp_path)
    insert_rows(database, [fixed_row(1)])
    message = "中" * 3000  # Valid ChatRequest length, at least 9000 UTF-8 bytes.
    with route_database(database), patch.object(OOMPClient, "context") as adaptive, \
         patch.object(OOMPClient, "retrieve") as legacy, \
         patch.object(OOMPClient, "call_async") as transport, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        with pytest.raises(HTTPException) as failure:
            chat(ChatRequest(message=message, session_id=SESSION, user_id=OWNER), http_request())
    assert failure.value.status_code == 413
    adaptive.assert_not_called()
    legacy.assert_not_called()
    transport.assert_not_called()
    model.assert_not_called()
    assert database["chat_history"].count_documents({}) == 1


def test_hints_are_complete_authorized_recent_user_sources_only(database, monkeypatch, tmp_path):
    activate_context(monkeypatch, tmp_path)
    first = fixed_row(1, text="Owned short first user source.", assistant="ASSISTANT-ONLY-HINT-MARKER")
    second = fixed_row(2, text="中" * 300, assistant="ASSISTANT-ONLY-HINT-MARKER")
    third = fixed_row(3, text="🙂" * 300, assistant="ASSISTANT-ONLY-HINT-MARKER")
    foreign = fixed_row(90, owner=OTHER, text="FOREIGN-OWNER-HINT-MARKER")
    other_session = fixed_row(91, session="p4b-other-session", text="OTHER-SESSION-HINT-MARKER")
    excluded = fixed_row(92, text="EXCLUDED-HINT-MARKER")
    excluded["oomp_publication"] = {"excluded": True}
    insert_rows(database, [first, second, third, foreign, other_session, excluded])
    # Extra request-body fields have no authority and cannot supply hints/IDs.
    request = ChatRequest(message="Which fictional options were discussed?", session_id=SESSION, user_id=OWNER,
                          recent_user_turns=["ATTACKER-BODY-HINT"], source_ids=[str(foreign["_id"])])
    with route_database(database), synthetic_mcp() as calls, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        response = chat(request, http_request())
    assert len(calls) == 1
    hints = calls[0][1]["recent_user_turns"]
    assert hints == [first["user_message"], third["user_message"]]
    assert len(hints) <= 2 and sum(len(text.encode("utf-8")) for text in hints) <= 2048
    for hint in hints:
        assert hint in {first["user_message"], second["user_message"], third["user_message"]}
    assert not {"source_ids", "tenant_id", "namespace", "principal_id", "owner_id"} & calls[0][1].keys()
    prompt = model.call_args.args[0]
    for marker in ("FOREIGN-OWNER-HINT-MARKER", "OTHER-SESSION-HINT-MARKER", "EXCLUDED-HINT-MARKER", "ATTACKER-BODY-HINT"):
        assert marker not in prompt and all(marker not in hint for hint in hints)
    diagnostics = saved_interaction(database, response)["oomp_diagnostics"]
    assert diagnostics["recent_user_hint_count"] == len(hints)
    assert diagnostics["recent_user_hint_bytes"] == sum(len(text.encode("utf-8")) for text in hints)


@pytest.mark.parametrize("status,coverage", [
    ("found_relevant_evidence", "complete"), ("no_relevant_evidence", "complete"),
    ("budget_excluded", "complete"), ("index_incomplete", "partial"),
    ("coverage_unknown", "unknown"), ("candidate_uncertain", "partial"),
    ("unavailable", "unknown"), ("unauthorized", "unknown"),
])
def test_wire_statuses_remain_truthful_without_legacy_downgrade(
        database, monkeypatch, tmp_path, status, coverage):
    config = activate_context(monkeypatch, tmp_path)
    source = fixed_row(2, session=HISTORICAL_SESSION, text=SOURCE_TEXT)
    insert_rows(database, [fixed_row(1), source])
    units = [context_unit(source)] if status in {"found_relevant_evidence", "candidate_uncertain"} else []
    message = "P4B-PRIVATE-STATUS-QUESTION"
    with route_database(database), synthetic_mcp(units=units, status=status, coverage=coverage) as calls, \
         patch.object(OOMPClient, "retrieve") as legacy, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        expected_standalone = build_context_prompt(SESSION, OWNER, message)
        if status == "unauthorized":
            with pytest.raises(HTTPException) as denied:
                chat(ChatRequest(message=message, session_id=SESSION, user_id=OWNER), http_request())
            assert denied.value.status_code == 403
        else:
            response = chat(ChatRequest(message=message, session_id=SESSION, user_id=OWNER), http_request())
    legacy.assert_not_called()
    assert len(calls) == 1 and calls[0][0] == "memory.context"
    if status == "unauthorized":
        model.assert_not_called()
        assert database["chat_history"].count_documents({}) == 2
        return
    prompt = model.call_args.args[0]
    diagnostics = saved_interaction(database, response)["oomp_diagnostics"]
    if status == "unavailable":
        assert prompt == expected_standalone and "HISTORICAL_CONTEXT" not in prompt
        assert diagnostics["context_status"] == status
        assert diagnostics["prompt_mode"] == "standalone"
        assert_prompt_capacity(prompt, diagnostics, config)
        return
    data = prompt_data(prompt)
    assert data["HISTORICAL_CONTEXT"]["status"] == status
    assert diagnostics["context_status"] == status
    assert data["CURRENT_USER_MESSAGE"] == message
    assert "not in current session memory" not in prompt
    assert "does not mean no prior conversation exists" in prompt
    assert_prompt_capacity(prompt, diagnostics, config)
    if units:
        assert data["HISTORICAL_CONTEXT"]["authoritative_source_units"]
        assert SOURCE_TEXT in prompt and FORGED_PARAPHRASE not in prompt
    else:
        assert data["HISTORICAL_CONTEXT"]["authoritative_source_units"] == []


@pytest.mark.parametrize("code,expected", [
    ("capability_missing", "context_unsupported"), ("unsupported", "context_unsupported"),
    ("not_found", "context_disabled"), ("timeout", "timeout"),
    ("authorization_failed", "unauthorized"), ("unauthorized", "unauthorized"),
    ("forbidden", "unauthorized"), ("unavailable", "unavailable"), ("busy", "unavailable"),
])
def test_context_failures_keep_bounded_truthful_status_and_sanitized_logs(
        database, monkeypatch, tmp_path, caplog, code, expected):
    config = activate_context(monkeypatch, tmp_path)
    source = fixed_row(1, text="P4B-PRIVATE-RECENT-SOURCE")
    insert_rows(database, [source])
    message = "P4B-PRIVATE-FAILURE-QUESTION"
    with route_database(database), synthetic_mcp(error=code) as calls, \
         patch.object(OOMPClient, "retrieve") as legacy, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        expected_standalone = build_context_prompt(SESSION, OWNER, message)
        if expected == "unauthorized":
            with pytest.raises(HTTPException) as denied:
                chat(ChatRequest(message=message, session_id=SESSION, user_id=OWNER), http_request())
            assert denied.value.status_code == 403
        else:
            response = chat(ChatRequest(message=message, session_id=SESSION, user_id=OWNER), http_request())
    legacy.assert_not_called()
    assert len(calls) == 1
    if expected == "unauthorized":
        model.assert_not_called()
        assert database["chat_history"].count_documents({}) == 1
        return
    prompt = model.call_args.args[0]
    diagnostics = saved_interaction(database, response)["oomp_diagnostics"]
    assert diagnostics["error_code"] == code and not diagnostics["retrieval_success"]
    assert prompt == expected_standalone and "HISTORICAL_CONTEXT" not in prompt
    assert diagnostics["context_status"] == expected and diagnostics["prompt_mode"] == "standalone"
    assert diagnostics["evidence_count"] == 0
    assert source["user_message"] in prompt
    assert message not in caplog.text and source["user_message"] not in caplog.text
    assert_prompt_capacity(prompt, diagnostics, config)


@pytest.mark.parametrize("corruption", ["packet", "event", "foreign", "excluded", "timestamp"])
def test_corrupt_or_foreign_historical_proofs_never_enter_model_prompt(
        database, monkeypatch, tmp_path, corruption):
    activate_context(monkeypatch, tmp_path)
    source = fixed_row(2, session=HISTORICAL_SESSION, text="REJECTED-HISTORICAL-SOURCE-CONTENT")
    if corruption == "foreign":
        source["user_id"] = OTHER
    if corruption == "excluded":
        source["oomp_publication"] = {"excluded": True}
    insert_rows(database, [fixed_row(1), source])
    unit = context_unit(source)
    if corruption == "event":
        unit["source_proofs"][0]["event_id"] = "forged-event-identity"
    if corruption == "timestamp":
        unit["source_proofs"][0]["source_reference"]["timestamp"] = (
            source["request_start_time"] + timedelta(days=1)).isoformat()
    mutate = (lambda value: value.update(selected_context_bytes=value["selected_context_bytes"] + 1)) \
        if corruption == "packet" else None
    before = deepcopy(database["chat_history"].find_one({"_id": source["_id"]}))
    with route_database(database), synthetic_mcp(units=[unit], status="found_relevant_evidence", mutate=mutate), \
         patch.object(OOMPClient, "retrieve") as legacy, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        response = chat(ChatRequest(message="A fictional historical lookup.", session_id=SESSION, user_id=OWNER), http_request())
    legacy.assert_not_called()
    prompt = model.call_args.args[0]
    data = prompt_data(prompt)
    diagnostics = saved_interaction(database, response)["oomp_diagnostics"]
    assert diagnostics["context_status"] == "invalid_evidence"
    assert diagnostics["error_code"] == ("invalid_evidence" if corruption == "packet" else "scope_rejected")
    assert data["HISTORICAL_CONTEXT"]["authoritative_source_units"] == []
    assert source["user_message"] not in prompt and FORGED_PARAPHRASE not in prompt
    assert database["chat_history"].find_one({"_id": source["_id"]}) == before


@pytest.mark.parametrize("raw_quote", [False, True])
def test_valid_span_cannot_promote_forged_completed_move_or_drop_negation(
        database, monkeypatch, tmp_path, raw_quote):
    activate_context(monkeypatch, tmp_path)
    source = fixed_row(2, session=HISTORICAL_SESSION, text=SOURCE_TEXT)
    insert_rows(database, [fixed_row(1), source])
    start = SOURCE_TEXT.index("moved")
    unit = context_unit(source, span=(start, start + len("moved")),
                        quote="moved" if raw_quote else None)
    with route_database(database), synthetic_mcp(units=[unit], status="found_relevant_evidence") as calls, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        response = chat(ChatRequest(message="Has the fictional move happened?", session_id=SESSION, user_id=OWNER), http_request())
    assert "include_source_content" not in calls[0][1]
    prompt = model.call_args.args[0]
    data = prompt_data(prompt)
    assert FORGED_PARAPHRASE not in prompt
    history = data["HISTORICAL_CONTEXT"]
    if raw_quote:
        assert history["status"] == "invalid_evidence"
        assert history["authoritative_source_units"] == []
        assert saved_interaction(database, response)["oomp_diagnostics"]["error_code"] == "invalid_evidence"
    else:
        assert history["status"] == "found_relevant_evidence"
        selected = history["authoritative_source_units"]
        assert len(selected) == 1 and selected[0]["derived"] and selected[0]["uncertain"]
        assert selected[0]["assertion_kinds"] == ["tentative"]
        original = selected[0]["authoritative_sources"][0]
        assert original["role"] == "user" and original["source_content"] == SOURCE_TEXT
        assert "not moved" in original["source_content"]
        assert original["source_interaction_id"] == str(source["_id"])
        assert original["validated_source_span"] == {"start": start, "end": start + 5}


@pytest.mark.parametrize("role", ["user", "assistant", "feedback"])
def test_historical_sources_keep_actual_role_and_original_serialization(
        database, monkeypatch, tmp_path, role):
    activate_context(monkeypatch, tmp_path)
    source = fixed_row(2, session=HISTORICAL_SESSION, text=SOURCE_TEXT,
                       assistant="The fictional assistant guessed that a move had happened.")
    insert_rows(database, [fixed_row(1), source])
    expected, _ = original_content(source, role)
    with route_database(database), synthetic_mcp(units=[context_unit(source, role=role)],
                                               status="found_relevant_evidence"), \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        chat(ChatRequest(message="What did the original source say?", session_id=SESSION, user_id=OWNER), http_request())
    data = prompt_data(model.call_args.args[0])
    sources = data["HISTORICAL_CONTEXT"]["authoritative_source_units"][0]["authoritative_sources"]
    assert len(sources) == 1 and sources[0]["role"] == role
    assert sources[0]["source_content"] == expected
    assert FORGED_PARAPHRASE not in model.call_args.args[0]


@pytest.mark.parametrize("mode", ["retrieve", "retrieve_and_ingest"])
def test_context_reads_do_not_mutate_sources_or_deliver_publications(
        database, monkeypatch, tmp_path, mode):
    config = activate_context(monkeypatch, tmp_path, mode=mode)
    source = fixed_row(2, session=HISTORICAL_SESSION, text=SOURCE_TEXT)
    current = fixed_row(1)
    insert_rows(database, [current, source])
    before = list(database["chat_history"].find({}).sort("_id", 1))
    collections = set(database.list_collection_names())
    with route_database(database), synthetic_mcp(units=[context_unit(source)],
                                               status="found_relevant_evidence") as calls, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER):
        response = chat(ChatRequest(message="A fictional source-backed question.", session_id=SESSION, user_id=OWNER), http_request())
    assert [name for name, _, _ in calls] == ["memory.context"]
    assert database["chat_history"].count_documents({}) == len(before) + 1
    assert set(database.list_collection_names()) == collections
    for original in before:
        assert database["chat_history"].find_one({"_id": original["_id"]}) == original
    saved = saved_interaction(database, response)
    assert saved["feedback"]["submitted"] is False
    assert database["sessions"].find_one({"session_id": SESSION})["message_count"] == 1
    assert database["sessions"].find_one({"session_id": HISTORICAL_SESSION})["message_count"] == 0
    if mode == "retrieve":
        assert "oomp_publication" not in saved
    else:
        marker = saved["oomp_publication"]
        assert marker["approved"] is True and marker["ready"] is True and marker["excluded"] is False
        assert marker["policy_id"] == config.policy_id
        assert set(marker["events"]) == {"user", "assistant"}
        assert all(state["status"] == "pending" and state["attempts"] == 0
                   for state in marker["events"].values())
        assert config.policy_id == config.model_copy(update={"retrieval_api": "retrieve"}).policy_id


@pytest.mark.parametrize("corruption", [
    "retracted", "superseded_current", "no_relevant_with_sources", "budget_with_sources",
    "unavailable_with_sources", "found_without_sources",
])
def test_context_temporal_and_outcome_inconsistencies_fall_back_before_prompt(
        database, monkeypatch, tmp_path, corruption):
    activate_context(monkeypatch, tmp_path)
    source = fixed_row(2, session=HISTORICAL_SESSION, text="WITHHELD-STALE-HISTORICAL-SOURCE")
    insert_rows(database, [fixed_row(1), source])
    unit = context_unit(source)
    units, status = [unit], "found_relevant_evidence"
    if corruption == "retracted":
        unit["temporal_status"] = "retracted"
    elif corruption == "superseded_current":
        unit["temporal_status"] = "superseded"
    elif corruption == "no_relevant_with_sources":
        status = "no_relevant_evidence"
    elif corruption == "budget_with_sources":
        status = "budget_excluded"
    elif corruption == "unavailable_with_sources":
        status = "unavailable"
    else:
        units = []
    with route_database(database), synthetic_mcp(units=units, status=status), \
         patch.object(OOMPClient, "retrieve") as legacy, \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        response = chat(ChatRequest(message="A fictional current-state lookup.", session_id=SESSION,
                                    user_id=OWNER), http_request())
    legacy.assert_not_called()
    prompt = model.call_args.args[0]
    historical = prompt_data(prompt)["HISTORICAL_CONTEXT"]
    assert historical["status"] == "invalid_evidence"
    assert historical["authoritative_source_units"] == []
    assert source["user_message"] not in prompt
    assert saved_interaction(database, response)["oomp_diagnostics"]["error_code"] == "invalid_evidence"


def test_historical_superseded_source_remains_explicitly_historical_and_uncertain(
        database, monkeypatch, tmp_path):
    activate_context(monkeypatch, tmp_path)
    source = fixed_row(2, session=HISTORICAL_SESSION,
                       text="The fictional old relocation proposal was tentative.")
    insert_rows(database, [fixed_row(1), source])
    unit = context_unit(source)
    unit["temporal_status"] = "superseded"
    def historical_response(value):
        value["retrieval_intent"] = "historical_correction"
    with route_database(database), synthetic_mcp(units=[unit], status="candidate_uncertain",
                                               mutate=historical_response), \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        chat(ChatRequest(message="What was the fictional plan before correction?", session_id=SESSION,
                         user_id=OWNER), http_request())
    selected, = prompt_data(model.call_args.args[0])["HISTORICAL_CONTEXT"]["authoritative_source_units"]
    assert selected["temporal_status"] == "superseded" and selected["uncertain"] is True
    assert selected["authoritative_sources"][0]["source_content"] == source["user_message"]

def test_default_naive_utc_mongo_sources_normalize_without_database_mutation(monkeypatch, tmp_path):
    import mongomock
    from stage8_support import seed

    # PyMongo's default UTC decoding is naive, unlike the shared tz-aware fixture.
    database = mongomock.MongoClient(tz_aware=False)["p4b-fictional-naive-utc"]
    seed(database)
    config = activate_context(monkeypatch, tmp_path)
    current = fixed_row(1, text="A complete fictional recent source with naive stored UTC.")
    historical = fixed_row(2, session=HISTORICAL_SESSION, text=SOURCE_TEXT)
    insert_rows(database, [current, historical])
    before = list(database["chat_history"].find({}).sort("_id", 1))
    assert before[0]["request_start_time"].tzinfo is None
    assert before[1]["response_end_time"].tzinfo is None
    with route_database(database), synthetic_mcp(units=[context_unit(historical)],
                                               status="candidate_uncertain", coverage="partial"), \
         patch("backend.routes.chat.generate_response", return_value=FAKE_ANSWER) as model:
        response = chat(ChatRequest(message="What did the fictional source actually say?", session_id=SESSION,
                                    user_id=OWNER), http_request())
    prompt = model.call_args.args[0]
    data = prompt_data(prompt)
    recent, = data["RECENT_SESSION_CONTEXT"]["complete_exchanges"]
    assert recent["source_timestamp"] == current["request_start_time"].isoformat()
    assert recent["user_message"] == current["user_message"]
    selected, = data["HISTORICAL_CONTEXT"]["authoritative_source_units"]
    assert selected["authoritative_sources"][0]["source_content"] == SOURCE_TEXT
    assert selected["authoritative_sources"][0]["source_reference"]["timestamp"].endswith("Z")
    assert_prompt_capacity(prompt, saved_interaction(database, response)["oomp_diagnostics"], config)
    for original in before:
        assert database["chat_history"].find_one({"_id": original["_id"]}) == original
    assert database["chat_history"].count_documents({}) == len(before) + 1
