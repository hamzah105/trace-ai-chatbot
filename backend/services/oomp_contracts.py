"""Independent validation of the documented OOMP MCP wire contract."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from typing import Annotated, Literal
from pydantic import AfterValidator, Field, StrictBool, StrictInt, model_validator
from .oomp_config import ValueModel, ID


def utc(value):
    if value.tzinfo is None:
        raise ValueError("an offset is required")
    return value.astimezone(timezone.utc)


Timestamp = Annotated[datetime, AfterValidator(utc)]


class SourceReference(ValueModel):
    source_system: str = Field(pattern=ID)
    external_event_id: str = Field(min_length=1, max_length=512)
    timestamp: Timestamp
    session_id: str | None = Field(default=None, max_length=128)
    turn_id: str | None = Field(default=None, max_length=128)
    locator: str | None = Field(default=None, max_length=1024)


class EventPayload(ValueModel):
    event_id: str = Field(pattern=ID)
    idempotency_key: str = Field(pattern=ID)
    event_type: Literal["user_message", "assistant_message", "feedback"]
    content: str = Field(min_length=1, max_length=16384)
    source_reference: SourceReference
    occurred_at: Timestamp


class GraphPath(ValueModel):
    node_ids: tuple[str, ...] = Field(min_length=1, max_length=33)
    edge_ids: tuple[str, ...] = Field(default=(), max_length=32)
    relationship_types: tuple[str, ...] = ()
    edge_evidence: tuple[tuple[SourceReference, ...], ...] = ()
    edge_directions: tuple[Literal["forward", "reverse"], ...] = ()
    edge_validity: tuple[StrictBool | None, ...] = ()

    @model_validator(mode="after")
    def aligned(self):
        n = len(self.edge_ids)
        if len(self.node_ids) != n+1 or len(self.relationship_types) != n:
            raise ValueError("invalid path")
        if any(items and len(items) != n for items in
               (self.edge_evidence, self.edge_directions, self.edge_validity)):
            raise ValueError("invalid path proof")
        return self


class MemoryEvidence(ValueModel):
    memory_id: str = Field(pattern=ID)
    canonical_content: str = Field(min_length=1, max_length=32768)
    memory_type: str = Field(min_length=1, max_length=64)
    source_references: tuple[SourceReference, ...] = Field(min_length=1, max_length=1000)
    source_event_ids: tuple[str, ...] = Field(min_length=1, max_length=1000)
    retrieval_score: float | None = Field(default=None, strict=True, allow_inf_nan=False)
    valid_from: Timestamp | None = None
    valid_until: Timestamp | None = None
    status: Literal["active", "superseded", "retracted"] = "active"
    temporal_status: str = Field(min_length=1, max_length=64)
    selection_reasons: tuple[str, ...] = Field(default=(), max_length=16)
    graph_paths: tuple[GraphPath, ...] = Field(default=(), max_length=64)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def proof_alignment(self):
        if len(self.source_event_ids) != len(self.source_references) or self.status == "retracted":
            raise ValueError("invalid current evidence")
        return self


class RetrieveWire(ValueModel):
    retrieval_id: str = Field(pattern=ID)
    memories: tuple[MemoryEvidence, ...] = Field(max_length=20)
    source_references: tuple[SourceReference, ...] = Field(max_length=1000)
    graph_paths: tuple[GraphPath, ...] = Field(max_length=1000)
    estimated_token_count: StrictInt = Field(ge=0, le=32768)
    token_budget: StrictInt = Field(ge=1, le=32768)
    counting_method: Literal["utf8_bytes_upper_bound_v1"]
    context_packet: str = Field(max_length=32768)
    retrieval_mode: Literal["lexical", "semantic", "hybrid"]
    degraded: StrictBool
    warnings: tuple[str, ...] = Field(max_length=100)
    retrieval_trace: dict
    source_data_untrusted: Literal[True]
    budget_scope: Literal["context_packet_only"]

    @model_validator(mode="after")
    def packet_matches(self):
        measured = len(self.context_packet.encode("utf-8"))
        if measured != self.estimated_token_count or measured > self.token_budget:
            raise ValueError("invalid packet accounting")
        if not self.memories:
            if self.context_packet or measured:
                raise ValueError("invalid empty packet")
            return self
        packet = json.loads(self.context_packet)
        if (packet.get("estimated_token_count") != measured
                or packet.get("token_budget") != self.token_budget
                or packet.get("counting_method") != self.counting_method):
            raise ValueError("invalid packet metadata")
        packed = tuple(MemoryEvidence.model_validate(m) for m in packet["memories"])
        if packed != self.memories:
            raise ValueError("packet evidence differs")
        return self


def event_identity(owner_id, interaction_id, role):
    digest = hashlib.sha256(json.dumps([owner_id, str(interaction_id), role],
                                      separators=(",", ":")).encode()).hexdigest()
    return "trace-" + digest


def session_identity(session_id):
    return "trace-session-" + hashlib.sha256(session_id.encode()).hexdigest()