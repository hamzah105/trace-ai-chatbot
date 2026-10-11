"""Finalize one owned active session with an immutable analytics summary."""

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from backend.analytics.dashboard import build_session_overview
from backend.analytics.data_service import get_session_analytics_data
from backend.analytics.metrics import compute_session_metrics
from backend.analytics.snapshot import FINAL_ANALYTICS_VERSION
from backend.database.database import get_database
from backend.services.session_lifecycle import session_lifecycle
from backend.services.session_service import (
    SessionNotFoundError, SessionOwnershipError, get_session, utc_now,
)


class PendingFeedbackError(Exception):
    def __init__(self, interactions):
        self.count = len(interactions)
        self.interaction_id = interactions[0].get("interaction_id") if interactions else None
        super().__init__("All interaction feedback must be submitted before ending the session")


class FinalizationConflictError(Exception):
    pass


class FinalizationComputationError(Exception):
    pass


def finalize_session(session_id, user_id):
    with session_lifecycle(session_id):
        try:
            session = get_session(session_id, user_id)
        except PyMongoError as error:
            raise RuntimeError("Database is unavailable") from error
        if session.get("status") == "ended":
            return session
        if session.get("status") != "active":
            raise FinalizationConflictError("Session is not active")

        try:
            data = get_session_analytics_data(session_id, user_id)
        except (SessionNotFoundError, SessionOwnershipError, RuntimeError):
            raise
        except Exception as error:
            raise FinalizationComputationError("Final analytics could not be computed") from error

        interactions = data["interactions"]
        pending = [row for row in interactions if row.get("feedback_submitted") is not True]
        if pending:
            raise PendingFeedbackError(pending)

        try:
            metrics = compute_session_metrics(interactions)
            overview = build_session_overview(metrics)
            now = utc_now()
            snapshot = {
                "version": FINAL_ANALYTICS_VERSION,
                "finalized_at": now,
                "interaction_count": len(interactions),
                "overview": overview,
                "metrics": metrics,
            }
        except Exception as error:
            raise FinalizationComputationError("Final analytics could not be computed") from error

        db = get_database()
        if db is None:
            raise RuntimeError("Database is unavailable")
        query = {
            "session_id": session_id,
            "user_id": user_id,
            "status": "active",
            "updated_at": session.get("updated_at"),
            "message_count": session.get("message_count"),
        }
        try:
            updated = db["sessions"].find_one_and_update(
                query,
                {"$set": {
                    "status": "ended", "ended_at": now, "updated_at": now,
                    "final_analytics": snapshot,
                }},
                return_document=ReturnDocument.AFTER,
            )
            if updated is not None:
                return updated
            current = get_session(session_id, user_id)
        except PyMongoError as error:
            raise RuntimeError("Database is unavailable") from error
        if current.get("status") == "ended":
            return current
        raise FinalizationConflictError("Session changed during finalization; retry")
