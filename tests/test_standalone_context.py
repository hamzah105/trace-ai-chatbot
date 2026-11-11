"""Actual chat orchestration with synthetic Mongo and explicitly fake inference.

These assert the exact model input; real-model greeting quality is separate.
"""
from unittest.mock import patch

import pytest

from backend.routes.chat import ChatRequest, build_context_prompt, chat
from backend.services.oomp_client import OOMPClient, OOMPError
from p4b_support import SERVER, activate_context, fixed_row, insert_rows, saved_interaction
from stage8_support import OWNER, OTHER, SESSION, activate, http_request, route_database


@pytest.mark.parametrize("mode", ["off", "context_v1", "legacy"])
@pytest.mark.parametrize("message", [
    "Hello", "Explain recursion briefly.", "What nickname did I mention in this session?",
    "What is my pet's name from a different session?",
])
def test_standalone_uses_normal_current_message_and_owned_eight_turns(
        database, monkeypatch, tmp_path, mode, message):
    if mode == "context_v1":
        activate_context(monkeypatch, tmp_path)
    elif mode == "legacy":
        activate(monkeypatch, SERVER, tmp_path, mode="retrieve")
    else:
        monkeypatch.setenv("TRACE_OOMP_MODE", "off")
    rows = [fixed_row(n, text=f"LOCAL-{n}: my nickname is fictional Willow.") for n in range(10)]
    foreign = fixed_row(20, owner=OTHER, text="FORBIDDEN-FOREIGN-OWNER")
    other_session = fixed_row(21, session="other-session", text="FORBIDDEN-OTHER-SESSION-PET")
    excluded = fixed_row(22, text="FORBIDDEN-EXCLUDED-SOURCE")
    excluded["oomp_publication"] = {"excluded": True}
    insert_rows(database, [*rows, foreign, other_session, excluded])
    with route_database(database), \
         patch.object(OOMPClient, "context", side_effect=OOMPError("unavailable")) as context, \
         patch.object(OOMPClient, "retrieve", side_effect=OOMPError("unavailable")) as legacy, \
         patch("backend.routes.chat.generate_response", return_value="Explicitly mocked answer") as model:
        expected = build_context_prompt(SESSION, OWNER, message)
        response = chat(ChatRequest(message=message, session_id=SESSION, user_id=OWNER), http_request())
    prompt = model.call_args.args[0]
    assert prompt == expected and message in prompt
    assert "HISTORICAL_CONTEXT" not in prompt and "retrieval_coverage" not in prompt
    assert "historical context is unavailable" not in prompt.lower()
    assert "Answer greetings and general questions normally" in prompt
    assert "Only when asked for personal or conversation history" in prompt
    assert "LOCAL-0:" not in prompt and "LOCAL-1:" not in prompt
    assert all(f"LOCAL-{n}:" in prompt for n in range(2, 10))
    assert "rating" in prompt and "Feedback for Turn" in prompt
    assert not any(marker in prompt for marker in (
        "FORBIDDEN-FOREIGN-OWNER", "FORBIDDEN-OTHER-SESSION-PET", "FORBIDDEN-EXCLUDED-SOURCE"))
    context.assert_called_once() if mode == "context_v1" else context.assert_not_called()
    legacy.assert_called_once() if mode == "legacy" else legacy.assert_not_called()
    stored = saved_interaction(database, response)
    assert stored["feedback"]["submitted"] is False
    if mode == "context_v1":
        assert stored["oomp_diagnostics"]["prompt_mode"] == "standalone"
        assert stored["oomp_diagnostics"]["error_code"] == "unavailable"
