"""Mongo-authoritative, embedded publication outbox; MCP is the only delivery path."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import secrets

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from backend.database.database import get_database
from .oomp_config import get_configuration
from .oomp_security import verified_owner
from .oomp_contracts import EventPayload, SourceReference, event_identity, session_identity
from .oomp_client import OOMPClient, OOMPError

LOGGER = logging.getLogger("trace.oomp")
ROLES = ("user", "assistant", "feedback")


def now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, datetime):
        raise OOMPError("invalid_source")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def stage_publication(chat_data, request):
    config = get_configuration()
    if config.mode != "retrieve_and_ingest":
        return
    if not verified_owner(request, chat_data["user_id"], config):
        raise OOMPError("owner_rejected")
    chat_data["oomp_publication"] = {
        "version": 1, "policy_id": config.policy_id, "approved": True,
        "approved_at": chat_data["request_start_time"], "ready": False, "excluded": False,
        "events": {},
    }


def _eligible(row, config):
    marker = row.get("oomp_publication") or {}
    return (config.mode == "retrieve_and_ingest" and row.get("user_id") == config.owner_id
            and marker.get("approved") is True and marker.get("ready") is True
            and marker.get("excluded") is False and marker.get("policy_id") == config.policy_id)


def _new_state():
    return {"status": "pending", "attempts": 0, "available_at": now(), "lease_until": None,
            "lease_token": None, "last_error": None}


def _feedback(row):
    value = row.get("feedback")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise OOMPError("invalid_source")
    return value


def ensure_entries(database, config, interaction_id):
    row = database["chat_history"].find_one({"_id": ObjectId(interaction_id), "user_id": config.owner_id})
    if not row or not _eligible(row, config):
        return 0
    # Persisted content and ownership must be coherent even during reconciliation.
    session = database["sessions"].find_one({"session_id": row.get("session_id"), "user_id": config.owner_id})
    if not session or not row.get("llama_response") or not row.get("user_message"):
        raise OOMPError("invalid_source")
    roles = ["user", "assistant"]
    if _feedback(row).get("submitted") is True:
        roles.append("feedback")
    added = 0
    for role in roles:
        field = "oomp_publication.events." + role
        result = database["chat_history"].update_one(
            {"_id": row["_id"], "user_id": config.owner_id, "oomp_publication.excluded": False,
             "oomp_publication.ready": True, "oomp_publication.policy_id": config.policy_id,
             field: {"$exists": False}},
            {"$set": {field: _new_state()}},
        )
        added += result.modified_count
    return added


def complete_publication(identifier, chat_data):
    if "oomp_publication" not in chat_data:
        return
    config = get_configuration()
    database = get_database()
    if database is None:
        raise RuntimeError("Interaction completion could not be stored")
    result = database["chat_history"].update_one(
        {"_id": identifier, "user_id": config.owner_id, "oomp_publication.excluded": False,
         "oomp_publication.policy_id": config.policy_id},
        {"$set": {"oomp_publication.ready": True}},
    )
    if result.matched_count != 1:
        raise RuntimeError("Interaction completion could not be stored")
    try:
        ensure_entries(database, config, identifier)
    except Exception:
        # The durable ready/approved marker is enough for explicit reconciliation.
        LOGGER.warning("oomp_outbox_schedule_failed code=mongo_unavailable")


def schedule_feedback(identifier):
    try:
        config = get_configuration()
        if config.mode == "retrieve_and_ingest":
            ensure_entries(get_database(), config, identifier)
    except Exception:
        LOGGER.warning("oomp_feedback_schedule_failed code=mongo_unavailable")


def make_payload(row, role, config):
    if not _eligible(row, config):
        raise OOMPError("excluded")
    identifier = str(row["_id"])
    if not ObjectId.is_valid(identifier) or role not in ROLES:
        raise OOMPError("invalid_source")
    if role == "user":
        content, occurred, kind = row["user_message"], row["request_start_time"], "user_message"
    elif role == "assistant":
        content, occurred, kind = row["llama_response"], row["response_end_time"], "assistant_message"
    else:
        feedback = _feedback(row)
        if (feedback.get("submitted") is not True or (not isinstance(feedback.get("rating"), int) or isinstance(feedback.get("rating"), bool))
                or not 1 <= feedback["rating"] <= 4
                or feedback.get("correctness") not in {"Correct", "Partial", "Incorrect"}
                or feedback.get("length_type") not in {"Short", "To the Point", "Lengthy"}):
            raise OOMPError("invalid_source")
        content = json.dumps({key: feedback[key] for key in ("rating", "correctness", "length_type")},
                             sort_keys=True, separators=(",", ":"))
        occurred, kind = feedback["submitted_at"], "feedback"
    occurred = timestamp(occurred)
    event_id = event_identity(config.owner_id, identifier, role)
    return EventPayload(
        event_id=event_id, idempotency_key=event_id, event_type=kind, content=content,
        occurred_at=occurred, source_reference=SourceReference(
            source_system=config.source_system, external_event_id=identifier, timestamp=occurred,
            session_id=session_identity(row["session_id"]), turn_id="trace-" + role + "-" + identifier,
            locator=None,
        ),
    )


def sign_payload(payload, grant, issued=None):
    """Implement only the documented host approval wire format, not OOMP core."""
    issued = issued or now()
    proof = {"issued_at": issued, "expires_at": issued + timedelta(seconds=60),
             "nonce": "approval-" + secrets.token_hex(16)}
    # Match the server's Pydantic UTC JSON serialization, including explicit nulls.
    proof_json = {key: value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value
                  for key, value in proof.items()}
    message = {
        "domain": "oomp.mcp.ingest.approval.v1", "grant": grant.signature_identity(),
        "payload": payload.model_dump(mode="json"), "approval": proof_json,
    }
    encoded = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False).encode("utf-8")
    signature = hmac.new(grant.credential(approval=True).encode("ascii"), encoded, hashlib.sha256).hexdigest()
    return {**payload.model_dump(mode="json"), "approval": {**proof_json, "signature": signature}}


class Publisher:
    def __init__(self, database, config, *, clock=now, client=None):
        self.database, self.config, self.clock = database, config, clock
        self.client = client or OOMPClient(config)

    def reconcile(self, *, limit=100, after_id=None, dry_run=True):
        if self.config.mode != "retrieve_and_ingest" or type(limit) is not int or not 1 <= limit <= 100:
            raise OOMPError("policy_required")
        query = {"user_id": self.config.owner_id, "oomp_publication.ready": True,
                 "oomp_publication.approved": True, "oomp_publication.excluded": False,
                 "oomp_publication.policy_id": self.config.policy_id}
        if after_id:
            query["_id"] = {"$gt": ObjectId(after_id)}
        rows = list(self.database["chat_history"].find(query).sort("_id", 1).limit(limit+1))
        result = {"scanned": 0, "events_missing": 0, "scheduled": 0, "invalid": 0,
                  "next_after_id": str(rows[limit-1]["_id"]) if len(rows) > limit else None}
        for row in rows[:limit]:
            result["scanned"] += 1
            try:
                roles = ("user", "assistant", "feedback") if _feedback(row).get("submitted") is True else ("user", "assistant")
                for role in roles:
                    make_payload(row, role, self.config)
                    result["events_missing"] += role not in row["oomp_publication"].get("events", {})
                if not dry_run:
                    result["scheduled"] += ensure_entries(self.database, self.config, row["_id"])
            except (OOMPError, ValueError, KeyError, TypeError):
                result["invalid"] += 1
        return result

    def _base(self, identifier):
        return {"_id": identifier, "user_id": self.config.owner_id,
                "oomp_publication.ready": True, "oomp_publication.approved": True,
                "oomp_publication.excluded": False, "oomp_publication.policy_id": self.config.policy_id}

    def deliver(self, identifier, role):
        if self.config.mode != "retrieve_and_ingest" or role not in ROLES:
            raise OOMPError("policy_required")
        path = "oomp_publication.events." + role
        at = self.clock()
        query = self._base(ObjectId(identifier))
        query.update({path + ".attempts": {"$lt": 5}, "$or": [
            {path + ".status": {"$in": ["pending", "retry"]}, path + ".available_at": {"$lte": at}},
            {path + ".status": "delivering", path + ".lease_until": {"$lte": at}},
        ]})
        token = secrets.token_hex(16)
        row = self.database["chat_history"].find_one_and_update(
            query, {"$set": {path+".status": "delivering", path+".lease_token": token,
                             path+".lease_until": at+timedelta(seconds=30)},
                    "$inc": {path+".attempts": 1}}, return_document=ReturnDocument.AFTER,
        )
        if row is None:
            return "not_claimed"
        fence = self._base(row["_id"]) | {path+".lease_token": token, path+".status": "delivering"}
        try:
            current = self.database["chat_history"].find_one(fence)
            if not current:
                return "excluded"
            session = self.database["sessions"].find_one({"session_id": current["session_id"],
                                                         "user_id": self.config.owner_id})
            if not session:
                raise OOMPError("invalid_source")
            payload = make_payload(current, role, self.config)
            grant = self.config.writers[role]
            result = self.client.call("memory.ingest", sign_payload(payload, grant), token=grant.credential())
            if (result.get("acceptance") != "durably_stored" or result.get("event_id") != payload.event_id
                    or result.get("worker_started_by_request") is not False):
                raise OOMPError("invalid_receipt")
            outcome = {"status": "delivered", "delivered_at": self.clock(), "last_error": None}
        except OOMPError as error:
            permanent = error.code in {"conflict", "forbidden", "unauthorized", "authorization_failed",
                                       "invalid_parameters", "invalid_source", "excluded", "capability_missing"}
            attempts = row["oomp_publication"]["events"][role]["attempts"]
            outcome = {"status": "failed" if permanent or attempts >= 5 else "retry",
                       "last_error": error.code,
                       "available_at": self.clock()+timedelta(seconds=min(300, 2**attempts))}
            LOGGER.warning("oomp_publication_failed code=%s", error.code)
        except Exception:
            # Leave the fenced lease for recovery, including acceptance/acknowledgement uncertainty.
            LOGGER.warning("oomp_publication_interrupted code=delivery_uncertain")
            return "uncertain"
        outcome.update(lease_token=None, lease_until=None)
        try:
            updated = self.database["chat_history"].update_one(fence, {"$set": {
                path+"."+key: value for key, value in outcome.items()}})
        except Exception:
            LOGGER.warning("oomp_publication_interrupted code=acknowledgement_uncertain")
            return "uncertain"
        return outcome["status"] if updated.matched_count else "lease_lost"

    def drain(self, *, limit=20):
        if self.config.mode != "retrieve_and_ingest" or type(limit) is not int or not 1 <= limit <= 100:
            raise OOMPError("policy_required")
        at = self.clock()
        due = []
        for role in ROLES:
            path = "oomp_publication.events." + role
            exhausted = self._base(None)
            del exhausted["_id"]
            exhausted.update({path+".status": "delivering", path+".lease_until": {"$lte": at},
                              path+".attempts": {"$gte": 5}})
            for expired in self.database["chat_history"].find(exhausted).sort("_id", 1).limit(limit):
                self.database["chat_history"].update_one({**exhausted, "_id": expired["_id"]}, {"$set": {
                    path+".status": "failed", path+".last_error": "delivery_uncertain",
                    path+".lease_token": None, path+".lease_until": None}})
            path = "oomp_publication.events." + role
            due += [
                {path+".status": {"$in": ["pending", "retry"]}, path+".available_at": {"$lte": at}, path+".attempts": {"$lt": 5}},
                {path+".status": "delivering", path+".lease_until": {"$lte": at}, path+".attempts": {"$lt": 5}},
            ]
        query = self._base(None)
        del query["_id"]
        query["$or"] = due
        rows = list(self.database["chat_history"].find(query).sort("_id", 1).limit(limit))
        results = []
        for row in rows:
            for role in ROLES:
                if len(results) >= limit:
                    break
                state = self.deliver(row["_id"], role)
                if state != "not_claimed":
                    results.append(state)
        return {"attempted": len(results), "results": results}

def backfill(database, config, *, owner_id, limit=100, after_id=None, approve=False):
    """Explicit legacy consent, never startup reconciliation or failed-row revival."""
    if config.mode != "retrieve_and_ingest" or owner_id != config.owner_id:
        raise OOMPError("owner_rejected")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise OOMPError("resource_limit")
    query = {"user_id": owner_id, "oomp_publication": {"$exists": False}}
    if after_id:
        query["_id"] = {"$gt": ObjectId(after_id)}
    rows = list(database["chat_history"].find(query).sort("_id", 1).limit(limit+1))
    report = {"scanned": 0, "eligible": 0, "approved": 0, "invalid": 0,
              "next_after_id": str(rows[limit-1]["_id"]) if len(rows) > limit else None}
    for row in rows[:limit]:
        report["scanned"] += 1
        marker = {"version": 1, "policy_id": config.policy_id, "approved": True,
                  "approved_at": now(), "ready": True, "excluded": False, "events": {}}
        candidate = {**row, "oomp_publication": marker}
        try:
            session = database["sessions"].find_one({"session_id": row["session_id"], "user_id": owner_id})
            if not session:
                raise OOMPError("invalid_source")
            make_payload(candidate, "user", config)
            make_payload(candidate, "assistant", config)
        except (OOMPError, ValueError, KeyError, TypeError):
            report["invalid"] += 1
            continue
        report["eligible"] += 1
        if approve:
            changed = database["chat_history"].update_one(
                {"_id": row["_id"], "user_id": owner_id, "oomp_publication": {"$exists": False}},
                {"$set": {"oomp_publication": marker}})
            report["approved"] += changed.modified_count
            ensure_entries(database, config, row["_id"])
    return report


def exclude(database, config, identifier):
    """Persist a local no-publication marker. Never deletes remote memory."""
    query = {"_id": ObjectId(identifier), "user_id": config.owner_id}
    row = database["chat_history"].find_one(query)
    if not row:
        raise OOMPError("not_found")
    changes = {"oomp_publication.excluded": True, "oomp_publication.ready": False}
    for role in (row.get("oomp_publication") or {}).get("events", {}):
        changes["oomp_publication.events."+role+".status"] = "excluded"
    database["chat_history"].update_one(query, {"$set": changes})
    return {"excluded": True}
