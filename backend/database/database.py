from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "trace_ai")

client = None
db = None


def connect_db():
    global client, db

    try:
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000
        )

        client.admin.command("ping")

        db = client[MONGO_DB_NAME]

        # Phase 2 indexes keep user identities and sessions independent while
        # preserving the existing Phase 1 collections and documents.
        db["users"].create_index("email", unique=True)
        db["users"].create_index("google_sub", unique=True, sparse=True)
        db["sessions"].create_index("session_id", unique=True)
        db["sessions"].create_index([("user_id", 1), ("updated_at", -1)])
        db["chat_history"].create_index(
            [("user_id", 1), ("session_id", 1), ("timestamp", -1)]
        )

        print("[OK] MongoDB Connected Successfully!")

        return db

    except Exception as e:
        print(f"[ERROR] MongoDB Connection Failed: {e}")

        client = None
        db = None

        return None


def get_database():
    return db
