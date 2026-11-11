"""Durable Mongo-authoritative publication, retry, roles and exclusion."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import copy
import json
import sqlite3
from types import SimpleNamespace
import uuid

import pytest
from pymongo import MongoClient

from backend.services.oomp_client import OOMPError
from backend.services.oomp_publisher import Publisher,backfill,exclude,make_payload,sign_payload
from stage8_support import OWNER,OTHER,SESSION,chat_row,configuration,binding,SECRETS,USER_TOKEN


class AcceptingClient:
    def __init__(self):
        self.accepted=[]
    def call(self,name,arguments,token=None):
        self.accepted.append(arguments)
        return {"event_id":arguments["event_id"],"acceptance":"durably_stored",
                "worker_started_by_request":False,"outbox_state":"pending","latest_extraction_job_status":None}


@pytest.mark.parametrize("feedback", ["malformed legacy value", [], 1, False])
def test_reconciliation_isolates_invalid_feedback_without_discarding_source(database, staged, feedback):
    identifier, config = staged
    database["chat_history"].update_one({"_id":identifier},{"$set":{"feedback":feedback}})
    before = database["chat_history"].find_one({"_id":identifier})
    result = Publisher(database, config).reconcile(dry_run=False)
    assert result["scanned"] == 1 and result["invalid"] == 1 and result["scheduled"] == 0
    assert database["chat_history"].find_one({"_id":identifier}) == before


@pytest.mark.parametrize("feedback", ["malformed legacy value", [], 1, False])
def test_invalid_feedback_claim_fails_once_without_reviving_or_blocking_valid_roles(database, staged, feedback):
    identifier, config = staged
    row = database["chat_history"].find_one({"_id":identifier})
    pending = copy.deepcopy(row["oomp_publication"]["events"]["user"])
    database["chat_history"].update_one({"_id":identifier},{"$set":{
        "feedback":feedback,"oomp_publication.events.feedback":pending}})
    client = AcceptingClient()
    publisher = Publisher(database, config, client=client)
    assert publisher.deliver(identifier,"feedback") == "failed"
    assert publisher.deliver(identifier,"feedback") == "not_claimed"
    state = database["chat_history"].find_one({"_id":identifier})["oomp_publication"]["events"]["feedback"]
    assert state["last_error"] == "invalid_source" and state["attempts"] == 1
    assert client.accepted == []
    assert publisher.deliver(identifier,"user") == "delivered"
    assert len(client.accepted) == 1
    assert database["chat_history"].find_one({"_id":identifier})["feedback"] == feedback


@pytest.fixture
def staged(database):
    row=chat_row(feedback=False)
    database["chat_history"].insert_one(row)
    config=configuration(SimpleNamespace(url="http://127.0.0.1:9/mcp"))
    assert backfill(database,config,owner_id=OWNER,approve=True)["approved"]==1
    return row["_id"],config


def test_outbox_references_actual_record_without_duplicate_bodies(database,staged):
    identifier,config=staged
    row=database["chat_history"].find_one({"_id":identifier})
    marker=row["oomp_publication"]
    assert set(marker["events"])=={"user","assistant"}
    assert "user_message" not in json.dumps(marker,default=str)
    user=make_payload(row,"user",config)
    assistant=make_payload(row,"assistant",config)
    assert user.source_reference.external_event_id==str(identifier)
    assert user.event_id!=assistant.event_id and user.idempotency_key==user.event_id
    assert user.event_type=="user_message" and assistant.event_type=="assistant_message"
    assert len(user.event_id)<=128 and ":" not in user.event_id
    assert sign_payload(user,config.writers["user"])["approval"]["signature"]


def test_outage_pending_retry_then_equal_delivery(database,staged):
    identifier,config=staged
    at=datetime.now(timezone.utc)
    class Offline:
        def call(self,*args,**kwargs):
            raise OOMPError("unavailable")
    failed=Publisher(database,config,clock=lambda:at,client=Offline())
    assert failed.deliver(identifier,"user")=="retry"
    assert failed.deliver(identifier,"user")=="not_claimed"
    accepted=AcceptingClient()
    replay=Publisher(database,config,clock=lambda:at+timedelta(seconds=5),client=accepted)
    assert replay.deliver(identifier,"user")=="delivered"
    assert replay.deliver(identifier,"user")=="not_claimed"
    assert len(accepted.accepted)==1
    assert database["chat_history"].find_one({"_id":identifier})["user_message"]


@pytest.mark.parametrize("code",["conflict","forbidden","authorization_failed","invalid_parameters"])
def test_permanent_failure_never_retries_under_another_grant(database,staged,code):
    identifier,config=staged
    class Rejecting:
        def call(self,*args,**kwargs):
            raise OOMPError(code)
    publisher=Publisher(database,config,client=Rejecting())
    assert publisher.deliver(identifier,"user")=="failed"
    assert publisher.deliver(identifier,"user")=="not_claimed"
    assert database["chat_history"].find_one({"_id":identifier})["oomp_publication"]["events"]["user"]["last_error"]==code


def test_crash_after_acceptance_before_ack_reuses_exact_identity(database,staged):
    identifier,config=staged
    at=datetime.now(timezone.utc)
    accepted=AcceptingClient()
    class Crashed:
        def call(self,*args,**kwargs):
            accepted.call(*args,**kwargs)
            raise RuntimeError("crashed before acknowledgement")
    assert Publisher(database,config,clock=lambda:at,client=Crashed()).deliver(identifier,"user")=="uncertain"
    assert Publisher(database,config,clock=lambda:at+timedelta(seconds=31),client=accepted).deliver(identifier,"user")=="delivered"
    first,second=accepted.accepted
    assert {k:v for k,v in first.items() if k!="approval"}=={k:v for k,v in second.items() if k!="approval"}


def test_reconciliation_repairs_only_successful_consented_rows(database,staged):
    identifier,config=staged
    database["chat_history"].update_one({"_id":identifier},{"$unset":{"oomp_publication.events.user":""}})
    legacy=chat_row(1)
    database["chat_history"].insert_one(legacy)
    failed=chat_row(2)
    failed["oomp_publication"]={"approved":True,"ready":False,"excluded":False,"policy_id":config.policy_id,"events":{}}
    database["chat_history"].insert_one(failed)
    publisher=Publisher(database,config)
    assert publisher.reconcile(dry_run=True)["events_missing"]==1
    assert "user" not in database["chat_history"].find_one({"_id":identifier})["oomp_publication"]["events"]
    assert publisher.reconcile(dry_run=False)["scheduled"]==1
    assert publisher.reconcile(dry_run=False)["scheduled"]==0
    assert "oomp_publication" not in database["chat_history"].find_one({"_id":legacy["_id"]})
    assert database["chat_history"].find_one({"_id":failed["_id"]})["oomp_publication"]["ready"] is False


def test_excluded_record_never_resurrects_in_backfill_or_reconciliation(database,staged):
    identifier,config=staged
    assert exclude(database,config,identifier)=={"excluded":True}
    client=AcceptingClient()
    publisher=Publisher(database,config,client=client)
    assert publisher.deliver(identifier,"user")=="not_claimed"
    assert publisher.reconcile(dry_run=False)["scheduled"]==0
    assert backfill(database,config,owner_id=OWNER,approve=True)["approved"]==0
    assert client.accepted==[]


def test_legacy_backfill_dry_run_pagination_skips_invalid_and_other_owner(database):
    config=configuration(SimpleNamespace(url="http://127.0.0.1:9/mcp"))
    rows=[chat_row(n) for n in range(4)]
    rows[2].pop("response_end_time")
    database["chat_history"].insert_many(rows+[chat_row(9,owner=OTHER)])
    before=copy.deepcopy(list(database["chat_history"].find({})))
    dry=backfill(database,config,owner_id=OWNER,limit=2)
    assert dry["scanned"]==2 and dry["eligible"]==2 and dry["approved"]==0 and dry["next_after_id"]
    assert list(database["chat_history"].find({}))==before
    next_batch=backfill(database,config,owner_id=OWNER,limit=2,after_id=dry["next_after_id"],approve=True)
    assert next_batch["invalid"]==1 and next_batch["approved"]==1
    with pytest.raises(OOMPError,match="owner_rejected"):
        backfill(database,config,owner_id=OTHER,approve=True)


def test_feedback_is_never_pending_before_submission(database,staged):
    identifier,config=staged
    publisher=Publisher(database,config)
    assert publisher.deliver(identifier,"feedback")=="not_claimed"
    row=database["chat_history"].find_one({"_id":identifier})
    with pytest.raises(OOMPError,match="invalid_source"):
        make_payload(row,"feedback",config)


def test_concurrent_delivery_claims_are_fenced(database,staged):
    identifier,config=staged
    accepting=AcceptingClient()
    publisher=Publisher(database,config,client=accepting)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes=list(pool.map(lambda _:publisher.deliver(identifier,"user"),range(16)))
    assert outcomes.count("delivered")==1 and len(accepting.accepted)==1


def test_retry_attempts_are_bounded_including_last_uncertain_lease(database,staged):
    identifier,config=staged
    at=datetime.now(timezone.utc)
    database["chat_history"].update_one({"_id":identifier},{"$set":{
        "oomp_publication.events.user.status":"delivering","oomp_publication.events.user.attempts":5,
        "oomp_publication.events.user.lease_until":at-timedelta(seconds=1),
        "oomp_publication.events.assistant.status":"delivered"}})
    result=Publisher(database,config,client=AcceptingClient()).drain()
    state=database["chat_history"].find_one({"_id":identifier})["oomp_publication"]["events"]["user"]
    assert state["status"]=="failed" and state["last_error"]=="delivery_uncertain"
    assert result["attempted"]==0


def test_real_mcp_roles_idempotency_feedback_and_approval_tampering(database,external_server):
    config=configuration(external_server)
    row=chat_row(text="I prefer Python.")
    database["chat_history"].insert_one(row)
    backfill(database,config,owner_id=OWNER,approve=True)
    publisher=Publisher(database,config)
    assert publisher.drain(limit=3)["results"]==["delivered"]*3
    from backend.services.oomp_client import OOMPClient
    client=OOMPClient(config)
    persisted=database["chat_history"].find_one({"_id":row["_id"]})
    arguments=sign_payload(make_payload(persisted,"user",config),config.writers["user"])
    assert client.call("memory.ingest",arguments,token=USER_TOKEN)["acceptance"]=="durably_stored"
    arguments["content"]="tampered source"
    with pytest.raises(OOMPError,match="forbidden"):
        client.call("memory.ingest",arguments,token=USER_TOKEN)
    with sqlite3.connect(f"file:{external_server.database.as_posix()}?mode=ro",uri=True) as connection:
        records=connection.execute("SELECT event_type,source_type FROM events").fetchall()
        assert sorted(records)==[("assistant_message","assistant"),("feedback","user"),("user_message","user")]
    external_server.worker()
    result=client.retrieve("Python")
    assert result.memories
    assert all("Synthetic response" not in m.canonical_content for m in result.memories)


def test_real_mongo_outbox_survives_client_reopen_and_replay():
    client=MongoClient("mongodb://127.0.0.1:27017/",serverSelectionTimeoutMS=800)
    try:
        client.admin.command("ping")
    except Exception:
        client.close()
        pytest.skip("Local MongoDB not available for the separate physical persistence check")
    name="trace_stage8_test_"+uuid.uuid4().hex
    try:
        from stage8_support import seed
        database=client[name]
        seed(database,history=1)
        config=configuration(SimpleNamespace(url="http://127.0.0.1:9/mcp"))
        assert backfill(database,config,owner_id=OWNER,approve=True)["approved"]==1
        identifier=database["chat_history"].find_one({})["_id"]
        client.close()
        client=MongoClient("mongodb://127.0.0.1:27017/",serverSelectionTimeoutMS=800)
        publisher=Publisher(client[name],config,client=AcceptingClient())
        assert publisher.deliver(identifier,"user")=="delivered"
        assert publisher.deliver(identifier,"user")=="not_claimed"
        assert client[name]["chat_history"].find_one({"_id":identifier})["oomp_publication"]["events"]["user"]["status"]=="delivered"
    finally:
        assert name.startswith("trace_stage8_test_") and len(name)==50
        client.drop_database(name)
        client.close()

def test_mongo_acknowledgement_failure_leaves_lease_for_safe_replay(database,staged,monkeypatch):
    from unittest.mock import patch
    identifier,config=staged
    at=datetime.now(timezone.utc)
    accepted=AcceptingClient()
    collection=database["chat_history"]
    with patch.object(collection,"update_one",side_effect=RuntimeError("private write failure")):
        assert Publisher(database,config,clock=lambda:at,client=accepted).deliver(identifier,"user")=="uncertain"
    assert collection.find_one({"_id":identifier})["oomp_publication"]["events"]["user"]["status"]=="delivering"
    assert Publisher(database,config,clock=lambda:at+timedelta(seconds=31),client=accepted).deliver(identifier,"user")=="delivered"
    assert accepted.accepted[0]["event_id"]==accepted.accepted[1]["event_id"]

def test_explicit_worker_recovers_consented_gaps_without_importing_legacy(database,staged):
    from backend.services.oomp_diagnostics import work
    identifier,config=staged
    database["chat_history"].update_one({"_id":identifier},{"$unset":{"oomp_publication.events.user":""}})
    database["chat_history"].insert_one(chat_row(9))
    accepting=AcceptingClient()
    reports=list(work(Publisher(database,config,client=accepting),cycles=1))
    assert reports[0]["reconciliation"]["scheduled"]==1
    assert reports[0]["delivery"]["attempted"]==2
    assert len(accepting.accepted)==2
    assert database["chat_history"].count_documents({"oomp_publication":{"$exists":False}})==1


def test_off_diagnostics_performs_no_mcp_or_mongo_calls(monkeypatch,capsys):
    from backend.services.oomp_diagnostics import main
    from unittest.mock import patch
    with patch("backend.services.oomp_diagnostics.OOMPClient") as client:
        assert main([])==0
        client.assert_not_called()
    assert json.loads(capsys.readouterr().out)["mode"]=="off"

def test_actual_service_outage_restart_and_durable_replay(database,external_server):
    config=configuration(external_server)
    row=chat_row(feedback=False,text="I prefer Python.")
    database["chat_history"].insert_one(row)
    backfill(database,config,owner_id=OWNER,approve=True)
    at=datetime.now(timezone.utc)
    external_server.stop()
    publisher=Publisher(database,config,clock=lambda:at)
    assert publisher.deliver(row["_id"],"user")=="retry"
    assert database["chat_history"].find_one({"_id":row["_id"]})["oomp_publication"]["events"]["user"]["status"]=="retry"
    external_server.start()
    resumed=Publisher(database,config,clock=lambda:at+timedelta(seconds=5))
    assert resumed.deliver(row["_id"],"user")=="delivered"
    assert resumed.deliver(row["_id"],"user")=="not_claimed"
    with sqlite3.connect(f"file:{external_server.database.as_posix()}?mode=ro",uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]==1
