"""Owned session data and read-only Phase 3 analytics endpoints."""

from fastapi import APIRouter, Query

from backend.analytics.data_service import get_session_analytics_data
from backend.analytics.charts import build_session_charts
from backend.analytics.dashboard import build_session_overview
from backend.analytics.metrics import compute_session_metrics
from backend.analytics.tables import build_session_tables
from backend.routes.sessions import session_error
from backend.services.session_service import SessionNotFoundError, SessionOwnershipError


router = APIRouter(prefix="/analytics", tags=["analytics"])


def _metrics(data):
    snapshot = data.get("final_analytics") or {}
    stored = snapshot.get("metrics")
    return stored if isinstance(stored, dict) else compute_session_metrics(data["interactions"])


@router.get("/session/{session_id}")
def session_analytics(session_id: str, user_id: str = Query(min_length=1, max_length=200)):
    try:
        return get_session_analytics_data(session_id, user_id)
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error


@router.get("/session/{session_id}/metrics")
def session_metrics(session_id: str, user_id: str = Query(min_length=1, max_length=200)):
    """Compute metrics only after Part 1 has retrieved and normalized owned data."""
    try:
        data = get_session_analytics_data(session_id, user_id)
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error
    return {
        "success": True,
        "session": data["session"],
        "metrics": _metrics(data),
        "finalization": data.get("finalization"),
    }


@router.get("/session/{session_id}/tables")
def session_tables(session_id: str, user_id: str = Query(min_length=1, max_length=200)):
    """Present server-computed metrics as read-only tables for an owned session."""
    try:
        data = get_session_analytics_data(session_id, user_id)
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error
    metrics = _metrics(data)
    return {
        "success": True,
        "session": data["session"],
        "tables": build_session_tables(data["interactions"], metrics),
        "finalization": data.get("finalization"),
    }


@router.get("/session/{session_id}/charts")
def session_charts(session_id: str, user_id: str = Query(min_length=1, max_length=200)):
    """Return the seven read-only charts for an owned session."""
    try:
        data = get_session_analytics_data(session_id, user_id)
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error
    metrics = _metrics(data)
    return {
        "success": True,
        "session": data["session"],
        "charts": build_session_charts(data["interactions"], metrics),
        "finalization": data.get("finalization"),
    }


@router.get("/session/{session_id}/dashboard")
def session_dashboard(session_id: str, user_id: str = Query(min_length=1, max_length=200)):
    """Reuse each analytics layer once for the frontend dashboard."""
    try:
        data = get_session_analytics_data(session_id, user_id)
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error
    interactions = data["interactions"]
    metrics = _metrics(data)
    snapshot = data.get("final_analytics") or {}
    overview = snapshot.get("overview")
    if not isinstance(overview, dict):
        overview = build_session_overview(metrics)
    return {
        "success": True,
        "session": data["session"],
        "overview": overview,
        "metrics": metrics,
        "tables": build_session_tables(interactions, metrics),
        "charts": build_session_charts(interactions, metrics),
        "finalization": data.get("finalization"),
    }
