"""Server-owned Stage 8 policy; no SDK or OOMP package imports."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt, field_validator, model_validator

ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SECRET = r"^[A-Za-z0-9_-]{43,256}$"


class ConfigurationError(ValueError):
    def __init__(self):
        super().__init__("Invalid OOMP deployment configuration")


class ValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WriterGrant(ValueModel):
    grant_id: str = Field(pattern=ID)
    principal_id: str = Field(pattern=ID)
    tenant_id: str = Field(pattern=ID)
    namespace: str = Field(pattern=ID)
    source_type: Literal["user", "assistant"]
    source_system: str = Field(pattern=ID)
    event_types: tuple[Literal["user_message", "assistant_message", "feedback"], ...]
    bearer_token_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    approval_key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")

    def credential(self, approval=False):
        value = os.environ.get(self.approval_key_env if approval else self.bearer_token_env, "")
        if not re.fullmatch(SECRET, value):
            raise ConfigurationError()
        return value

    def signature_identity(self):
        return {key: getattr(self, key) for key in
                ("grant_id", "principal_id", "tenant_id", "namespace", "source_type", "source_system")} | {
                    "event_types": list(self.event_types)}


class OOMPConfiguration(ValueModel):
    mode: Literal["off", "retrieve", "retrieve_and_ingest"] = "off"
    url: str = "http://127.0.0.1:8765/mcp"
    origin: str = "http://127.0.0.1:8000"
    owner_id: str = Field(default="", max_length=200)
    tenant_id: str = "trace-local"
    namespace: str = "personal"
    principal_id: str = "trace-host"
    source_system: str = "trace-ai"
    read_token: SecretStr = Field(default=SecretStr(""), repr=False, exclude=True)
    owner_key: SecretStr = Field(default=SecretStr(""), repr=False, exclude=True)
    evidence_budget: StrictInt = Field(default=1200, ge=1, le=32768)
    max_results: StrictInt = Field(default=5, ge=1, le=20)
    timeout_seconds: float = Field(default=5, ge=.1, le=15, allow_inf_nan=False)
    max_prompt_bytes: StrictInt = Field(default=7000, ge=1024, le=32768)
    num_ctx: StrictInt = Field(default=8192, ge=2048, le=65536)
    generation_reserve: StrictInt = Field(default=512, ge=256, le=4096)
    allow_degraded: bool = False
    retrieval_mode: Literal["lexical", "semantic", "hybrid"] = "lexical"
    writers: dict[str, WriterGrant] = Field(default_factory=dict, exclude=True, repr=False)

    @model_validator(mode="after")
    def trusted_settings(self):
        if self.mode == "off":
            return self
        for endpoint, path in ((self.url, "/mcp"), (self.origin, "")):
            p = urlsplit(endpoint)
            try:
                address = ipaddress.ip_address(p.hostname or "")
                port = p.port
            except ValueError:
                raise ConfigurationError() from None
            if (p.scheme != "http" or not address.is_loopback or port is None
                    or p.path != path or p.query or p.fragment or p.username or p.password):
                raise ConfigurationError()
        if not self.owner_id or self.owner_id == "anonymous":
            raise ConfigurationError()
        for value in (self.tenant_id, self.namespace, self.principal_id, self.source_system):
            if not re.fullmatch(ID, value):
                raise ConfigurationError()
        tokens = [self.owner_key.get_secret_value(), self.read_token.get_secret_value()]
        if any(not re.fullmatch(SECRET, v) for v in tokens) or len(set(tokens)) != 2:
            raise ConfigurationError()
        if self.max_prompt_bytes + self.generation_reserve + 256 > self.num_ctx:
            raise ConfigurationError()
        if self.mode == "retrieve_and_ingest":
            if set(self.writers) != {"user", "assistant", "feedback"}:
                raise ConfigurationError()
            roles = {"user": ("user", "user_message"), "assistant": ("assistant", "assistant_message"),
                     "feedback": ("user", "feedback")}
            for role, grant in self.writers.items():
                source_type, event_type = roles[role]
                if ((grant.tenant_id, grant.namespace, grant.principal_id, grant.source_system) !=
                    (self.tenant_id, self.namespace, self.principal_id, self.source_system)
                    or grant.source_type != source_type or event_type not in grant.event_types):
                    raise ConfigurationError()
                bearer, approval = grant.credential(), grant.credential(approval=True)
                if approval in (*tokens, bearer) or bearer == tokens[0]:
                    raise ConfigurationError()
            all_bearers = {g.credential() for g in self.writers.values()} | set(tokens)
            if any(g.credential(approval=True) in all_bearers for g in self.writers.values()):
                raise ConfigurationError()
        elif self.writers:
            raise ConfigurationError()
        return self

    @property
    def policy_id(self):
        public = {name: getattr(self, name) for name in
                  ("owner_id", "tenant_id", "namespace", "principal_id", "source_system")}
        public["writers"] = {role: grant.signature_identity() for role, grant in sorted(self.writers.items())}
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def get_configuration():
    """Read named settings only. Off mode ignores optional secrets and endpoints."""
    mode = os.environ.get("TRACE_OOMP_MODE", "off")
    if mode == "off":
        return OOMPConfiguration()
    try:
        values = {"mode": mode}
        names = {
            "url": "URL", "origin": "TRACE_ORIGIN", "owner_id": "OWNER_ID", "tenant_id": "TENANT_ID",
            "namespace": "NAMESPACE", "principal_id": "PRINCIPAL_ID", "source_system": "SOURCE_SYSTEM",
            "read_token": "READ_TOKEN", "owner_key": "OWNER_KEY", "retrieval_mode": "RETRIEVAL_MODE",
        }
        for field, suffix in names.items():
            key = "TRACE_OOMP_" + suffix
            if key in os.environ:
                values[field] = os.environ[key]
        for field in ("evidence_budget", "max_results", "max_prompt_bytes", "num_ctx", "generation_reserve"):
            key = "TRACE_OOMP_" + field.upper()
            if key in os.environ:
                values[field] = int(os.environ[key])
        if "TRACE_OOMP_TIMEOUT_SECONDS" in os.environ:
            values["timeout_seconds"] = float(os.environ["TRACE_OOMP_TIMEOUT_SECONDS"])
        if "TRACE_OOMP_ALLOW_DEGRADED" in os.environ:
            value = os.environ["TRACE_OOMP_ALLOW_DEGRADED"].lower()
            if value not in {"true", "false"}:
                raise ConfigurationError()
            values["allow_degraded"] = value == "true"
        if mode == "retrieve_and_ingest":
            with Path(os.environ["TRACE_OOMP_WRITER_CONFIG"]).open("rb") as handle:
                raw = handle.read(16385)
            if len(raw) > 16384:
                raise ConfigurationError()
            values["writers"] = json.loads(raw.decode("utf-8-sig"))
        return OOMPConfiguration.model_validate(values)
    except Exception:
        raise ConfigurationError() from None