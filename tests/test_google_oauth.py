import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from bson import ObjectId
from fastapi import HTTPException
import requests
from starlette.requests import Request

from backend.routes.auth import (
    LoginRequest,
    OAUTH_LOGIN_COOKIE,
    OAUTH_STATE_COOKIE,
    decode_oauth_login_ticket,
    encode_oauth_login_ticket,
    encode_oauth_state,
    google_callback,
    google_login,
    google_session,
    login,
    upsert_google_user,
)


TEST_OAUTH_ENV = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "GOOGLE_REDIRECT_URI": "http://127.0.0.1:8000/auth/google/callback",
    "GOOGLE_OAUTH_STATE_SECRET": "test-state-secret",
}


def make_request(path, cookies=None):
    cookie_header = "; ".join(
        f"{name}={value}" for name, value in (cookies or {}).items()
    )
    headers = [(b"host", b"127.0.0.1:8000")]
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("ascii")))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    })


class OAuthLoginTicketTests(unittest.TestCase):
    def test_ticket_is_signed_and_rejects_tampering(self):
        user_id = str(ObjectId())
        ticket = encode_oauth_login_ticket(user_id, "ticket-secret")

        self.assertEqual(
            decode_oauth_login_ticket(ticket, "ticket-secret"),
            user_id,
        )
        self.assertIsNone(
            decode_oauth_login_ticket(ticket + "tampered", "ticket-secret")
        )


