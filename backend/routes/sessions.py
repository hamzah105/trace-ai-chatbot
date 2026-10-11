from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from backend.analytics.finalization import (
    FinalizationComputationError, FinalizationConflictError, PendingFeedbackError,
)
from backend.analytics.snapshot import finalization_metadata, public_snapshot
from backend.services.session_service import (
    SessionEndedError,
    SessionNotFoundError,
    SessionOwnershipError,
    create_session,
    end_session,
    get_pending_feedback,
    get_session,
    get_session_history,
    get_user_sessions,
)


router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)


class EndSessionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)


def serialize_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value


def serialize_session(session):
    allowed = (
        "_id", "session_id", "user_id", "status", "created_at", "updated_at",
        "ended_at", "message_count", "summary", "topics", "title",
    )
    public = {key: serialize_value(session[key]) for key in allowed if key in session}
    if "topics" in public:
        public["topics"] = [topic for topic in public["topics"] if isinstance(topic, str)] if isinstance(public["topics"], list) else []
    for key in ("summary", "title"):
        if key in public and not isinstance(public[key], str):
            public[key] = ""
    public["finalization"] = finalization_metadata(session)
    snapshot = public_snapshot(session)
    if snapshot is not None:
        public["final_analytics"] = snapshot
    return public


def session_error(error):
    if isinstance(error, PendingFeedbackError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "code": "feedback_required", "message": str(error),
            "pending_feedback_count": error.count,
            "interaction_id": error.interaction_id,
        })
    if isinstance(error, FinalizationConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, FinalizationComputationError):
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                             detail="Final analytics could not be computed")
    if isinstance(error, SessionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, SessionOwnershipError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, SessionEndedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database is unavailable",
    )


@router.post("/create", status_code=status.HTTP_201_CREATED)
def create(request: CreateSessionRequest):
    try:
        session = create_session(request.user_id, request.session_id)
        return {"success": True, "session": serialize_session(session)}
    except (SessionOwnershipError, RuntimeError, PyMongoError) as error:
        raise session_error(error) from error


@router.get("/user/{user_id}")
def list_for_user(user_id: str):
    try:
        sessions = get_user_sessions(user_id)
        return {
            "success": True,
            "sessions": [serialize_session(session) for session in sessions],
        }
    except (RuntimeError, PyMongoError) as error:
        raise session_error(error) from error


@router.get("/{session_id}/messages")
def history(
    session_id: str,
    user_id: str = Query(min_length=1, max_length=200),
):
    try:
        session, messages = get_session_history(session_id, user_id)
        pending_interaction = None
        if session.get("status") == "active" and messages:
            latest = messages[-1]
            if not (latest.get("feedback") or {}).get("submitted"):
                pending_interaction = latest

        return {
            "success": True,
            "session_id": session["session_id"],
            "status": session.get("status", "active"),
            "messages": serialize_value(messages),
            "pending_feedback": pending_interaction is not None,
            "pending_interaction_id": (
                str(pending_interaction["_id"])
                if pending_interaction is not None
                else None
            ),
            "message_count": len(messages),
            "finalization": finalization_metadata(session),
        }
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError, PyMongoError) as error:
        raise session_error(error) from error


@router.get("/{session_id}")
def retrieve(
    session_id: str,
    user_id: str = Query(min_length=1, max_length=200),
):
    try:
        session = serialize_session(get_session(session_id, user_id))
        pending = None
        if session.get("status") == "active":
            interaction = get_pending_feedback(session_id, user_id)
            if interaction:
                pending = str(interaction["_id"])
        session["pending_feedback_interaction_id"] = pending
        return {"success": True, "session": session, "finalization": session["finalization"]}
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError, PyMongoError) as error:
        raise session_error(error) from error


@router.post("/{session_id}/end")
def end(session_id: str, request: EndSessionRequest):
    try:
        session = end_session(session_id, request.user_id)
        public = serialize_session(session)
        return {"success": True, "session": public, "finalization": public["finalization"]}
    except (
        SessionNotFoundError,
        SessionOwnershipError,
        SessionEndedError,
        PendingFeedbackError,
        FinalizationConflictError,
        FinalizationComputationError,
        RuntimeError,
        PyMongoError,
    ) as error:
        raise session_error(error) from error
