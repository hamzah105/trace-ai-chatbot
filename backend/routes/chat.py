import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from backend.database.database import get_database
from backend.services.chat_storage import save_chat
from backend.services.session_lifecycle import session_lifecycle
from backend.services.ollama_service import (
    OllamaServiceError,
    OllamaTimeoutError,
    generate_response,
)
from backend.services.session_service import (
    SessionEndedError,
    SessionNotFoundError,
    SessionOwnershipError,
    ensure_active_session,
    get_pending_feedback,
    record_interaction,
)
from backend.services.topic_service import classify_topic


router = APIRouter(tags=["chat"])
CONTEXT_INTERACTION_LIMIT = 8


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    user_id: str = Field(default="anonymous", min_length=1, max_length=200)

    @field_validator("message", "session_id", "user_id")
    @classmethod
    def strip_text(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


def utc_now():
    return datetime.now(timezone.utc)


def build_context_prompt(session_id: str, user_id: str, user_message: str):
    db = get_database()
    if db is None:
        raise RuntimeError("Database is unavailable")

    recent_chats = list(
        db["chat_history"]
        .find({"session_id": session_id, "user_id": user_id})
        .sort("timestamp", -1)
        .limit(CONTEXT_INTERACTION_LIMIT)
    )
    recent_chats.reverse()

    transcript_parts = []
    feedback_parts = []

    for index, chat in enumerate(recent_chats, start=1):
        transcript_parts.append(
            f"Turn {index}\n"
            f"User said: {chat.get('user_message', '')}\n"
            f"TRACE replied: {chat.get('llama_response', '')}"
        )

        feedback = chat.get("feedback") or {}
        if feedback.get("submitted") is True:
            feedback_parts.append(
                f"Feedback for Turn {index}: rating {feedback.get('rating')}/4; "
                f"correctness {feedback.get('correctness')}; "
                f"length {feedback.get('length_type')}."
            )

    transcript = "\n\n".join(transcript_parts) or "No previous turns in this session."
    feedback_notes = "\n".join(feedback_parts) or "No submitted feedback yet."

    return f"""
You are TRACE.AI, a multi-turn chatbot powered by local LLaMA 3.

IMPORTANT MEMORY RULES:
1. Use only the conversation transcript below as session memory.
2. If asked about earlier messages, answer only from this transcript.
3. Do not invent prior topics or mix this session with another session.
4. If the transcript lacks an answer, say it is not in current session memory.
5. Answer directly and keep the explanation useful and concise.

IMPORTANT FEEDBACK RULES:
1. Treat submitted user feedback as a correction signal.
2. Improve precision after Partial or Incorrect feedback.
3. Be shorter after Lengthy, add detail after Short, and stay concise after To the Point.

CONVERSATION TRANSCRIPT (last {CONTEXT_INTERACTION_LIMIT} interactions maximum):
{transcript}

USER FEEDBACK HISTORY:
{feedback_notes}

CURRENT USER MESSAGE:
{user_message}

TRACE RESPONSE:
""".strip()


def session_http_error(error):
    if isinstance(error, SessionOwnershipError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    if isinstance(error, SessionEndedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database is unavailable",
    )


@router.post("/chat")
def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    with session_lifecycle(session_id):
        try:
            ensure_active_session(session_id, request.user_id)
            pending_feedback = get_pending_feedback(session_id, request.user_id)
        except (SessionOwnershipError, SessionEndedError, RuntimeError) as error:
            raise session_http_error(error) from error

        if pending_feedback:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "feedback_required",
                    "message": "Submit feedback for the previous response before sending another message.",
                    "interaction_id": str(pending_feedback["_id"]),
                },
            )

        request_start_time = utc_now()
        start_counter = time.perf_counter()
        try:
            final_prompt = build_context_prompt(session_id, request.user_id, request.message)
            ai_response = generate_response(final_prompt)
        except OllamaTimeoutError as error:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                                detail=str(error)) from error
        except OllamaServiceError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail=str(error)) from error

        response_end_time = utc_now()
        response_time_seconds = round(time.perf_counter() - start_counter, 3)
        topic_label = classify_topic(request.message, ai_response)
        chat_data = {
            "session_id": session_id, "user_id": request.user_id,
            "user_message": request.message, "llama_response": ai_response,
            "timestamp": request_start_time,
            "request_start_time": request_start_time,
            "response_end_time": response_end_time,
            "response_time_seconds": response_time_seconds,
            "response_time": response_time_seconds,
            "topic_label": topic_label,
            "feedback": {
                "rating": None, "correctness": None, "length_type": None,
                "submitted": False, "submitted_at": None,
            },
        }
        try:
            inserted_id = save_chat(chat_data)
            record_interaction(session_id, request.user_id, topic_label)
        except (RuntimeError, SessionNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="Interaction could not be stored") from error

        return {
            "interaction_id": str(inserted_id), "session_id": session_id,
            "user_id": request.user_id, "user_message": request.message,
            "llama_response": ai_response,
            "request_start_time": request_start_time.isoformat(),
            "response_end_time": response_end_time.isoformat(),
            "response_time_seconds": response_time_seconds,
            "response_time": response_time_seconds, "topic_label": topic_label,
        }
