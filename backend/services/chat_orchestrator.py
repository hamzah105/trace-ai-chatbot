"""Deterministic pre-generation retrieval around the unchanged model interface."""
from __future__ import annotations
import logging
import time
from fastapi import HTTPException
from backend.database.database import get_database
from .oomp_config import get_configuration
from .oomp_security import verified_owner
from .oomp_client import OOMPClient, OOMPError
from .oomp_context import compose, validate_provenance

LOGGER = logging.getLogger("trace.oomp")
_SESSION_FALLBACK = {"unavailable", "timeout", "context_disabled", "context_unsupported",
                     "source_validation_unavailable"}
_AUTH_FAILURES = {"authorization_failed", "unauthorized", "forbidden"}


def _standalone(request, config, baseline_builder, diagnostics):
    """Keep transport status out of generation; retain it as safe metadata."""
    prompt = baseline_builder(request.session_id, request.user_id, request.message)
    size = len(prompt.encode("utf-8"))
    limit = min(config.max_prompt_bytes, config.num_ctx - config.generation_reserve - 256)
    if size > limit:
        raise HTTPException(status_code=413, detail="Recent context exceeds configured model capacity")
    # Adaptive allocation counts describe the discarded JSON prompt, not this
    # original same-session view. Do not persist those counts as actual usage.
    diagnostics = {k: v for k, v in diagnostics.items() if k in {
        "enabled", "retrieval_api", "retrieval_attempted", "retrieval_success",
        "retrieval_latency_ms", "orchestration_latency_ms", "error_code",
        "retrieval_status", "context_status", "context_coverage", "degraded",
        "context_degraded"}}
    diagnostics.update(prompt_mode="standalone", prompt_bytes=size,
        prompt_token_upper_bound=size, prompt_limit_bytes=limit,
        generation_reserve=config.generation_reserve, safety_overhead=256,
        evidence_count=0, selected_context_units=0, evidence_budget_used=0,
        recent_interaction_limit=8)
    return prompt, diagnostics


def prepare_prompt(request, http_request, baseline_builder, context_loader, baseline_formatter):
    config = get_configuration()
    if config.mode == "off":
        return baseline_builder(request.session_id, request.user_id, request.message), None
    if not verified_owner(http_request, request.user_id, config):
        raise HTTPException(status_code=403, detail="Verified local memory owner required")
    if config.retrieval_api == 'context_v1':
        from .oomp_adaptive_context import prepare_context_prompt
        prompt, diagnostics = prepare_context_prompt(request, config, get_database())
        if diagnostics.get("context_status") in _SESSION_FALLBACK:
            return _standalone(request, config, baseline_builder, diagnostics)
        return prompt, diagnostics
    transcript, feedback = context_loader(request.session_id, request.user_id)
    baseline = baseline_formatter(transcript, feedback, request.message)
    if len(baseline.encode("utf-8")) > config.max_prompt_bytes:
        raise HTTPException(status_code=413, detail="Recent context exceeds configured model capacity")
    diagnostics = {"enabled": True, "retrieval_attempted": True, "retrieval_success": False,
                   "retrieval_latency_ms": 0.0, "evidence_count": 0, "evidence_budget_used": 0,
                   "degraded": False, "error_code": None}
    started = time.perf_counter()
    try:
        result = OOMPClient(config).retrieve(request.message)
        database = get_database()
        if database is None:
            raise OOMPError("source_validation_unavailable")
        validate_provenance(result, config, database)
        final, selected = compose(config, request.message, transcript, feedback, result, baseline)
        diagnostics.update(retrieval_success=True, evidence_count=selected,
                           evidence_budget_used=result.estimated_token_count, degraded=result.degraded)
    except OOMPError as error:
        if error.code in _AUTH_FAILURES:
            raise HTTPException(status_code=403, detail="Memory authorization rejected") from None
        diagnostics["error_code"] = error.code
        LOGGER.warning("oomp_retrieval_failed code=%s", error.code)
        final = baseline
    except Exception:
        diagnostics["error_code"] = "invalid_evidence"
        LOGGER.warning("oomp_retrieval_failed code=invalid_evidence")
        final = baseline
    diagnostics["retrieval_latency_ms"] = round((time.perf_counter()-started)*1000, 3)
    diagnostics["prompt_bytes"] = len(final.encode("utf-8"))
    return final, diagnostics
