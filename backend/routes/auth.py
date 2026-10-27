import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

import bcrypt
import requests
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from backend.database.database import get_database


router = APIRouter(tags=["authentication"])
oauth_logger = logging.getLogger("uvicorn.error")

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
OAUTH_STATE_COOKIE = "trace_oauth_state"
OAUTH_LOGIN_COOKIE = "trace_oauth_login"
OAUTH_STATE_MAX_AGE_SECONDS = 600
OAUTH_LOGIN_MAX_AGE_SECONDS = 300


def utc_now():
    return datetime.now(timezone.utc)


def normalize_email(email: str):
    return email.strip().casefold()


def validate_email(value: str):
    value = normalize_email(value)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Enter a valid email address")
    return value


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator("email")
    @classmethod
    def clean_email(cls, value):
        return validate_email(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value):
        return validate_email(value)


def database_or_503():
    db = get_database()
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )
    return db


def find_user_by_email(users, email: str):
    normalized = normalize_email(email)
    user = users.find_one({"email": normalized})
    if user:
        return user
    # Phase 1 may contain mixed-case email values. Keep those profiles usable.
    return users.find_one({"email": {"$regex": f"^{re.escape(normalized)}$", "$options": "i"}})


def password_bytes(password: str):
    # bcrypt accepts at most 72 bytes. The API already limits character count.
    return password.encode("utf-8")[:72]


def hash_password(password: str):
    return bcrypt.hashpw(password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored_password: str):
    if stored_password.startswith("$2"):
        try:
            return bcrypt.checkpw(
                password_bytes(password),
                stored_password.encode("utf-8"),
            )
        except ValueError:
            return False
    # Backward compatibility for already-marked Phase 1 demo accounts.
    return hmac.compare_digest(password, stored_password)


def serialize_user(user):
    return {
        "user_id": str(user["_id"]),
        "name": user.get("name", "TRACE User"),
        "email": user.get("email", ""),
        "auth_provider": user.get("auth_provider", "local"),
        "profile_picture": user.get("picture", ""),
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
    }


def profile_response(user, message: str):
    profile = serialize_user(user)
    return {
        "success": True,
        "message": message,
        "name": profile["name"],
        "user_id": profile["user_id"],
        "user": profile,
    }


@router.post("/register")
def register(request: RegisterRequest):
    users = database_or_503()["users"]
    if find_user_by_email(users, request.email):
        return {"success": False, "message": "User already exists"}

    now = utc_now()
    document = {
        "name": request.name,
        "email": request.email,
        "password": hash_password(request.password),
        "auth_provider": "local",
        "created_at": now,
        "last_login": None,
    }
    try:
        result = users.insert_one(document)
    except DuplicateKeyError:
        return {"success": False, "message": "User already exists"}

    document["_id"] = result.inserted_id
    return profile_response(document, "Registration successful")


@router.post("/login")
def login(request: LoginRequest, http_request: Request = None):
    users = database_or_503()["users"]
    user = find_user_by_email(users, request.email)

    if not user or not verify_password(request.password, user.get("password", "")):
        return {"success": False, "message": "Invalid credentials"}

    now = utc_now()
    update = {
        "email": normalize_email(user.get("email", request.email)),
        "auth_provider": "local",
        "created_at": user.get("created_at", now),
        "last_login": now,
    }
    if not user.get("password", "").startswith("$2"):
        update["password"] = hash_password(request.password)

    users.update_one({"_id": user["_id"]}, {"$set": update})
    user.update(update)
    from backend.services.oomp_security import attach_owner_login
    return attach_owner_login(profile_response(user, "Login successful"), str(user["_id"]), request=http_request)


@router.get("/users/{user_id}")
def get_user_profile(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")
    user = database_or_503()["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User profile not found")
    return {"success": True, "user": serialize_user(user)}


def google_config(request: Request):
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI") or str(
        request.url_for("google_callback")
    )
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        "state_secret": os.getenv("GOOGLE_OAUTH_STATE_SECRET", "").strip(),
        "redirect_uri": redirect_uri,
    }


def state_fingerprint(value: str | None):
    if not value:
        return "missing"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def request_host(request: Request):
    return request.url.hostname or "unknown"


def redirect_host(config: dict):
    return urlsplit(config["redirect_uri"]).hostname or "unknown"


def encode_signed_payload(payload: dict, secret: str):
    payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{encoded.decode('ascii')}.{encoded_signature.decode('ascii')}"


def decode_signed_payload(value: str, secret: str, max_age_seconds: int):
    try:
        if not secret:
            return None
        encoded, supplied_signature = value.split(".", 1)
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        age = int(time.time()) - int(payload["issued_at"])
        if not 0 <= age <= max_age_seconds or not payload.get("nonce"):
            return None
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def encode_oauth_state(secret: str):
    return encode_signed_payload(
        {
            "purpose": "google_oauth_state",
            "issued_at": int(time.time()),
            "nonce": secrets.token_urlsafe(18),
        },
        secret,
    )


