"""Independent, bounded validation of the opt-in oomp.context.v1 wire.

This module deliberately imports no OOMP implementation. The historical
memory.retrieve wire remains in oomp_contracts and is not changed here.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StrictBool,
    StrictInt, StringConstraints, field_serializer, field_validator, model_validator,
)

CONTEXT_VERSION = "oomp.context.v1"
COUNTING_METHOD = "utf8_bytes_upper_bound_v1"
Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128,
                                             pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)]
Anchor = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=160)]
Label = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]
Intent = Literal["factual_recall", "episodic_recall", "plan_followup", "historical_correction",
                 "entity_lookup", "current_session_only", "uncertain_recall"]
Status = Literal["found_relevant_evidence", "no_relevant_evidence", "index_incomplete",
                 "coverage_unknown", "unavailable", "unauthorized", "candidate_uncertain",
                 "budget_excluded"]
Resolution = Literal["object_snapshot", "episode_summary", "canonical_fact", "source_evidence"]
TopicHint = Literal["projects", "relocation", "preferences", "identity-claims",
                    "sensitive-discussion", "conversation"]


def _datetime_input(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("timestamp must be an offset-aware timestamp")
    return value


def _utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a UTC offset")
    return value.astimezone(timezone.utc)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("score must be a number")
    try:
        return float(value)
    except OverflowError:
        raise ValueError("score is out of range") from None


def _true(value):
    if value is not True:
        raise ValueError("untrusted-source marker is required")
    return value


Timestamp = Annotated[datetime, BeforeValidator(_datetime_input), AfterValidator(_utc)]
Score = Annotated[float, BeforeValidator(_number), Field(allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=0)]


class ContextValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class ContextSourceReference(ContextValue):
    source_system: Identifier
    external_event_id: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512)]
    timestamp: Timestamp
    session_id: Identifier | None = None
    turn_id: Identifier | None = None
    locator: Annotated[str, StringConstraints(strict=True, max_length=1024)] | None = None

    @field_validator("external_event_id", "locator")
    @classmethod
    def nonblank_reference(cls, value):
        if value is not None and not value.strip():
            raise ValueError("source reference text must not be blank")
        return value


class ContextSource(ContextValue):
    memory_id: Identifier
    event_id: Identifier
    source_reference: ContextSourceReference
    span_start: StrictInt = Field(ge=0, le=1_000_000)
    span_end: StrictInt = Field(ge=1, le=1_000_000)
    quote: Annotated[str, StringConstraints(strict=True, max_length=1_000_000)] | None = None

    @model_validator(mode="after")
    def span_shape(self):
        if self.span_end <= self.span_start:
            raise ValueError("source span must be nonempty")
        if self.quote is not None and len(self.quote) != self.span_end - self.span_start:
            raise ValueError("quote length differs from source span")
        return self


class ContextEvidence(ContextValue):
    unit_id: Identifier
    resolution: Resolution
    content: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1_000_000)]
    memory_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=16)
    source_proofs: tuple[ContextSource, ...] = Field(min_length=1, max_length=16)
    object_ids: tuple[Identifier, ...] = Field(default=(), max_length=8)
    revision_id: Identifier | None = None
    source_fingerprint: Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")] | None = None
    assertion_kinds: tuple[Label, ...] = Field(default=(), max_length=16)
    temporal_status: Label = "uncertain"
    selection_reasons: tuple[Identifier, ...] = Field(default=(), max_length=16)
    retrieval_score: Score | None = None
    derived: StrictBool = False
    uncertain: StrictBool = True

    @model_validator(mode="after")
    def proof_alignment(self):
        if len(set(self.memory_ids)) != len(self.memory_ids):
            raise ValueError("duplicate memory identity")
        if set(self.memory_ids) != {proof.memory_id for proof in self.source_proofs}:
            raise ValueError("memory identities and proofs differ")
        identities = {(proof.memory_id, proof.event_id, proof.span_start, proof.span_end)
                      for proof in self.source_proofs}
        if len(identities) != len(self.source_proofs):
            raise ValueError("duplicate source proof")
        return self


class ContextQueryPlan(ContextValue):
    retrieval_intent: Intent
    query_variants: tuple[Text, ...] = Field(default=(), max_length=3)
    anchors: tuple[Anchor, ...] = Field(default=(), max_length=4)
    focus_terms: tuple[Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)], ...] = Field(default=(), max_length=32)
    topic_hints: tuple[TopicHint, ...] = Field(default=(), max_length=6)
    needs_clarification: StrictBool = False
    search_allowed: StrictBool = True
    reasons: tuple[Identifier, ...] = Field(default=(), max_length=16)


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate packet key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite packet number")


class ContextResult(ContextValue):
    context_contract_version: Literal["oomp.context.v1"] = CONTEXT_VERSION
    retrieval_intent: Intent
    retrieval_status: Status
    evidence_packets: tuple[ContextEvidence, ...] = Field(default=(), max_length=20)
    source_references: tuple[ContextSourceReference, ...] = Field(default=(), max_length=320)
    context_packet: Annotated[str, StringConstraints(strict=True, max_length=32768)] = ""
    selected_context_bytes: StrictInt = Field(default=0, ge=0, le=32768)
    token_budget: StrictInt = Field(default=1200, ge=1, le=32768)
    counting_method: Literal["utf8_bytes_upper_bound_v1"] = COUNTING_METHOD
    degraded: StrictBool = False
    reasons: tuple[Identifier, ...] = Field(default=(), max_length=32)
    coverage: Literal["complete", "partial", "unknown"] = "unknown"
    trace: Mapping[Identifier, Count] = Field(default_factory=dict, max_length=32)
    query_plan: ContextQueryPlan | None = None
    source_data_untrusted: Annotated[Literal[True], BeforeValidator(_true)] = True
    budget_scope: Literal["context_packet_only"] = "context_packet_only"

    @field_validator("trace")
    @classmethod
    def freeze_trace(cls, value):
        return MappingProxyType(dict(value))

    @field_serializer("trace")
    def serialize_trace(self, value):
        return dict(value)

    @model_validator(mode="after")
    def packet_accounting(self):
        if self.retrieval_status == "unauthorized" and (
                self.evidence_packets or self.source_references or self.trace or self.query_plan is not None):
            raise ValueError("denied context must not disclose sources or diagnostics")
        measured = len(self.context_packet.encode("utf-8"))
        if measured != self.selected_context_bytes or measured > self.token_budget:
            raise ValueError("invalid context byte accounting")
        if not self.evidence_packets:
            if self.context_packet or self.source_references:
                raise ValueError("empty evidence requires an empty packet and sources")
            return self
        packet = json.loads(self.context_packet, object_pairs_hook=_unique_object,
                            parse_constant=_invalid_constant)
        expected_keys = {"context_contract_version", "evidence_packets", "token_budget",
                         "counting_method", "selected_context_bytes"}
        if (not isinstance(packet, dict) or set(packet) != expected_keys
                or packet.get("context_contract_version") != CONTEXT_VERSION
                or type(packet.get("token_budget")) is not int
                or packet["token_budget"] != self.token_budget
                or packet.get("counting_method") != COUNTING_METHOD
                or type(packet.get("selected_context_bytes")) is not int
                or packet["selected_context_bytes"] != measured
                or not isinstance(packet.get("evidence_packets"), list)):
            raise ValueError("invalid context packet metadata")
        packed = tuple(ContextEvidence.model_validate(value) for value in packet["evidence_packets"])
        if packed != self.evidence_packets:
            raise ValueError("packet evidence differs from response")
        references = tuple(dict.fromkeys(proof.source_reference for unit in self.evidence_packets
                                         for proof in unit.source_proofs))
        if references != self.source_references:
            raise ValueError("packet source references differ from response")
        return self


ContextWire = ContextResult
