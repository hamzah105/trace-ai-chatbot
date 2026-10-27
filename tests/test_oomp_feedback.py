"""Existing feedback, sessions and analytics with optional memory enabled."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import patch
import httpx2
import pytest
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import AutoReconnect

from backend.routes.chat import ChatRequest,chat
from backend.routes.feedback import FeedbackRequest,submit_feedback
from backend.services.ollama_service import OllamaServiceError
from backend.services.oomp_client import OOMPError
from backend.services.oomp_publisher import Publisher,backfill
from backend.services.session_service import end_session
from backend.analytics.data_service import get_session_analytics_data
from backend.analytics.metrics import compute_session_metrics
from stage8_support import OWNER,OTHER,SESSION,HOST_KEY,activate,chat_row,route_database,http_request,app_instance


@pytest.mark.parametrize("guard",["pending","ended","wrong_owner"])
def test_guards_run_before_any_mcp_or_model_call(database,monkeypatch,tmp_path,guard):
    activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path)
    if guard=="pending":
        database["chat_history"].insert_one(chat_row(feedback=False))
    elif guard=="ended":
        database["sessions"].update_one({"session_id":SESSION},{"$set":{"status":"ended"}})
    else:
        database["sessions"].update_one({"session_id":SESSION},{"$set":{"user_id":OTHER}})
    with route_database(database),patch("backend.services.chat_orchestrator.OOMPClient") as client, \
         patch("backend.routes.chat.generate_response") as model:
        with pytest.raises(HTTPException) as failure:
            chat(ChatRequest(message="hello",session_id=SESSION,user_id=OWNER),http_request())
        assert failure.value.status_code==(403 if guard=="wrong_owner" else 409)
        client.assert_not_called()
        model.assert_not_called()
    assert database["chat_history"].count_documents({"oomp_publication":{"$exists":True}})==0


def test_feedback_submit_once_finalize_and_analytics_survive_oomp_outage(database,monkeypatch,tmp_path):
    config=activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path)
    with route_database(database),patch("backend.services.chat_orchestrator.OOMPClient.retrieve",
                                       side_effect=OOMPError("unavailable")), \
         patch("backend.routes.chat.generate_response",return_value="Synthetic answer"):
        response=chat(ChatRequest(message="Explain Python.",session_id=SESSION,user_id=OWNER),http_request())
        feedback=FeedbackRequest(interaction_id=response["interaction_id"],user_id=OWNER,session_id=SESSION,
                                 rating=3,correctness="Partial",length_type="To the Point")
        assert submit_feedback(feedback)["success"]
        with pytest.raises(HTTPException) as duplicate:
            submit_feedback(feedback)
        assert duplicate.value.status_code==409
        saved=database["chat_history"].find_one({"_id":ObjectId(response["interaction_id"])})
        assert saved["oomp_publication"]["events"]["feedback"]["status"]=="pending"
        before=compute_session_metrics(get_session_analytics_data(SESSION,OWNER)["interactions"])
        ended=end_session(SESSION,OWNER)
        assert ended["status"]=="ended" and ended["final_analytics"]["metrics"]==before
        assert end_session(SESSION,OWNER)["final_analytics"]==ended["final_analytics"]
        with pytest.raises(HTTPException):
            submit_feedback(feedback)
        with pytest.raises(HTTPException):
            chat(ChatRequest(message="ended",session_id=SESSION,user_id=OWNER),http_request())


def test_feedback_foreign_record_rejected_even_without_optional_body_owner(database,monkeypatch,tmp_path):
    activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path)
    foreign=chat_row(owner=OTHER,feedback=False)
    database["chat_history"].insert_one(foreign)
    with route_database(database):
        with pytest.raises(HTTPException) as failure:
            submit_feedback(FeedbackRequest(interaction_id=str(foreign["_id"]),rating=4,
                                            correctness="Correct",length_type="Short"))
    assert failure.value.status_code==403
    assert database["chat_history"].find_one({"_id":foreign["_id"]})["feedback"]["submitted"] is False


@pytest.mark.parametrize("failure_point",["model","save","record"])
def test_failed_interactions_are_not_eligible_for_reconciliation(database,monkeypatch,tmp_path,failure_point):
    config=activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path)
    from contextlib import ExitStack
    with route_database(database),patch("backend.services.chat_orchestrator.OOMPClient.retrieve",
                                       side_effect=OOMPError("unavailable")),ExitStack() as stack:
        if failure_point=="model":
            stack.enter_context(patch("backend.routes.chat.generate_response",side_effect=OllamaServiceError("Unavailable")))
        else:
            stack.enter_context(patch("backend.routes.chat.generate_response",return_value="Synthetic answer"))
            target="save_chat" if failure_point=="save" else "record_interaction"
            stack.enter_context(patch("backend.routes.chat."+target,side_effect=RuntimeError("Database unavailable")))
        with pytest.raises(HTTPException):
            chat(ChatRequest(message="Synthetic question",session_id=SESSION,user_id=OWNER),http_request())
    publisher=Publisher(database,config)
    assert publisher.reconcile(dry_run=False)["scheduled"]==0
    assert all(not row.get("oomp_publication",{}).get("ready") for row in database["chat_history"].find({}))


def test_feedback_scheduling_failure_cannot_undo_valid_feedback(database,monkeypatch,tmp_path):
    config=activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path)
    row=chat_row(feedback=False)
    database["chat_history"].insert_one(row)
    backfill(database,config,owner_id=OWNER,approve=True)
    with route_database(database),patch("backend.services.oomp_publisher.ensure_entries",side_effect=AutoReconnect("private-db")):
        result=submit_feedback(FeedbackRequest(interaction_id=str(row["_id"]),rating=4,
                                               correctness="Correct",length_type="Short"))
    assert result["success"]
    assert database["chat_history"].find_one({"_id":row["_id"]})["feedback"]["submitted"] is True
    assert Publisher(database,config).reconcile(dry_run=False)["scheduled"]==1


def test_oomp_metadata_never_changes_phase3_metric_values(database,monkeypatch,tmp_path):
    activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path,mode="retrieve")
    rows=[chat_row(n) for n in range(9)]
    database["chat_history"].insert_many(rows)
    with route_database(database):
        before=get_session_analytics_data(SESSION,OWNER)
        for row in rows:
            database["chat_history"].update_one({"_id":row["_id"]},{"$set":{
                "oomp_diagnostics":{"evidence_count":5,"retrieval_latency_ms":123},
                "oomp_publication":{"ready":True,"excluded":False,"events":{"user":{"status":"retry"}}}}})
        after=get_session_analytics_data(SESSION,OWNER)
        assert before==after
        assert compute_session_metrics(before["interactions"])==compute_session_metrics(after["interactions"])


def test_owner_cross_session_recall_requires_stored_owner_link(database,external_server,monkeypatch,tmp_path):
    config=activate(monkeypatch,external_server,tmp_path)
    row=chat_row(text="I am developing a project called OOMP.")
    database["chat_history"].insert_one(row)
    backfill(database,config,owner_id=OWNER,approve=True)
    assert Publisher(database,config).deliver(row["_id"],"user")=="delivered"
    external_server.worker()
    second="second-owned-session"
    database["sessions"].insert_one({"session_id":second,"user_id":OWNER,"status":"active",
                                    "message_count":0,"topics":[]})
    with route_database(database),patch("backend.routes.chat.generate_response",return_value="Synthetic") as model:
        chat(ChatRequest(message="What project was the user developing?",session_id=second,user_id=OWNER),http_request())
    prompt=model.call_args.args[0]
    assert "User is developing a project called OOMP." in prompt
    assert "other sessions owned by this user" in prompt
    assert "No previous turns in this session." in prompt