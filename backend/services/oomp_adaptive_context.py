"""TRACE-only opt-in context orchestration over authoritative host sources."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import time

from bson import ObjectId
from fastapi import HTTPException

from .oomp_allocator import AllocationError, prepare, compose
from .oomp_client import OOMPClient, OOMPError
from .oomp_context_provenance import validate_context_provenance

LOGGER = logging.getLogger("trace.oomp")
_HISTORY_LIMIT = 32
_ERROR_STATUSES = {
    "capability_missing": "context_unsupported",
    "unsupported": "context_unsupported",
    "not_found": "context_disabled",
    "timeout": "timeout",
    "authorization_failed": "unauthorized",
    "forbidden": "unauthorized",
    "unauthorized": "unauthorized",
    "scope_rejected": "invalid_evidence",
    "invalid_response": "invalid_evidence",
    "invalid_evidence": "invalid_evidence",
    "source_validation_unavailable": "source_validation_unavailable",
}


def _owned_exchanges(database, config, request):
    """Load a finite current-session view; no client-supplied hints or source IDs."""
    if request.user_id != config.owner_id or not request.session_id:
        raise HTTPException(status_code=403, detail="Verified memory session required")
    if database is None:
        raise HTTPException(status_code=503, detail="Recent source validation unavailable")
    try:
        session = database["sessions"].find_one(
            {"session_id": request.session_id, "user_id": config.owner_id})
        if not session:
            raise HTTPException(status_code=403, detail="Verified memory session required")
        query = {"session_id": request.session_id, "user_id": config.owner_id,
                 "oomp_publication.excluded": {"$ne": True}}
        projection = {name: 1 for name in (
            "_id", "user_id", "session_id", "user_message", "llama_response",
            "timestamp", "request_start_time", "response_end_time", "feedback",
            "oomp_publication.excluded")}
        rows = list(database["chat_history"].find(query, projection)
                    .sort([("timestamp", -1), ("_id", -1)]).limit(_HISTORY_LIMIT + 1))
        truncated = len(rows) > _HISTORY_LIMIT
        selected = []
        for original in rows[:_HISTORY_LIMIT]:
            row = dict(original)
            if (row.get("user_id") != config.owner_id
                    or row.get("session_id") != request.session_id
                    or not isinstance(row.get("_id"), ObjectId)):
                raise ValueError("invalid_recent_identity")
            marker = row.get("oomp_publication")
            if marker is None:
                marker = {}
            if not isinstance(marker, dict) or (type(marker.get("excluded", False)) is not bool or marker.get("excluded", False)):
                raise ValueError("invalid_recent_exclusion")
            for name in ("user_message", "llama_response"):
                content = row.get(name)
                if not isinstance(content, str) or not content or len(content) > 16384:
                    raise ValueError("invalid_recent_source")
                content.encode("utf-8")
            for name in ("timestamp", "request_start_time", "response_end_time"):
                if not isinstance(row.get(name), datetime):
                    raise ValueError("invalid_recent_timestamp")
                value = row[name]
                row[name] = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
            feedback = row.get("feedback") or {}
            if not isinstance(feedback, dict):
                raise ValueError("invalid_recent_feedback")
            if feedback.get("submitted") is True:
                if (type(feedback.get("rating")) is not int
                        or not 1 <= feedback["rating"] <= 4
                        or feedback.get("correctness") not in {"Correct", "Partial", "Incorrect"}
                        or feedback.get("length_type") not in {"Short", "To the Point", "Lengthy"}):
                    raise ValueError("invalid_recent_feedback")
            if feedback:
                feedback = dict(feedback)
                submitted_at = feedback.get("submitted_at")
                if isinstance(submitted_at, datetime):
                    feedback["submitted_at"] = submitted_at.replace(tzinfo=timezone.utc) if submitted_at.tzinfo is None else submitted_at.astimezone(timezone.utc)
                row["feedback"] = feedback
            selected.append(row)
        selected.reverse()
        return selected, truncated
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Recent source validation unavailable") from None


def prepare_context_prompt(request, config, database):
    """The caller has already verified the HTTP owner; Mongo remains authority."""
    started = time.perf_counter()
    exchanges, history_truncated = _owned_exchanges(database, config, request)
    try:
        allocation = prepare(config, request.message, exchanges,
                             history_truncated=history_truncated)
    except AllocationError:
        raise HTTPException(status_code=413, detail="Required context exceeds configured model capacity") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid context input") from None
    diagnostics = {
        "enabled": True, "retrieval_api": "context_v1",
        "retrieval_attempted": False, "retrieval_success": False,
        "retrieval_latency_ms": 0.0, "orchestration_latency_ms": 0.0,
        "evidence_count": 0, "evidence_budget_used": 0, "degraded": False,
        "error_code": None, "history_scan_truncated": history_truncated,
    }
    units = ()
    status, coverage, degraded = "budget_excluded", "unknown", False
    result = None
    if allocation.evidence_budget > 0:
        diagnostics["retrieval_attempted"] = True
        retrieval_started = time.perf_counter()
        try:
            result = OOMPClient(config).context(
                request.message, token_budget=allocation.evidence_budget,
                recent_user_turns=allocation.recent_user_turns)
            if result.retrieval_status == "unauthorized":
                raise OOMPError("unauthorized")
            units = validate_context_provenance(result, config, database)
            status, coverage, degraded = result.retrieval_status, result.coverage, result.degraded
            diagnostics.update(retrieval_success=True, retrieved_context_units=len(units),
                               evidence_budget_used=result.selected_context_bytes)
        except OOMPError as error:
            if error.code in {"authorization_failed", "forbidden", "unauthorized"}:
                raise HTTPException(status_code=403, detail="Memory authorization rejected") from None
            degraded = True
            status = _ERROR_STATUSES.get(error.code, "unavailable")
            # Log only this finite sanitized set, never remote text or input.
            diagnostics["error_code"] = error.code if error.code in {
                "capability_missing", "unsupported", "not_found", "timeout",
                "authorization_failed", "forbidden", "unauthorized", "scope_rejected",
                "invalid_response", "invalid_evidence", "source_validation_unavailable",
                "unavailable", "busy", "dependency_missing", "server_mismatch",
                "redirect_rejected", "response_limit", "query_limit"} else "unavailable"
            LOGGER.warning("oomp_context_failed code=%s", diagnostics["error_code"])
            units = ()
        except Exception:
            degraded = True
            status = "invalid_evidence"
            diagnostics["error_code"] = "invalid_evidence"
            LOGGER.warning("oomp_context_failed code=invalid_evidence")
            units = ()
        diagnostics["retrieval_latency_ms"] = round(
            (time.perf_counter() - retrieval_started) * 1000, 3)
    final, allocation_diagnostics = compose(
        allocation, units, status=status, coverage=coverage, degraded=degraded)
    diagnostics.update(allocation_diagnostics)
    diagnostics["evidence_count"] = allocation_diagnostics["selected_context_units"]
    diagnostics["degraded"] = degraded
    diagnostics["orchestration_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return final, diagnostics
