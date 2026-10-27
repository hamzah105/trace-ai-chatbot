"""Stage 8 configuration, verified owner/cookie and safe fallback boundaries."""
import asyncio
import importlib.abc
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import httpx2
import pytest
from bson import ObjectId
from pydantic import ValidationError

from backend.services.oomp_config import get_configuration, OOMPConfiguration, ConfigurationError
from backend.services.oomp_client import OOMPError
from backend.services.oomp_security import attach_owner_login, COOKIE
from stage8_support import (OWNER, OTHER, HOST_KEY, READ_TOKEN, SESSION, activate,
    configuration, route_database, app_instance, http_request)


@pytest.mark.parametrize("changes", [
    {"url":"http://example.com:8765/mcp"}, {"url":"http://127.0.0.1:8765/mcp?token=private"},
    {"url":"http://user@127.0.0.1:8765/mcp"}, {"url":"https://127.0.0.1:8765/mcp"},
    {"url":"http://127.0.0.1:8765/wrong"}, {"owner_id":"anonymous"}, {"owner_id":""},
    {"owner_key":"short"}, {"owner_key":READ_TOKEN}, {"max_results":21}, {"evidence_budget":32769},
    {"timeout_seconds":float("nan")}, {"timeout_seconds":30}, {"max_prompt_bytes":8192},
])
def test_unsafe_or_ambiguous_memory_configuration_fails(changes):
    with pytest.raises((ValidationError,ConfigurationError)):
        configuration(SimpleNamespace(url="http://127.0.0.1:8765/mcp"),mode="retrieve",**changes)


def test_off_mode_ignores_optional_configuration_and_never_imports_sdk(monkeypatch):
    monkeypatch.setenv("TRACE_OOMP_URL","http://unsafe.example:1234/mcp")
    assert get_configuration().mode=="off"
    script="""
import importlib.abc,sys,os
os.environ['TRACE_OOMP_MODE']='off'
class NoSDK(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='mcp' or fullname.startswith('mcp.') or fullname=='httpx2' or fullname.startswith('oomp'):
            raise ImportError('SDK and OOMP imports deliberately blocked')
sys.meta_path.insert(0,NoSDK())
from unittest.mock import patch
from backend.routes.chat import ChatRequest,chat
from bson import ObjectId
with patch('backend.routes.chat.ensure_active_session'), patch('backend.routes.chat.get_pending_feedback',return_value=None), patch('backend.routes.chat.build_context_prompt',return_value='original prompt') as prompt, patch('backend.routes.chat.generate_response',return_value='answer') as model, patch('backend.routes.chat.save_chat',return_value=ObjectId()),patch('backend.routes.chat.record_interaction'):
    result=chat(ChatRequest(message='hello',session_id='s',user_id='u',oomp_mode='retrieve_and_ingest'))
    assert result['llama_response']=='answer'
    model.assert_called_once_with('original prompt')
"""
    result=subprocess.run([sys.executable,"-c",script],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize("headers,owner", [
    ({},OWNER), ({"X-TRACE-Memory-Key":"wrong"},OWNER),
    ({"X-TRACE-Memory-Key":HOST_KEY},OTHER),
    ({"X-TRACE-Memory-Key":HOST_KEY,"Origin":"http://evil.example"},OWNER),
    ({"X-TRACE-Memory-Key":HOST_KEY,"Host":"evil.example"},OWNER),
])
def test_unverified_or_other_owner_never_reaches_memory(database,monkeypatch,tmp_path,headers,owner):
    activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path,mode="retrieve")
    async def scenario():
        with route_database(database),patch("backend.services.chat_orchestrator.OOMPClient") as mcp:
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app_instance()),
                                          base_url="http://127.0.0.1:8000") as client:
                response=await client.post("/chat",headers=headers,json={
                    "message":"private question","session_id":SESSION,"user_id":owner})
                assert response.status_code==403
                mcp.assert_not_called()
    asyncio.run(scenario())


