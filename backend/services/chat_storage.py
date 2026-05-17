from backend.database.database import get_database


def save_chat(chat_data):

    db = get_database()

    if db is None:
        print("❌ Database not connected")
        return None

    chats_collection = db["chat_history"]

    result = chats_collection.insert_one(chat_data)

    print("✅ Chat saved to MongoDB")

    return result.inserted_id