class GoogleLoginStartTests(unittest.TestCase):
    def test_start_route_redirects_to_google_with_state(self):
        request = make_request("/auth/google/login")

        with self.assertLogs("uvicorn.error", level="INFO") as logs:
            with patch.dict(os.environ, TEST_OAUTH_ENV, clear=False):
                response = google_login(request)

        destination = urlparse(response.headers["location"])
        query = parse_qs(destination.query)
        self.assertEqual(destination.netloc, "accounts.google.com")
        self.assertEqual(query["client_id"], ["test-client-id"])
        self.assertEqual(
            query["redirect_uri"],
            ["http://127.0.0.1:8000/auth/google/callback"],
        )
        self.assertEqual(query["scope"], ["openid email profile"])
        self.assertTrue(query["state"][0])
        self.assertIn(OAUTH_STATE_COOKIE, response.headers["set-cookie"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertTrue(any("state generated" in item for item in logs.output))
        self.assertFalse(any(query["state"][0] in item for item in logs.output))

    def test_start_route_fails_clearly_when_configuration_is_missing(self):
        request = make_request("/auth/google/login")
        empty_oauth_env = {
            **TEST_OAUTH_ENV,
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "GOOGLE_OAUTH_STATE_SECRET": "",
        }

        with patch.dict(os.environ, empty_oauth_env, clear=False):
            with self.assertRaises(HTTPException) as raised:
                google_login(request)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("not configured", raised.exception.detail)


class GoogleProfileTests(unittest.TestCase):
    def setUp(self):
        self.google_profile = {
            "sub": "google-sub-123",
            "name": "Google User",
            "email": "Google.User@gmail.com",
            "email_verified": True,
            "picture": "https://example.test/avatar.png",
        }

    def test_first_google_login_creates_complete_profile(self):
        users = MagicMock()
        users.find_one.side_effect = [None, None, None]
        users.insert_one.return_value.inserted_id = ObjectId()

        user = upsert_google_user(users, self.google_profile)

        self.assertEqual(user["email"], "google.user@gmail.com")
        self.assertEqual(user["auth_provider"], "google")
        self.assertEqual(user["google_sub"], "google-sub-123")
        self.assertEqual(user["picture"], "https://example.test/avatar.png")
        self.assertIn("created_at", user)
        self.assertIn("last_login", user)
        users.insert_one.assert_called_once()

    def test_repeat_google_login_reuses_same_profile(self):
        existing_id = ObjectId()
        existing = {
            "_id": existing_id,
            "name": "Old Name",
            "email": "google.user@gmail.com",
            "auth_provider": "google",
            "google_sub": "google-sub-123",
        }
        users = MagicMock()
        users.find_one.side_effect = [existing, existing]

        user = upsert_google_user(users, self.google_profile)

        self.assertEqual(user["_id"], existing_id)
        users.update_one.assert_called_once()
        users.insert_one.assert_not_called()

    def test_google_login_links_existing_local_email_without_removing_password(self):
        password = "phase-1-password"
        existing = {
            "_id": ObjectId(),
            "name": "Local User",
            "email": "google.user@gmail.com",
            "password": password,
            "auth_provider": "local",
        }
        users = MagicMock()
        users.find_one.side_effect = [None, existing]

        user = upsert_google_user(users, self.google_profile)

        self.assertEqual(user["password"], password)
        self.assertEqual(user["auth_provider"], "google")
        self.assertEqual(user["google_sub"], "google-sub-123")

    def test_google_login_rejects_different_sub_for_linked_email(self):
        existing = {
            "_id": ObjectId(),
            "email": "google.user@gmail.com",
            "auth_provider": "google",
            "google_sub": "different-google-sub",
        }
        users = MagicMock()
        users.find_one.side_effect = [None, existing]

        with self.assertRaises(HTTPException) as raised:
            upsert_google_user(users, self.google_profile)

        self.assertEqual(raised.exception.status_code, 409)
        users.update_one.assert_not_called()
        users.insert_one.assert_not_called()

    @patch("backend.routes.auth.database_or_503")
    def test_linked_user_can_still_use_local_password_login(self, database_mock):
        user = {
            "_id": ObjectId(),
            "name": "Local User",
            "email": "user@example.com",
            "password": "phase-1-password",
            "auth_provider": "google",
            "google_sub": "google-sub-123",
        }
        users = MagicMock()
        users.find_one.return_value = user
        database_mock.return_value.__getitem__.return_value = users

        response = login(LoginRequest(
            email="user@example.com",
            password="phase-1-password",
        ))

        self.assertTrue(response["success"])
        self.assertEqual(response["user"]["auth_provider"], "local")
        self.assertEqual(user["google_sub"], "google-sub-123")


class GoogleCallbackTests(unittest.TestCase):
    @patch("backend.routes.auth.database_or_503")
    @patch("backend.routes.auth.requests.get")
    @patch("backend.routes.auth.requests.post")
    def test_callback_exchanges_code_and_sets_safe_login_ticket(
        self,
        post_mock,
        get_mock,
        database_mock,
    ):
        state = encode_oauth_state(TEST_OAUTH_ENV["GOOGLE_OAUTH_STATE_SECRET"])
        request = make_request(
            "/auth/google/callback",
            {OAUTH_STATE_COOKIE: state},
        )

        token_response = MagicMock()
        token_response.json.return_value = {"access_token": "access-token"}
        post_mock.return_value = token_response

        user_response = MagicMock()
        user_response.json.return_value = {
            "sub": "google-sub-123",
            "name": "Google User",
            "email": "google.user@gmail.com",
            "email_verified": True,
            "picture": "https://example.test/avatar.png",
        }
        get_mock.return_value = user_response

        users = MagicMock()
        users.find_one.side_effect = [None, None, None]
        users.insert_one.return_value.inserted_id = ObjectId()
        database_mock.return_value.__getitem__.return_value = users

        with patch.dict(os.environ, TEST_OAUTH_ENV, clear=False):
            response = google_callback(
                request,
                code="authorization-code",
                state_value=state,
                oauth_error=None,
            )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/login.html?oauth=success")
        cookies = response.headers.getlist("set-cookie")
        self.assertTrue(any(OAUTH_LOGIN_COOKIE in value for value in cookies))
        self.assertFalse(any("google.user@gmail.com" in value for value in cookies))
        post_mock.assert_called_once()
        get_mock.assert_called_once()

    @patch("backend.routes.auth.requests.get")
    @patch("backend.routes.auth.requests.post")
    def test_token_exchange_failure_has_specific_redirect_and_log(
        self,
        post_mock,
        get_mock,
    ):
        state = encode_oauth_state(TEST_OAUTH_ENV["GOOGLE_OAUTH_STATE_SECRET"])
        request = make_request(
            "/auth/google/callback",
            {OAUTH_STATE_COOKIE: state},
        )
        token_error = requests.HTTPError("token exchange rejected")
        token_error.response = MagicMock(status_code=400)
        post_mock.side_effect = token_error

        with self.assertLogs("uvicorn.error", level="INFO") as logs:
            with patch.dict(os.environ, TEST_OAUTH_ENV, clear=False):
                response = google_callback(
                    request,
                    code="authorization-code",
                    state_value=state,
                    oauth_error=None,
                )

        self.assertEqual(
            response.headers["location"],
            "/login.html?oauth_error=google_token_exchange_failed",
        )
        self.assertTrue(any("token exchange failed" in item for item in logs.output))
        get_mock.assert_not_called()

    @patch("backend.routes.auth.database_or_503")
    def test_session_endpoint_returns_safe_profile_and_clears_ticket(
        self,
        database_mock,
    ):
        user_id = ObjectId()
        ticket = encode_oauth_login_ticket(
            str(user_id),
            TEST_OAUTH_ENV["GOOGLE_OAUTH_STATE_SECRET"],
        )
        request = make_request(
            "/auth/google/session",
            {OAUTH_LOGIN_COOKIE: ticket},
        )
        now = datetime.now(timezone.utc)
        database_mock.return_value.__getitem__.return_value.find_one.return_value = {
            "_id": user_id,
            "name": "Google User",
            "email": "google.user@gmail.com",
            "auth_provider": "google",
            "google_sub": "google-sub-123",
            "picture": "https://example.test/avatar.png",
            "created_at": now,
            "last_login": now,
        }

        with patch.dict(os.environ, TEST_OAUTH_ENV, clear=False):
            response = google_session(request)

        payload = json.loads(response.body)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["user"]["auth_provider"], "google")
        self.assertEqual(
            payload["user"]["profile_picture"],
            "https://example.test/avatar.png",
        )
        self.assertEqual(payload["user"]["created_at"], now.isoformat())
        self.assertEqual(payload["user"]["last_login"], now.isoformat())
        self.assertIn("Max-Age=0", response.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()
