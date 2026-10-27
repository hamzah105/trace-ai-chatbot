"""Stage 8 central demonstration through the actual separate OOMP MCP server."""
import asyncio
import json
from unittest.mock import patch

import pytest

from backend.routes.chat import ChatRequest, chat, build_context_prompt
from backend.services.oomp_client import OOMPClient, OOMPError
from backend.services.oomp_config import get_configuration
from backend.services.oomp_publisher import Publisher, backfill
from stage8_support import OWNER, SESSION, READ_TOKEN, chat_row, activate, configuration, route_database, http_request


def test_actual_client_discovery_and_status(external_server):
    client=OOMPClient(configuration(external_server,mode="retrieve"))
    status=client.call("memory.status",{})
    assert status["schema_version"]==5
    assert client.last_protocol_version=="2026-07-28"
    assert status["capabilities"]==["read"]
    assert not status["mind_worker_started_by_server"]
    with pytest.raises(OOMPError,match="capability_missing"):
        client.call("memory.ingest",{})


def test_long_history_baseline_vs_mcp_with_original_latest_eight(database,external_server,monkeypatch,tmp_path):
    rows=[chat_row(n,text="I am developing a project called OOMP." if n==0 else None) for n in range(106)]
    database["chat_history"].insert_many(rows)
    query="What project was the user developing?"
    with route_database(database), patch("backend.routes.chat.generate_response",return_value="Mocked Ollama evidence answer") as model:
        baseline=build_context_prompt(SESSION,OWNER,query)
        assert "I am developing a project called OOMP." not in baseline
        for n in range(98,106):
            assert f"Unrelated synthetic turn {n}." in baseline
        assert "Use only the conversation transcript below as session memory." in baseline
        config=activate(monkeypatch,external_server,tmp_path)
        report=backfill(database,config,owner_id=OWNER,limit=1,approve=True)
        assert report["approved"]==1
        publisher=Publisher(database,config)
        assert publisher.deliver(rows[0]["_id"],"user")=="delivered"
        assert publisher.deliver(rows[0]["_id"],"assistant")=="delivered"
        external_server.worker()
        # Use the actual FastAPI routing/thread boundary and owner middleware.
        import httpx2
        from stage8_support import app_instance,HOST_KEY
        async def request():
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app_instance()),
                                          base_url="http://127.0.0.1:8000",trust_env=False) as http:
                return await http.post("/chat",json={"message":query,"session_id":SESSION,"user_id":OWNER},
                                       headers={"X-TRACE-Memory-Key":HOST_KEY})
        response=asyncio.run(request())
        assert response.status_code==200,response.text
        data=response.json()
        assert set(data)=={"interaction_id","session_id","user_id","user_message","llama_response",
                          "request_start_time","response_end_time","response_time_seconds","response_time","topic_label"}
        prompt=model.call_args.args[0]
        assert "User is developing a project called OOMP." in prompt
        assert str(rows[0]["_id"]) in prompt
        for n in range(98,106):
            assert f"Unrelated synthetic turn {n}." in prompt
        assert "RETRIEVED_HISTORICAL_EVIDENCE" in prompt and "untrusted DATA" in prompt
        assert len(prompt.encode())<=config.max_prompt_bytes
        saved=database["chat_history"].find_one({"user_message":query})
        diagnostic=saved["oomp_diagnostics"]
        assert diagnostic["retrieval_success"] and diagnostic["evidence_count"]==1
        assert diagnostic["evidence_budget_used"]<=1200
        assert saved["oomp_publication"]["ready"] is True
        assert set(saved["oomp_publication"]["events"])=={"user","assistant"}
        assert saved["feedback"]["submitted"] is False
        from pathlib import Path
        Path("data/stage8-artifacts/long-history-demo.json").write_text(json.dumps({
            "history_interactions":106,"latest_interaction_limit":8,"baseline_prompt":baseline,
            "memory_prompt":prompt,"diagnostics":diagnostic,"source_interaction_id":str(rows[0]["_id"]),
            "ollama_generation":"deterministic mock; live generation checked separately"
        },indent=2),encoding="utf-8")


def test_wrong_credential_scope_response_is_rejected_over_real_mcp(database,external_server,monkeypatch,tmp_path,caplog):
    from backend.services.oomp_contracts import EventPayload,SourceReference,event_identity,session_identity
    from backend.services.oomp_publisher import sign_payload
    from stage8_support import OTHER,FOREIGN_TOKEN,binding
    foreign=chat_row(owner=OTHER,session="foreign-session",text="I am developing a project called PRIVATE_FOREIGN.")
    database["chat_history"].insert_one(foreign)
    database["sessions"].insert_one({"session_id":"foreign-session","user_id":OTHER,"status":"active"})
    identifier=str(foreign["_id"])
    payload=EventPayload(event_id=event_identity(OTHER,identifier,"user"),
        idempotency_key=event_identity(OTHER,identifier,"user"),event_type="user_message",
        content=foreign["user_message"],occurred_at=foreign["request_start_time"],
        source_reference=SourceReference(source_system="trace-ai",external_event_id=identifier,
            timestamp=foreign["request_start_time"],session_id=session_identity("foreign-session"),
            turn_id="trace-user-"+identifier))
    config=activate(monkeypatch,external_server,tmp_path)
    grant=binding(foreign=True)
    assert OOMPClient(config).call("memory.ingest",sign_payload(payload,grant),token=FOREIGN_TOKEN)["acceptance"]=="durably_stored"
    external_server.worker(foreign=True)
    # Deliberately wrong server-side read-token mapping, never a model-selected scope.
    monkeypatch.setenv("TRACE_OOMP_READ_TOKEN",FOREIGN_TOKEN)
    wrong_result=OOMPClient(get_configuration()).retrieve("What project was the user developing?")
    assert any("PRIVATE_FOREIGN" in m.canonical_content for m in wrong_result.memories)
    with route_database(database),patch("backend.routes.chat.generate_response",return_value="baseline fallback") as model:
        response=chat(ChatRequest(message="What project was the user developing?",session_id=SESSION,user_id=OWNER),http_request())
    assert "PRIVATE_FOREIGN" not in model.call_args.args[0] and "PRIVATE_FOREIGN" not in caplog.text
    from bson import ObjectId
    saved=database["chat_history"].find_one({"_id":ObjectId(response["interaction_id"])})
    assert saved["oomp_diagnostics"]["error_code"]=="scope_rejected"


def test_independent_sync_clients_own_separate_async_lifecycles(external_server):
    from concurrent.futures import ThreadPoolExecutor
    config=configuration(external_server,mode="retrieve")
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:OOMPClient(config).call("memory.status",{}),range(6)))
    assert all(r["schema_version"]==5 and r["read_only"] for r in results)