from fastapi import APIRouter
from pydantic import BaseModel

from backend.database.database import get_database

router = APIRouter()


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(request: RegisterRequest):

    db = get_database()

    users = db["users"]

    existing_user = users.find_one({
        "email": request.email
    })

    if existing_user:
        return {
            "success": False,
            "message": "User already exists"
        }

    users.insert_one({
        "name": request.name,
        "email": request.email,
        "password": request.password
    })

    return {
        "success": True,
        "message": "Registration successful"
    }


@router.post("/login")
def login(request: LoginRequest):

    db = get_database()

    users = db["users"]

    user = users.find_one({
        "email": request.email,
        "password": request.password
    })

    if not user:
        return {
            "success": False,
            "message": "Invalid credentials"
        }

    return {
        "success": True,
        "message": "Login successful",
        "name": user["name"]
    }