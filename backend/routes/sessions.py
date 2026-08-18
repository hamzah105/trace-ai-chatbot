from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

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
    return serialize_value(session)


def session_error(error):
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
    except (SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error


@router.get("/user/{user_id}")
def list_for_user(user_id: str):
    try:
        sessions = get_user_sessions(user_id)
        return {
            "success": True,
            "sessions": [serialize_session(session) for session in sessions],
        }
    except RuntimeError as error:
        raise session_error(error) from error


@router.get("/{session_id}/messages")
def history(
    session_id: str,
    user_id: str = Query(min_length=1, max_length=200),
):
    try:
        session, messages = get_session_history(session_id, user_id)
        pending_interaction = None
        if messages:
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
        }
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error


@router.get("/{session_id}")
def retrieve(
    session_id: str,
    user_id: str | None = Query(default=None, min_length=1, max_length=200),
):
    try:
        session = serialize_session(get_session(session_id, user_id))
        pending = None
        if user_id:
            interaction = get_pending_feedback(session_id, user_id)
            if interaction:
                pending = str(interaction["_id"])
        session["pending_feedback_interaction_id"] = pending
        return {"success": True, "session": session}
    except (SessionNotFoundError, SessionOwnershipError, RuntimeError) as error:
        raise session_error(error) from error


@router.post("/{session_id}/end")
def end(session_id: str, request: EndSessionRequest):
    try:
        session = end_session(session_id, request.user_id)
        return {"success": True, "session": serialize_session(session)}
    except (
        SessionNotFoundError,
        SessionOwnershipError,
        SessionEndedError,
        RuntimeError,
    ) as error:
        raise session_error(error) from error
