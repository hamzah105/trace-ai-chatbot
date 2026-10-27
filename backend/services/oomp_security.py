"""Local owner credential for optional memory, without changing baseline auth."""
from __future__ import annotations
import ipaddress
import logging
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .oomp_config import get_configuration, ConfigurationError

COOKIE = "trace_memory_owner"
LOGGER = logging.getLogger("trace.oomp")


def _protected(path):
    return path == "/chat" or path == "/feedback" or any(
        path == prefix or path.startswith(prefix + "/") for prefix in ("/sessions", "/analytics", "/users"))


def _authorized(scope, config, *, credentials=True):
    headers = {}
    for key, value in scope.get("headers", ()):
        key = key.lower()
        if key in {b"host", b"origin", b"x-trace-memory-key", b"cookie"} and key in headers:
            return False
        headers[key] = value
    try:
        client = ipaddress.ip_address((scope.get("client") or ("", 0))[0])
        if not client.is_loopback:
            return False
    except ValueError:
        return False
    if headers.get(b"host", b"").decode("latin1") != config.origin.split("://", 1)[1]:
        return False
    if b"origin" in headers and headers[b"origin"].decode("latin1") != config.origin:
        return False
    if not credentials:
        return True
    key = headers.get(b"x-trace-memory-key", b"")
    if key:
        return secrets.compare_digest(key, config.owner_key.get_secret_value().encode("ascii"))
    try:
        cookies = SimpleCookie()
        cookies.load(headers.get(b"cookie", b"").decode("latin1"))
        ticket = cookies.get(COOKIE)
        from backend.routes.auth import decode_signed_payload
        payload = decode_signed_payload(ticket.value if ticket else "",
            config.owner_key.get_secret_value(), 8*3600)
        return bool(payload and payload.get("purpose") == "oomp-owner-v1"
                    and payload.get("owner_id") == config.owner_id)
    except Exception:
        return False


class MemoryOwnerMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if not _protected(scope["path"]):
            return await self.app(scope, receive, send)
        try:
            config = get_configuration()
        except ConfigurationError:
            response = JSONResponse(status_code=503, content={"detail": "Memory deployment configuration is invalid"})
            return await response(scope, receive, send)
        if config.mode == "off" or not _protected(scope["path"]):
            return await self.app(scope, receive, send)
        if not _authorized(scope, config):
            response = JSONResponse(status_code=403, content={"detail": "Verified local memory owner required"})
            return await response(scope, receive, send)
        scope.setdefault("state", {})["oomp_owner"] = config.owner_id
        # GET owner selection is checked before existing history/analytics routes run.
        owners = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="replace")).get("user_id", [])
        path = scope["path"]
        if path.startswith("/sessions/user/") or path.startswith("/users/"):
            owners.append(path.rsplit("/", 1)[1])
        if any(owner != config.owner_id for owner in owners):
            response = JSONResponse(status_code=403, content={"detail": "Memory owner mismatch"})
            return await response(scope, receive, send)
        await self.app(scope, receive, send)


async def require_memory_owner(request: Request):
    config = get_configuration()
    if config.mode == "off":
        return
    if getattr(request.state, "oomp_owner", None) != config.owner_id:
        raise HTTPException(status_code=403, detail="Verified local memory owner required")
    if request.method == "POST":
        body = await request.json()
        if isinstance(body, dict) and body.get("user_id") not in (None, config.owner_id):
            raise HTTPException(status_code=403, detail="Memory owner mismatch")


def verified_owner(request, user_id, config):
    return (config.mode != "off" and user_id == config.owner_id and request is not None
            and getattr(request.state, "oomp_owner", None) == config.owner_id)


def attach_owner_login(payload, user_id, response=None, request=None):
    config = get_configuration()
    if config.mode == "off":
        return response if response is not None else payload
    if user_id != config.owner_id:
        if response is None:
            response = JSONResponse(jsonable_encoder(payload))
        response.delete_cookie(COOKIE, path="/")
        response.delete_cookie("trace_memory_enabled", path="/")
        return response
    if request is None or not _authorized(request.scope, config, credentials=False):
        raise HTTPException(status_code=403, detail="Local owner login required")
    from backend.routes.auth import encode_signed_payload
    ticket = encode_signed_payload({"purpose": "oomp-owner-v1", "owner_id": user_id, "issued_at": int(time.time()), "nonce": secrets.token_urlsafe(18)},
                                   config.owner_key.get_secret_value())
    if response is None:
        response = JSONResponse(jsonable_encoder(payload))
    response.set_cookie(COOKIE, ticket, max_age=8*3600, httponly=True, secure=False, samesite="strict", path="/")
    response.set_cookie("trace_memory_enabled", "1", max_age=8*3600, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response

def logout_owner(request):
    config = get_configuration()
    if config.mode != "off" and not _authorized(request.scope, config, credentials=False):
        raise HTTPException(status_code=403, detail="Local owner logout required")
    response = JSONResponse({"success": True})
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie("trace_memory_enabled", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response
