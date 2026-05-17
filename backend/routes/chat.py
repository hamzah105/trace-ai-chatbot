from fastapi import APIRouter
from pydantic import BaseModel

from backend.services.ollama_service import generate_response
from backend.services.chat_storage import save_chat
from backend.database.database import get_database

import uuid
import time
from datetime import datetime


router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = None


def build_context_prompt(session_id: str, user_message: str):
    db = get_database()
    chats = db["chat_history"]

    recent_chats = list(
        chats.find(
            {"session_id": session_id}
        )
        .sort("timestamp", -1)
        .limit(8)
    )

    recent_chats.reverse()

    transcript = ""

    for index, chat in enumerate(recent_chats, start=1):
        transcript += f"""
Turn {index}
User said: {chat.get("user_message", "")}
TRACE replied: {chat.get("llama_response", "")}
"""

    prompt = f"""
You are TRACE.AI, a multi-turn chatbot.

IMPORTANT RULES:
1. Use the conversation transcript below as your memory.
2. If the user asks what they previously asked, what you previously suggested, or asks you to rewind, answer ONLY from the transcript.
3. Do not invent previous topics.
4. If the transcript does not contain the answer, say you cannot find it in the current session memory.
5. Keep responses concise and useful.

CONVERSATION TRANSCRIPT:
{transcript}

CURRENT USER MESSAGE:
{user_message}

TRACE RESPONSE:
"""

    return prompt


@router.post("/chat")
def chat(request: ChatRequest):

    start_time = time.time()

    session_id = (
        request.session_id
        if request.session_id
        else str(uuid.uuid4())
    )

    final_prompt = build_context_prompt(
        session_id,
        request.message
    )

    ai_response = generate_response(final_prompt)

    response_time = round(
        time.time() - start_time,
        2
    )

    chat_data = {
        "session_id": session_id,
        "user_message": request.message,
        "llama_response": ai_response,
        "timestamp": datetime.now(),
        "response_time": response_time,
        "feedback": None
    }

    inserted_id = save_chat(chat_data)

    return {
        "interaction_id": str(inserted_id),
        "session_id": session_id,
        "user_message": request.message,
        "llama_response": ai_response,
        "response_time": response_time
    }