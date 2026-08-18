import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from backend.database.database import get_database


class SessionNotFoundError(Exception):
    pass


class SessionOwnershipError(Exception):
    pass


class SessionEndedError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def _database():
    db = get_database()
    if db is None:
        raise RuntimeError("Database is unavailable")
    return db


def create_session(user_id: str, session_id: str | None = None):
    """Create a new session, or safely retrieve the requested owned session."""
    db = _database()
    sessions = db["sessions"]
    requested_id = session_id.strip() if session_id else str(uuid.uuid4())

    existing = sessions.find_one({"session_id": requested_id})
    if existing:
        if existing.get("user_id") != user_id:
            raise SessionOwnershipError("Session belongs to another user")
        return existing

    now = utc_now()
    document = {
        "session_id": requested_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "message_count": 0,
        "summary": "",
        "topics": [],
    }

    try:
        sessions.insert_one(document)
    except DuplicateKeyError:
        existing = sessions.find_one({"session_id": requested_id})
        if not existing or existing.get("user_id") != user_id:
            raise SessionOwnershipError("Session belongs to another user")
        return existing

    return document


def ensure_active_session(session_id: str, user_id: str):
    session = create_session(user_id=user_id, session_id=session_id)
    if session.get("status") != "active":
        raise SessionEndedError("Session has ended; create a new session")
    return session


def get_session(session_id: str, user_id: str | None = None):
    session = _database()["sessions"].find_one({"session_id": session_id})
    if not session:
        raise SessionNotFoundError("Session not found")
    if user_id and session.get("user_id") != user_id:
        raise SessionOwnershipError("Session belongs to another user")
    return session


def get_user_sessions(user_id: str):
    db = _database()
    sessions = list(
        db["sessions"]
        .find({"user_id": user_id})
        .sort("updated_at", -1)
    )

    for session in sessions:
        first_interaction = db["chat_history"].find_one(
            {"session_id": session["session_id"], "user_id": user_id},
            sort=[("timestamp", 1)],
        )
        first_message = (first_interaction or {}).get("user_message", "")
        clean_message = " ".join(first_message.split())
        session["title"] = (
            clean_message
            if len(clean_message) <= 40
            else clean_message[:37].rstrip() + "..."
        ) or "New chat"

    return sessions


def get_session_history(session_id: str, user_id: str):
    """Return one owned session and only its interactions, oldest first."""
    db = _database()
    session = db["sessions"].find_one({"session_id": session_id})
    if not session:
        raise SessionNotFoundError("Session not found")
    if session.get("user_id") != user_id:
        raise SessionOwnershipError("Session belongs to another user")

    messages = list(
        db["chat_history"]
        .find({"session_id": session_id, "user_id": user_id})
        .sort("timestamp", 1)
    )
    return session, messages


def end_session(session_id: str, user_id: str):
    session = get_session(session_id, user_id)
    if session.get("status") == "ended":
        return session

    _database()["sessions"].update_one(
        {"session_id": session_id, "user_id": user_id},
        {"$set": {"status": "ended", "updated_at": utc_now()}},
    )
    return get_session(session_id, user_id)


def record_interaction(session_id: str, user_id: str, topic_label: str):
    result = _database()["sessions"].update_one(
        {"session_id": session_id, "user_id": user_id, "status": "active"},
        {
            "$inc": {"message_count": 1},
            "$set": {"updated_at": utc_now()},
            "$addToSet": {"topics": topic_label},
        },
    )
    if result.matched_count == 0:
        raise SessionNotFoundError("Active session not found")


def get_pending_feedback(session_id: str, user_id: str):
    latest_interaction = _database()["chat_history"].find_one(
        {"session_id": session_id, "user_id": user_id},
        sort=[("timestamp", -1)],
    )
    if latest_interaction and not (latest_interaction.get("feedback") or {}).get("submitted"):
        return latest_interaction
    return None


def touch_session(session_id: str, user_id: str):
    _database()["sessions"].update_one(
        {"session_id": session_id, "user_id": user_id},
        {"$set": {"updated_at": utc_now()}},
    )
