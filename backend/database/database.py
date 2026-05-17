from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

client = None
db = None


def connect_db():
    global client, db

    try:
        client = MongoClient(MONGO_URI)

        client.admin.command("ping")

        db = client["trace_ai"]

        print("✔️MongoDB Connected Successfully!")

        return db

    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}")

        return None


def get_database():
    return db