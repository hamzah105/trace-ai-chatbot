"""Bind context proofs to TRACE-owned original Mongo sources, without writes.

Passing this check authenticates source attribution and exact spans. It does not
prove that an OOMP paraphrase, object snapshot or episode summary follows from
those sources. Consumers must preserve source roles and uncertainty and render
original source_content, rather than treating evidence.content as verified fact.
The complete source is available because a valid substring can omit negation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json

from bson import ObjectId

from .oomp_client import OOMPError
from .oomp_context_contracts import ContextEvidence, ContextResult, ContextSourceReference
from .oomp_contracts import event_identity, session_identity


@dataclass(frozen=True)
class ValidatedContextSource:
    role: str
    interaction_id: str
    event_id: str
    memory_id: str
    source_reference: ContextSourceReference
    span_start: int
    span_end: int
    excerpt: str = field(repr=False)
    source_content: str = field(repr=False)


@dataclass(frozen=True)
class ValidatedContextUnit:
    evidence: ContextEvidence = field(repr=False)
    sources: tuple[ValidatedContextSource, ...]


def _timestamp(value):
    # Mongo commonly returns naive UTC; use the publication serialization rule.
    if not isinstance(value, datetime):
        raise OOMPError("scope_rejected")
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def _role_source(row, role):
    """Pure counterpart of the publisher's existing role serialization.

    Do not call publisher.make_payload: its writer-mode/consent guard would
    incorrectly reject a legitimate read-only retrieval deployment.
    """
    if role == "user":
        content, occurred = row.get("user_message"), row.get("request_start_time")
    elif role == "assistant":
        content, occurred = row.get("llama_response"), row.get("response_end_time")
    elif role == "feedback":
        feedback = row.get("feedback") or {}
        if (not isinstance(feedback, dict) or feedback.get("submitted") is not True
                or type(feedback.get("rating")) is not int or not 1 <= feedback["rating"] <= 4
                or feedback.get("correctness") not in {"Correct", "Partial", "Incorrect"}
                or feedback.get("length_type") not in {"Short", "To the Point", "Lengthy"}):
            raise OOMPError("scope_rejected")
        content = json.dumps({key: feedback[key] for key in ("rating", "correctness", "length_type")},
                             sort_keys=True, separators=(",", ":"))
        occurred = feedback.get("submitted_at")
    else:
        raise OOMPError("scope_rejected")
    if not isinstance(content, str) or not content or len(content) > 16384:
        raise OOMPError("scope_rejected")
    # Validate encoding now; lone surrogates cannot enter a prompt or byte count.
    try:
        content.encode("utf-8")
    except UnicodeEncodeError:
        raise OOMPError("scope_rejected") from None
    return content, _timestamp(occurred)


def validate_context_provenance(result: ContextResult, config, database):
    """Return original sources for every complete unit, or reject the result.

    The bearer mapping is the remote authority. These independent checks bind
    its returned proofs to current owner/session-linked TRACE records. Neither
    an object ID, a memory ID, a ranking score nor a returned scope label grants
    authority. No locator is fetched and no database operation writes data.
    """
    if database is None:
        raise OOMPError("source_validation_unavailable")
    rows = {}
    sources = {}

    def validate(proof):
        reference = proof.source_reference
        identifier = reference.external_event_id
        if (reference.source_system != config.source_system
                or not ObjectId.is_valid(identifier) or reference.locator is not None):
            raise OOMPError("scope_rejected")
        if identifier != str(ObjectId(identifier)):
            raise OOMPError("scope_rejected")
        if identifier not in rows:
            try:
                row = database["chat_history"].find_one(
                    {"_id": ObjectId(identifier), "user_id": config.owner_id})
                if (not row or str(row.get("_id")) != identifier
                        or row.get("user_id") != config.owner_id):
                    raise OOMPError("scope_rejected")
                session_id = row.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    raise OOMPError("scope_rejected")
                session = database["sessions"].find_one(
                    {"session_id": session_id, "user_id": config.owner_id})
                if not session:
                    raise OOMPError("scope_rejected")
            except OOMPError:
                raise
            except Exception:
                raise OOMPError("source_validation_unavailable") from None
            marker = row.get("oomp_publication")
            if marker is None:
                marker = {}
            if (not isinstance(marker, dict) or marker.get("excluded") is True
                    or ("excluded" in marker and type(marker["excluded"]) is not bool)):
                raise OOMPError("scope_rejected")
            rows[identifier] = row
        row = rows[identifier]
        role = next((role for role in ("user", "assistant", "feedback")
                     if reference.turn_id == "trace-" + role + "-" + identifier), None)
        if role is None:
            raise OOMPError("scope_rejected")
        expected_event = event_identity(config.owner_id, identifier, role)
        if proof.event_id != expected_event:
            raise OOMPError("scope_rejected")
        key = (identifier, role)
        if key not in sources:
            content, occurred = _role_source(row, role)
            expected_reference = ContextSourceReference(
                source_system=config.source_system, external_event_id=identifier,
                timestamp=occurred, session_id=session_identity(row["session_id"]),
                turn_id="trace-" + role + "-" + identifier, locator=None)
            sources[key] = (content, expected_reference)
        content, expected_reference = sources[key]
        if reference != expected_reference:
            raise OOMPError("scope_rejected")
        if not 0 <= proof.span_start < proof.span_end <= len(content):
            raise OOMPError("scope_rejected")
        excerpt = content[proof.span_start:proof.span_end]
        if proof.quote is not None and proof.quote != excerpt:
            raise OOMPError("scope_rejected")
        return ValidatedContextSource(
            role=role, interaction_id=identifier, event_id=expected_event,
            memory_id=proof.memory_id, source_reference=expected_reference,
            span_start=proof.span_start, span_end=proof.span_end, excerpt=excerpt,
            source_content=content)

    validated = []
    for unit in result.evidence_packets:
        checked = tuple(validate(proof) for proof in unit.source_proofs)
        validated.append(ValidatedContextUnit(evidence=unit, sources=checked))
    return tuple(validated)
