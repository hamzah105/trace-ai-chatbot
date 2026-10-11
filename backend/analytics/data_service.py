"""Owned, read-only session data prepared for future analytics features."""

from datetime import datetime, timezone
from math import isfinite

from bson import ObjectId
from pymongo.errors import PyMongoError

from backend.services.session_service import get_session_history
from backend.analytics.snapshot import finalization_metadata, public_snapshot
from backend.services.topic_service import classify_topic


ALLOWED_TOPICS = frozenset({
    "Machine Learning", "Deep Learning", "Healthcare AI", "Power Systems",
    "E-commerce AI", "General",
})
ALLOWED_CORRECTNESS = frozenset({"Correct", "Partial", "Incorrect"})
ALLOWED_LENGTH_TYPES = frozenset({"Short", "To the Point", "Lengthy"})


def _datetime(value):
    """Interpret stored datetimes and legacy ISO strings; assume UTC if naive."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _timestamp(value):
    parsed = _datetime(value)
    return parsed.isoformat() if parsed else None


def _text(value):
    return value if isinstance(value, str) else ""


def _response_seconds(interaction):
    for field in ("response_time_seconds", "response_time"):
        value = interaction.get(field)
        if isinstance(value, bool):
            continue
        try:
            seconds = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if isfinite(seconds) and seconds >= 0:
            return seconds
    return None


def _sort_key(interaction):
    # Legacy records may have no timestamp; use request start, then put undated
    # records last. Normalizing to UTC makes aware and naive datetimes comparable.
    moment = _datetime(interaction.get("timestamp")) or _datetime(
        interaction.get("request_start_time")
    )
    identifier = interaction.get("_id")
    return (
        moment is None,
        moment.astimezone(timezone.utc) if moment else datetime.max.replace(tzinfo=timezone.utc),
        str(identifier) if identifier is not None else "",
    )


def phase_for_position(index, total):
    """Assign thirds using (index + 1) / total, with explicit N=1 and N=2 rules."""
    if total < 1 or not 0 <= index < total:
        raise ValueError("Interaction position is outside the session")
    if total == 1:
        return "Start"
    if total == 2:
        return "Start" if index == 0 else "End"
    # Integer comparisons preserve the exact <=1/3 and <=2/3 boundaries.
    position = index + 1
    if 3 * position <= total:
        return "Start"
    if 3 * position <= 2 * total:
        return "Middle"
    return "End"


def normalize_interaction(interaction, session_id, user_id, interaction_number, phase):
    """Return only approved analytics fields; never pass through raw Mongo data."""
    user_message = _text(interaction.get("user_message"))
    llama_response = _text(interaction.get("llama_response"))
    topic = interaction.get("topic_label")
    if not isinstance(topic, str) or topic not in ALLOWED_TOPICS:
        topic = classify_topic(user_message, llama_response)

    feedback = interaction.get("feedback")
    feedback = feedback if isinstance(feedback, dict) else {}
    rating = feedback.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or rating not in (1, 2, 3, 4):
        rating = None
    correctness = feedback.get("correctness")
    if not isinstance(correctness, str) or correctness not in ALLOWED_CORRECTNESS:
        correctness = None
    length_type = feedback.get("length_type")
    if not isinstance(length_type, str) or length_type not in ALLOWED_LENGTH_TYPES:
        length_type = None

    identifier = interaction.get("_id")
    return {
        "interaction_id": str(identifier) if isinstance(identifier, (ObjectId, str)) else None,
        "session_id": session_id,
        "user_id": user_id,
        "interaction_number": interaction_number,
        "phase": phase,
        "topic_label": topic,
        "user_message": user_message,
        "llama_response": llama_response,
        "timestamp": _timestamp(interaction.get("timestamp")),
        "request_start_time": _timestamp(interaction.get("request_start_time")),
        "response_end_time": _timestamp(interaction.get("response_end_time")),
        "response_time_seconds": _response_seconds(interaction),
        "rating": rating,
        "correctness": correctness,
        "length_type": length_type,
        "feedback_submitted": feedback.get("submitted") is True,
    }


def get_session_analytics_data(session_id, user_id):
    """Read complete owned history; keep a valid stored count separately from actual rows."""
    try:
        session, history = get_session_history(session_id, user_id)
    except PyMongoError as error:
        raise RuntimeError("Database is unavailable") from error

    interactions = sorted(history, key=_sort_key)
    count = len(interactions)
    stored_count = session.get("message_count")
    if isinstance(stored_count, bool) or not isinstance(stored_count, int) or stored_count < 0:
        stored_count = count

    result = {
        "success": True,
        "session": {
            "session_id": session_id,
            "user_id": user_id,
            "status": _text(session.get("status")),
            "message_count": stored_count,
            "created_at": _timestamp(session.get("created_at")),
            "updated_at": _timestamp(session.get("updated_at")),
            "finalization": finalization_metadata(session),
        },
        "interaction_count": count,
        "interactions": [
            normalize_interaction(record, session_id, user_id, index + 1,
                                  phase_for_position(index, count))
            for index, record in enumerate(interactions)
        ],
    }
    snapshot = public_snapshot(session)
    if snapshot is not None:
        result["final_analytics"] = snapshot
    result["finalization"] = finalization_metadata(session)
    return result