def validate_oauth_state(
    state_value: str,
    secret: str,
    max_age_seconds: int = OAUTH_STATE_MAX_AGE_SECONDS,
):
    payload = decode_signed_payload(state_value, secret, max_age_seconds)
    return bool(payload and payload.get("purpose") == "google_oauth_state")


def encode_oauth_login_ticket(user_id: str, secret: str):
    return encode_signed_payload(
        {
            "purpose": "google_oauth_login",
            "issued_at": int(time.time()),
            "nonce": secrets.token_urlsafe(18),
            "user_id": user_id,
        },
        secret,
    )


def decode_oauth_login_ticket(ticket: str, secret: str):
    payload = decode_signed_payload(ticket, secret, OAUTH_LOGIN_MAX_AGE_SECONDS)
    if not payload or payload.get("purpose") != "google_oauth_login":
        return None
    user_id = payload.get("user_id", "")
    return user_id if ObjectId.is_valid(user_id) else None


def google_config_missing(config: dict):
    return [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", config["client_id"]),
            ("GOOGLE_CLIENT_SECRET", config["client_secret"]),
            ("GOOGLE_REDIRECT_URI", config["redirect_uri"]),
            ("GOOGLE_OAUTH_STATE_SECRET", config["state_secret"]),
        )
        if not value
    ]


@router.get("/auth/google/status")
def google_status(request: Request):
    config = google_config(request)
    missing = google_config_missing(config)
    return {
        "enabled": not missing,
        "redirect_uri": config["redirect_uri"],
        "message": (
            "Google OAuth is ready"
            if not missing
            else "Google OAuth is not configured; local login is still available"
        ),
    }


@router.get("/auth/google/login")
def google_login(request: Request):
    config = google_config(request)
    missing = google_config_missing(config)
    if missing:
        oauth_logger.warning(
            "Google OAuth start rejected: configuration missing=%s",
            ",".join(missing),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured. Add the required GOOGLE_* environment variables or use local login.",
        )

    configured_host = redirect_host(config)
    current_host = request_host(request)
    if current_host.casefold() != configured_host.casefold():
        redirect_parts = urlsplit(config["redirect_uri"])
        canonical_login_url = (
            f"{redirect_parts.scheme}://{redirect_parts.netloc}/auth/google/login"
        )
        oauth_logger.info(
            "Google OAuth start canonicalized: request_host=%s redirect_host=%s",
            current_host,
            configured_host,
        )
        return RedirectResponse(canonical_login_url)

    state_value = encode_oauth_state(config["state_secret"])
    oauth_logger.info(
        "Google OAuth state generated: fingerprint=%s request_host=%s redirect_host=%s state_secret_configured=%s",
        state_fingerprint(state_value),
        current_host,
        configured_host,
        bool(config["state_secret"]),
    )
    query = urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": "openid email profile",
        "state": state_value,
        "prompt": "select_account",
    })
    response = RedirectResponse(f"{GOOGLE_AUTHORIZE_URL}?{query}")
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state_value,
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/auth/google",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def oauth_result_redirect(url: str):
    response = RedirectResponse(url)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/auth/google")
    response.delete_cookie(OAUTH_LOGIN_COOKIE, path="/auth/google")
    response.headers["Cache-Control"] = "no-store"
    return response


def upsert_google_user(users, google_user: dict):
    email = normalize_email(google_user["email"])
    google_sub = str(google_user["sub"])
    by_sub = users.find_one({"google_sub": google_sub})
    by_email = find_user_by_email(users, email)

    if by_sub and by_email and by_sub["_id"] != by_email["_id"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Google identity conflicts with an existing account",
        )
    if by_email and by_email.get("google_sub") not in (None, "", google_sub):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already linked to a different Google identity",
        )

    user = by_sub or by_email
    now = utc_now()
    update = {
        "name": google_user.get("name") or email.split("@", 1)[0],
        "email": email,
        "auth_provider": "google",
        "google_sub": google_sub,
        "last_login": now,
    }
    if google_user.get("picture"):
        update["picture"] = google_user["picture"]

    if user:
        update["created_at"] = user.get("created_at", now)
        users.update_one({"_id": user["_id"]}, {"$set": update})
        user.update(update)
        oauth_logger.info("Google OAuth profile retrieved and updated")
        return user

    user = {**update, "created_at": now}
    try:
        result = users.insert_one(user)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this Google identity already exists",
        ) from error
    user["_id"] = result.inserted_id
    oauth_logger.info("Google OAuth profile created")
    return user


