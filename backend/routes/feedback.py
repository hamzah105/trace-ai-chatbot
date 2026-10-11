from datetime import datetime, timezone
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.database.database import get_database
from backend.services.session_lifecycle import session_lifecycle
from backend.services.session_service import (
    SessionNotFoundError, SessionOwnershipError, get_session, touch_session,
)
from pymongo.errors import PyMongoError


router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    interaction_id: str = Field(min_length=1, max_length=100)
    rating: int = Field(ge=1, le=4)
    correctness: Literal["Correct", "Partial", "Incorrect"]
    length_type: Literal["Short", "To the Point", "Lengthy"]
    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)


@router.post("/feedback")
def submit_feedback(request: FeedbackRequest):
    if not ObjectId.is_valid(request.interaction_id):
        raise HTTPException(status_code=400, detail="Invalid interaction ID")

    db = get_database()
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )

    chats = db["chat_history"]
    interaction_id = ObjectId(request.interaction_id)
    try:
        interaction = chats.find_one({"_id": interaction_id})
    except PyMongoError as error:
        raise HTTPException(status_code=503, detail="Database is unavailable") from error
    if not interaction:
        raise HTTPException(status_code=404, detail="Chat interaction not found")

    if request.user_id and interaction.get("user_id") != request.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Feedback does not belong to this user",
        )
    if request.session_id and interaction.get("session_id") != request.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Feedback does not belong to this session",
        )
    interaction_session_id = interaction.get("session_id")
    interaction_user_id = interaction.get("user_id")
    if not interaction_session_id or not interaction_user_id:
        # Orphaned Phase 1 records cannot be tied to an active owned session;
        # accepting feedback would make final analytics impossible to protect.
        raise HTTPException(status_code=404, detail="Chat session not found")

    with session_lifecycle(interaction_session_id):
        try:
            current = chats.find_one({"_id": interaction_id})
            if not current:
                raise HTTPException(status_code=404, detail="Chat interaction not found")
            if current.get("session_id") != interaction_session_id or current.get("user_id") != interaction_user_id:
                raise HTTPException(status_code=409, detail="Interaction changed during feedback submission")
            session = get_session(interaction_session_id, interaction_user_id)
            if session.get("status") != "active":
                raise HTTPException(status_code=409, detail="Session has ended. Feedback cannot be changed.")
            if (current.get("feedback") or {}).get("submitted") is True:
                raise HTTPException(status_code=409, detail="Feedback was already submitted for this response")

            submitted_at = datetime.now(timezone.utc)
            result = chats.update_one(
                {"_id": interaction_id, "session_id": interaction_session_id,
                 "user_id": interaction_user_id, "feedback.submitted": {"$ne": True}},
                {"$set": {"feedback": {
                    "rating": request.rating, "correctness": request.correctness,
                    "length_type": request.length_type, "submitted": True,
                    "submitted_at": submitted_at,
                }}},
            )
            if result.modified_count == 0:
                raise HTTPException(status_code=409, detail="Feedback could not be saved")
            touch_session(interaction_session_id, interaction_user_id)
        except SessionOwnershipError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (PyMongoError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail="Database is unavailable") from error

    return {"success": True, "message": "Feedback submitted successfully",
            "interaction_id": request.interaction_id,
            "submitted_at": submitted_at.isoformat()}
