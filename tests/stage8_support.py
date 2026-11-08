"""Synthetic Stage 8 fixtures. OOMP is used ONLY as a separate CLI/MCP process."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from unittest.mock import patch

from bson import ObjectId
import mongomock
from starlette.requests import Request

from backend.services.oomp_config import OOMPConfiguration, WriterGrant
from backend.services.oomp_publisher import Publisher, backfill

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_PYTHON = Path(os.environ.get("TRACE_TEST_OOMP_PYTHON", "D:/Desktop/OOMP/.venv/Scripts/python.exe"))
OWNER = str(ObjectId("000000000000000000000001"))
OTHER = str(ObjectId("000000000000000000000002"))
SESSION = "stage8-owned-session"
HOST_KEY = "H" * 43
READ_TOKEN = "R" * 43
USER_TOKEN = "U" * 43
ASSISTANT_TOKEN = "A" * 43
FOREIGN_TOKEN = "F" * 43
USER_APPROVAL = "K" * 43
ASSISTANT_APPROVAL = "L" * 43
FOREIGN_APPROVAL = "G" * 43
SECRETS = {
    "TRACE_TEST_READ": READ_TOKEN, "TRACE_TEST_USER": USER_TOKEN, "TRACE_TEST_ASSISTANT": ASSISTANT_TOKEN,
    "TRACE_TEST_FOREIGN": FOREIGN_TOKEN, "TRACE_TEST_USER_APPROVAL": USER_APPROVAL,
    "TRACE_TEST_ASSISTANT_APPROVAL": ASSISTANT_APPROVAL, "TRACE_TEST_FOREIGN_APPROVAL": FOREIGN_APPROVAL,
}


def binding(role="user", *, foreign=False):
    source_type = "assistant" if role == "assistant" else "user"
    prefix = "FOREIGN" if foreign else ("ASSISTANT" if role == "assistant" else "USER")
    return WriterGrant(grant_id="trace-" + ("foreign" if foreign else role),
        principal_id="other-host" if foreign else "trace-host",
        tenant_id="trace-other" if foreign else "trace-local", namespace="personal",
        source_type=source_type, source_system="trace-ai",
        event_types=("assistant_message",) if source_type == "assistant" else ("user_message", "feedback"),
        bearer_token_env="TRACE_TEST_" + prefix, approval_key_env="TRACE_TEST_" + prefix + "_APPROVAL")


def configuration(server, *, mode="retrieve_and_ingest", **changes):
    values = dict(mode=mode, url=server.url, owner_id=OWNER, read_token=READ_TOKEN,
                  owner_key=HOST_KEY, writers={"user": binding(), "assistant": binding("assistant"), "feedback": binding()})
    if mode == "retrieve":
        values["writers"] = {}
    values.update(changes)
    return OOMPConfiguration(**values)


def chat_row(number=0, *, owner=OWNER, session=SESSION, text=None, feedback=True):
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=number)
    return {
        "_id": ObjectId(), "session_id": session, "user_id": owner,
        "user_message": text or f"Unrelated synthetic turn {number}.", "llama_response": "Synthetic response.",
        "timestamp": stamp, "request_start_time": stamp, "response_end_time": stamp+timedelta(seconds=1),
        "response_time": 1., "response_time_seconds": 1., "topic_label": "General",
        "feedback": {"submitted": feedback, "rating": 4, "correctness": "Correct",
                     "length_type": "To the Point", "submitted_at": stamp+timedelta(seconds=2) if feedback else None},
    }


def seed(database, *, history=0, owner=OWNER, session=SESSION):
    database["sessions"].insert_one({
        "session_id": session, "user_id": owner, "status": "active", "message_count": history,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc), "topics": ["General"],
    })
    database["users"].insert_one({"_id": ObjectId(owner), "email": owner+"@example.test", "name": "Synthetic"})
    rows = [chat_row(n, owner=owner, session=session,
                     text="I am developing a project called OOMP." if n == 0 else None) for n in range(history)]
    if rows:
        database["chat_history"].insert_many(rows)
    return rows


class ExternalOOMP:
    def __init__(self, folder):
        self.folder = folder.resolve()
        self.database = self.folder/"external-memory.sqlite3"
        self.config_path = self.folder/"external-server.local.json"
        with socket.socket() as connection:
            connection.bind(("127.0.0.1", 0))
            self.port = connection.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        reader = dict(grant_id="trace-reader",principal_id="trace-host",tenant_id="trace-local",
                      namespace="personal",capabilities=["read"],bearer_token_env="TRACE_TEST_READ")
        grants = [reader]
        for grant in (binding(), binding("assistant"), binding(foreign=True)):
            grants.append(dict(grant_id=grant.grant_id,principal_id=grant.principal_id,
                tenant_id=grant.tenant_id,namespace=grant.namespace,capabilities=["read","ingest"],
                bearer_token_env=grant.bearer_token_env,ingest_approval_key_env=grant.approval_key_env,
                ingest_source_type=grant.source_type,ingest_source_system=grant.source_system,
                ingest_event_types=list(grant.event_types)))
        self.config_path.write_text(json.dumps({
            "database": str(self.database), "transport":"streamable-http","profile":"trusted-ingest",
            "host":"127.0.0.1","port":self.port,"http_grants":grants,
        }),encoding="utf-8")
        self.environment = {**os.environ, **SECRETS, "PYTHONDONTWRITEBYTECODE":"1"}
        self.command("storage","init","--db",str(self.database))
        self.process = None
        self.start()

    def command(self, *args):
        result = subprocess.run([str(EXTERNAL_PYTHON),"-B","-m","oomp",*args],cwd=ROOT,
            env={**os.environ, **SECRETS, "PYTHONDONTWRITEBYTECODE":"1"},
            capture_output=True,text=True,timeout=45)
        if result.returncode:
            raise RuntimeError("External OOMP CLI failed: " + result.stderr)
        return result.stdout

    def start(self):
        self.process = subprocess.Popen([str(EXTERNAL_PYTHON),"-B","-m","oomp","mcp","serve",
            "--config",str(self.config_path)],cwd=ROOT,env=self.environment,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        deadline = time.monotonic()+45
        while time.monotonic()<deadline:
            if self.process.poll() is not None:
                raise RuntimeError("External OOMP exited")
            try:
                with socket.create_connection(("127.0.0.1",self.port),timeout=.1):
                    return
            except OSError:
                time.sleep(.03)
        self.stop()
        raise RuntimeError("External OOMP startup timeout")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(10)

    def worker(self, *, foreign=False):
        output = self.command("mind","run-once","--db",str(self.database),
            "--tenant","trace-other" if foreign else "trace-local","--namespace","personal","--max-jobs","16")
        return json.loads(output)


@contextmanager
def route_database(database):
    targets = (
        "backend.database.database.db", "backend.routes.chat.get_database",
        "backend.routes.feedback.get_database", "backend.services.session_service.get_database",
        "backend.services.chat_storage.get_database", "backend.services.chat_orchestrator.get_database",
        "backend.services.oomp_publisher.get_database", "backend.analytics.finalization.get_database",
    )
    from contextlib import ExitStack
    with ExitStack() as stack:
        for target in targets:
            stack.enter_context(patch(target, database if target.endswith(".db") else lambda: database))
        yield


def http_request(*, headers=None, owner=OWNER):
    values = [(b"host",b"127.0.0.1:8000"), (b"x-trace-memory-key",HOST_KEY.encode())]
    if headers is not None:
        values = headers
    scope = {"type":"http","method":"POST","scheme":"http","path":"/chat","headers":values,
             "client":("127.0.0.1",12345),"server":("127.0.0.1",8000),"query_string":b"",
             "state":{"oomp_owner":owner}}
    return Request(scope)


def app_instance():
    # Synthetic routes must never discover a workstation's private handoff.
    with patch("backend.services.oomp_local.load_local_connection", return_value={"configured":False}), patch("backend.database.database.connect_db"):
        return importlib.import_module("backend.app").app

def activate(monkeypatch, server, folder, *, mode="retrieve_and_ingest", **changes):
    config=configuration(server,mode=mode,**changes)
    values={
        "TRACE_OOMP_MODE":mode,"TRACE_OOMP_URL":config.url,"TRACE_OOMP_OWNER_ID":config.owner_id,
        "TRACE_OOMP_OWNER_KEY":config.owner_key.get_secret_value(),
        "TRACE_OOMP_READ_TOKEN":config.read_token.get_secret_value(),
        "TRACE_OOMP_TENANT_ID":config.tenant_id,"TRACE_OOMP_NAMESPACE":config.namespace,
        "TRACE_OOMP_PRINCIPAL_ID":config.principal_id,
    }
    if mode=="retrieve_and_ingest":
        file=folder/"writers.local.json"
        file.write_text(json.dumps({role:g.model_dump(mode="json") for role,g in config.writers.items()}),encoding="utf-8")
        values["TRACE_OOMP_WRITER_CONFIG"]=str(file)
    for key,value in values.items():
        monkeypatch.setenv(key,value)
    return config