@router.get("/auth/google/callback", name="google_callback")
def google_callback(
    request: Request,
    code: str | None = Query(default=None),
    state_value: str | None = Query(default=None, alias="state"),
    oauth_error: str | None = Query(default=None, alias="error"),
):
    if oauth_error:
        oauth_logger.warning(
            "Google OAuth provider returned an error: error=%s",
            oauth_error,
        )
        return oauth_result_redirect(f"/login.html?{urlencode({'oauth_error': oauth_error})}")

    config = google_config(request)
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    state_matches_cookie = bool(
        state_value
        and state_cookie
        and hmac.compare_digest(state_value, state_cookie)
    )
    signed_state_valid = bool(
        state_value
        and config["state_secret"]
        and validate_oauth_state(state_value, config["state_secret"])
    )
    missing = google_config_missing(config)
    oauth_logger.info(
        "Google OAuth callback received: code_exists=%s returned_state_exists=%s state_cookie_exists=%s state_match=%s signed_state_valid=%s state_fingerprint=%s request_host=%s redirect_host=%s config_ready=%s",
        bool(code),
        bool(state_value),
        bool(state_cookie),
        state_matches_cookie,
        signed_state_valid,
        state_fingerprint(state_value),
        request_host(request),
        redirect_host(config),
        not missing,
    )
    if not code or not state_matches_cookie or not signed_state_valid or missing:
        oauth_logger.warning("Google OAuth callback rejected during state validation")
        return oauth_result_redirect("/login.html?oauth_error=invalid_oauth_response")

    try:
        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": config["redirect_uri"],
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        oauth_logger.info("Google OAuth token exchange succeeded")
    except (requests.RequestException, KeyError, ValueError) as error:
        response_status = getattr(getattr(error, "response", None), "status_code", None)
        oauth_logger.warning(
            "Google OAuth token exchange failed: error_type=%s status=%s",
            type(error).__name__,
            response_status,
        )
        return oauth_result_redirect(
            "/login.html?oauth_error=google_token_exchange_failed"
        )

    try:
        user_response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        user_response.raise_for_status()
        google_user = user_response.json()
        oauth_logger.info(
            "Google OAuth userinfo fetch succeeded: sub_exists=%s email_exists=%s email_verified=%s",
            bool(google_user.get("sub")),
            bool(google_user.get("email")),
            google_user.get("email_verified") is True,
        )
    except (requests.RequestException, ValueError) as error:
        response_status = getattr(getattr(error, "response", None), "status_code", None)
        oauth_logger.warning(
            "Google OAuth userinfo fetch failed: error_type=%s status=%s",
            type(error).__name__,
            response_status,
        )
        return oauth_result_redirect(
            "/login.html?oauth_error=google_userinfo_failed"
        )

    if (
        not google_user.get("sub")
        or not google_user.get("email")
        or google_user.get("email_verified") is not True
    ):
        oauth_logger.warning(
            "Google OAuth userinfo rejected: sub_exists=%s email_exists=%s email_verified=%s",
            bool(google_user.get("sub")),
            bool(google_user.get("email")),
            google_user.get("email_verified") is True,
        )
        return oauth_result_redirect("/login.html?oauth_error=unverified_google_email")

    try:
        user = upsert_google_user(database_or_503()["users"], google_user)
    except HTTPException as error:
        oauth_logger.warning(
            "Google OAuth profile save failed: status=%s detail=%s",
            error.status_code,
            error.detail,
        )
        return oauth_result_redirect("/login.html?oauth_error=google_profile_failed")

    ticket = encode_oauth_login_ticket(str(user["_id"]), config["state_secret"])
    response = RedirectResponse("/login.html?oauth=success")
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/auth/google")
    response.set_cookie(
        OAUTH_LOGIN_COOKIE,
        ticket,
        max_age=OAUTH_LOGIN_MAX_AGE_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/auth/google",
    )
    response.headers["Cache-Control"] = "no-store"
    oauth_logger.info("Google OAuth callback completed; login handoff cookie issued")
    return response


@router.get("/auth/google/session")
def google_session(request: Request):
    config = google_config(request)
    ticket = request.cookies.get(OAUTH_LOGIN_COOKIE, "")
    user_id = decode_oauth_login_ticket(ticket, config["state_secret"])
    oauth_logger.info(
        "Google OAuth login handoff received: ticket_exists=%s ticket_valid=%s",
        bool(ticket),
        bool(user_id),
    )
    if not user_id:
        oauth_logger.warning("Google OAuth login handoff rejected: missing or expired ticket")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google login session is missing or expired",
        )

    user = database_or_503()["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        oauth_logger.warning("Google OAuth login handoff rejected: profile not found")
        raise HTTPException(status_code=404, detail="Google user profile not found")

    payload = jsonable_encoder({"success": True, "user": serialize_user(user)})
    response = JSONResponse(payload)
    response.delete_cookie(OAUTH_LOGIN_COOKIE, path="/auth/google")
    response.headers["Cache-Control"] = "no-store"
    oauth_logger.info("Google OAuth login handoff completed")
    from backend.services.oomp_security import attach_owner_login
    return attach_owner_login(payload, str(user["_id"]), response=response, request=request)


@router.post("/auth/oomp/logout")
def memory_logout(request: Request):
    from backend.services.oomp_security import logout_owner
    return logout_owner(request)
