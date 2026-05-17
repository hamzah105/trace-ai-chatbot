from fastapi import FastAPI
from backend.routes.chat import router as chat_router
from backend.database.database import connect_db

app = FastAPI(
    title="TRACE AI Chatbot",
    description="Multi-Turn LLaMA3 Chatbot",
    version="1.0"
)

connect_db()

app.include_router(chat_router)


@app.get("/")
def home():
    return {
        "message": "TRACE Backend Running Successfully"
    }