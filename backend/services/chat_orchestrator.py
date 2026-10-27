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


def prepare_prompt(request, http_request, baseline_builder, context_loader, baseline_formatter):
    config = get_configuration()
    if config.mode == "off":
        return baseline_builder(request.session_id, request.user_id, request.message), None
    if not verified_owner(http_request, request.user_id, config):
        raise HTTPException(status_code=403, detail="Verified local memory owner required")
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