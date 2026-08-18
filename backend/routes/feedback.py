from datetime import datetime, timezone
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.database.database import get_database
from backend.services.session_service import touch_session


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
    interaction = chats.find_one({"_id": interaction_id})
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
    if (interaction.get("feedback") or {}).get("submitted") is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback was already submitted for this response",
        )

    submitted_at = datetime.now(timezone.utc)
    result = chats.update_one(
        {
            "_id": interaction_id,
            "feedback.submitted": {"$ne": True},
        },
        {
            "$set": {
                "feedback": {
                    "rating": request.rating,
                    "correctness": request.correctness,
                    "length_type": request.length_type,
                    "submitted": True,
                    "submitted_at": submitted_at,
                }
            }
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback could not be saved",
        )

    interaction_user_id = interaction.get("user_id")
    interaction_session_id = interaction.get("session_id")
    if interaction_user_id and interaction_session_id:
        touch_session(interaction_session_id, interaction_user_id)

    return {
        "success": True,
        "message": "Feedback submitted successfully",
        "interaction_id": request.interaction_id,
        "submitted_at": submitted_at.isoformat(),
    }