def test_pinned_owner_credential_covers_stored_history_and_analytics(database,monkeypatch,tmp_path):
    activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path,mode="retrieve")
    async def scenario():
        with route_database(database):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app_instance()),
                                          base_url="http://127.0.0.1:8000") as client:
                for path in (f"/sessions/{SESSION}?user_id={OWNER}",
                             f"/sessions/{SESSION}/messages?user_id={OWNER}",
                             f"/analytics/session/{SESSION}/dashboard?user_id={OWNER}"):
                    assert (await client.get(path)).status_code==403
                    assert (await client.get(path,headers={"X-TRACE-Memory-Key":HOST_KEY})).status_code==200
                response=await client.get(f"/sessions/user/{OTHER}",headers={"X-TRACE-Memory-Key":HOST_KEY})
                assert response.status_code==403
                assert (await client.get("/health")).json()=={"status":"ok"}
    asyncio.run(scenario())


def test_successful_password_login_mints_cookie_and_logout_clears_it(database,monkeypatch,tmp_path):
    from backend.routes.auth import hash_password
    database["users"].update_one({"_id":ObjectId(OWNER)},{"$set":{"password":hash_password("synthetic-password")}})
    activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path,mode="retrieve")
    async def scenario():
        with route_database(database),patch("backend.routes.auth.get_database",return_value=database):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app_instance()),
                                          base_url="http://127.0.0.1:8000") as client:
                bad=await client.post("/login",json={"email":OWNER+"@example.test","password":"wrong"})
                assert bad.json()["success"] is False and COOKIE not in client.cookies
                good=await client.post("/login",json={"email":OWNER+"@example.test","password":"synthetic-password"})
                assert good.json()["success"] is True and COOKIE in client.cookies
                assert "HttpOnly" in good.headers["set-cookie"] and "SameSite=strict" in good.headers["set-cookie"]
                assert (await client.get(f"/sessions/{SESSION}?user_id={OWNER}")).status_code==200
                assert (await client.post("/auth/oomp/logout")).json()=={"success":True}
                assert COOKIE not in client.cookies
                assert (await client.get(f"/sessions/{SESSION}?user_id={OWNER}")).status_code==403
    asyncio.run(scenario())


def test_other_login_drops_owner_cookie_and_tampering_does_not_authenticate(monkeypatch,tmp_path):
    activate(monkeypatch,SimpleNamespace(url="http://127.0.0.1:9/mcp"),tmp_path,mode="retrieve")
    owner=attach_owner_login({"success":True},OWNER,request=http_request())
    switched=attach_owner_login({"success":True},OTHER)
    assert "Max-Age=0" in switched.headers["set-cookie"]
    from backend.services.oomp_security import _authorized
    signed=owner.headers["set-cookie"].split(";",1)[0].split("=",1)[1]
    scope=http_request(headers=[(b"host",b"127.0.0.1:8000"),
                                (b"cookie",(COOKIE+"="+signed+"tampered").encode())]).scope
    assert not _authorized(scope,get_configuration())


def test_invalid_configuration_keeps_health_and_fails_private_routes(monkeypatch):
    monkeypatch.setenv("TRACE_OOMP_MODE","retrieve")
    async def scenario():
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app_instance()),
                                      base_url="http://127.0.0.1:8000") as client:
            assert (await client.get("/health")).json()=={"status":"ok"}
            response=await client.post("/chat",json={"message":"hello","user_id":OWNER})
            assert response.status_code==503
            assert "secret" not in response.text.lower()
    asyncio.run(scenario())


def test_production_modules_do_not_import_oomp_source():
    import ast
    for path in Path("backend").rglob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                assert all(n.name!="oomp" and not n.name.startswith("oomp.") for n in node.names),path
            if isinstance(node,ast.ImportFrom):
                assert node.module!="oomp" and not (node.module or "").startswith("oomp."),path