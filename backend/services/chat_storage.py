from backend.database.database import get_database


def save_chat(chat_data):

    db = get_database()

    if db is None:
        raise RuntimeError("Database is unavailable")

    chats_collection = db["chat_history"]

    result = chats_collection.insert_one(chat_data)

    print("[OK] Chat saved to MongoDB")

    return result.inserted_id
