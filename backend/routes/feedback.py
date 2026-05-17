from fastapi import APIRouter
from pydantic import BaseModel
from bson import ObjectId

from backend.database.database import get_database


router = APIRouter()


class FeedbackRequest(BaseModel):
    interaction_id: str
    rating: int
    correctness: str
    length_type: str


@router.post("/feedback")
def submit_feedback(request: FeedbackRequest):

    db = get_database()
    chats = db["chat_history"]

    result = chats.update_one(
        {"_id": ObjectId(request.interaction_id)},
        {
            "$set": {
                "feedback": {
                    "rating": request.rating,
                    "correctness": request.correctness,
                    "length_type": request.length_type,
                    "submitted": True
                }
            }
        }
    )

    if result.modified_count == 0:
        return {
            "success": False,
            "message": "Feedback could not be saved"
        }

    return {
        "success": True,
        "message": "Feedback submitted successfully"
    }