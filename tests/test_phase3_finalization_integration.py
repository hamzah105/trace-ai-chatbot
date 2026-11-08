"""FR22 HTTP contracts through the real ASGI app, without MongoDB or Ollama."""

import asyncio
import copy
import importlib
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from test_phase3_finalization import OWNER, SESSION, make_database


async def asgi_request(app, method, path, *, query=None, payload=None):
    """Exercise routing, validation, serialization and exception handling locally."""
    body = json.dumps(payload).encode() if payload is not None else b""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path,
        "raw_path": path.encode(), "root_path": "",
        "query_string": urlencode(query or {}).encode(),
        "headers": [(b"content-type", b"application/json")],
        "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 12345),
    }
    events = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(event):
        events.append(event)

    await app(scope, receive, send)
    status = next(event["status"] for event in events if event["type"] == "http.response.start")
    response_body = b"".join(event.get("body", b"") for event in events
                             if event["type"] == "http.response.body")
    return status, json.loads(response_body)


class FinalizationHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep startup discovery and MongoDB connection outside these synthetic HTTP tests.
        with patch("backend.services.oomp_local.load_local_connection", return_value={"configured":False}), patch("backend.database.database.connect_db"):
            cls.app = importlib.import_module("backend.app").app

    def setUp(self):
        self.db, self.sessions, self.chats = make_database((True,) * 5 + (False,))
        for target in (
            "backend.services.session_service.get_database",
            "backend.analytics.finalization.get_database",
            "backend.routes.feedback.get_database",
        ):
            replacement = patch(target, side_effect=lambda: self.db)
            replacement.start()
            self.addCleanup(replacement.stop)

    def request(self, method, path, **kwargs):
        return asyncio.run(asgi_request(self.app, method, path, **kwargs))

    def owned_get(self, suffix="", *, owner=OWNER):
        return self.request("GET", f"/analytics/session/{SESSION}{suffix}",
                            query={"user_id": owner})

    def end(self, *, owner=OWNER, session_id=SESSION):
        return self.request("POST", f"/sessions/{session_id}/end", payload={"user_id": owner})

    def feedback(self, *, include_ids=True):
        payload = {
            "interaction_id": str(self.chats.rows[-1]["_id"]), "rating": 3,
            "correctness": "Partial", "length_type": "To the Point",
        }
        if include_ids:
            payload.update(user_id=OWNER, session_id=SESSION)
        return self.request("POST", "/feedback", payload=payload)

    def test_openapi_preserves_routes_and_requires_owner_for_session_detail(self):
        status, schema = self.request("GET", "/openapi.json")
        self.assertEqual(status, 200)
        expected = {
            "/register": "post", "/login": "post", "/chat": "post", "/feedback": "post",
            "/auth/google/login": "get", "/auth/google/callback": "get",
            "/sessions/create": "post", "/sessions/user/{user_id}": "get",
            "/sessions/{session_id}": "get", "/sessions/{session_id}/messages": "get",
            "/sessions/{session_id}/end": "post",
        }
        for suffix in ("", "/metrics", "/tables", "/charts", "/dashboard"):
            expected[f"/analytics/session/{{session_id}}{suffix}"] = "get"
        for path, method in expected.items():
            with self.subTest(path=path):
                self.assertIn(method, schema["paths"][path])
        parameters = schema["paths"]["/sessions/{session_id}"]["get"]["parameters"]
        self.assertTrue(next(item for item in parameters if item["name"] == "user_id")["required"])
        self.assertEqual(self.request("GET", f"/sessions/{SESSION}")[0], 422)
        self.assertEqual(self.request("POST", f"/sessions/{SESSION}/end", payload={})[0], 422)

    def test_pending_complete_finalize_read_only_and_repeat_end_full_flow(self):
        status, before_dashboard = self.owned_get("/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(before_dashboard["overview"]["total_interactions"], 6)
        self.assertEqual(before_dashboard["overview"]["feedback_submitted_count"], 5)
        self.assertFalse(before_dashboard["finalization"]["is_finalized"])
        before = copy.deepcopy((self.sessions.rows, self.chats.rows))
        status, blocked = self.end()
        self.assertEqual(status, 409)
        self.assertEqual(blocked["detail"]["code"], "feedback_required")
        self.assertEqual(blocked["detail"]["pending_feedback_count"], 1)
        self.assertEqual(blocked["detail"]["interaction_id"], str(self.chats.rows[-1]["_id"]))
        self.assertEqual((self.sessions.rows, self.chats.rows), before)

        self.assertEqual(self.feedback()[0], 200)
        completed_history = copy.deepcopy(self.chats.rows)
        status, ended = self.end()
        self.assertEqual(status, 200)
        self.assertTrue(ended["success"])
        self.assertEqual(ended["session"]["status"], "ended")
        stored = copy.deepcopy(self.sessions.rows[0])
        snapshot = stored["final_analytics"]
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["interaction_count"], 6)
        self.assertEqual(stored["ended_at"], snapshot["finalized_at"])
        self.assertEqual(ended["finalization"], {
            "is_finalized": True, "analytics_version": 1,
            "finalized_at": snapshot["finalized_at"].isoformat(),
        })
        self.assertEqual(self.chats.rows, completed_history)

        writes = self.sessions.writes, self.chats.writes
        for suffix in ("", "/metrics", "/tables", "/charts", "/dashboard"):
            with self.subTest(suffix=suffix):
                status, data = self.owned_get(suffix)
                self.assertEqual(status, 200)
                self.assertTrue(data["finalization"]["is_finalized"])
                if suffix in ("/metrics", "/dashboard"):
                    self.assertEqual(data["metrics"], snapshot["metrics"])
                if suffix == "/dashboard":
                    self.assertEqual(data["overview"], snapshot["overview"])
                    self.assertEqual(len(data["charts"]), 7)
                    self.assertEqual(len(data["tables"]), 6)
                    self.assertEqual(len(data["overview"]), 8)
                self.assertNotIn("never-public", json.dumps(data))
        self.assertEqual((self.sessions.writes, self.chats.writes), writes)
        status, history = self.request("GET", f"/sessions/{SESSION}/messages",
                                       query={"user_id": OWNER})
        self.assertEqual(status, 200)
        self.assertEqual(history["status"], "ended")
        self.assertEqual(history["message_count"], 6)
        self.assertFalse(history["pending_feedback"])
        self.assertIsNone(history["pending_interaction_id"])
        self.assertEqual(self.end(), (200, ended))
        self.assertEqual(self.sessions.rows[0], stored)
        self.assertEqual((self.sessions.writes, self.chats.writes), writes)

        with patch("backend.routes.chat.generate_response") as generate, \
                patch("backend.routes.chat.save_chat") as save:
            status, response = self.request("POST", "/chat", payload={
                "session_id": SESSION, "user_id": OWNER, "message": "One more message",
            })
            self.assertEqual(status, 409)
            self.assertIn("ended", response["detail"].lower())
            generate.assert_not_called()
            save.assert_not_called()
        self.assertEqual(self.feedback(include_ids=False)[0], 409)
        self.assertEqual(self.chats.rows, completed_history)
        self.assertEqual((self.sessions.writes, self.chats.writes), writes)

    def test_final_snapshot_is_not_exposed_to_foreign_or_missing_owner(self):
        self.chats.rows[-1]["feedback"]["submitted"] = True
        self.assertEqual(self.end()[0], 200)
        writes = self.sessions.writes, self.chats.writes
        self.assertEqual(self.end(owner="foreign-owner")[0], 403)
        for path in (f"/sessions/{SESSION}", f"/sessions/{SESSION}/messages"):
            self.assertEqual(self.request("GET", path, query={"user_id": "foreign-owner"})[0], 403)
            self.assertEqual(self.request("GET", path)[0], 422)
        for suffix in ("", "/metrics", "/tables", "/charts", "/dashboard"):
            self.assertEqual(self.owned_get(suffix, owner="foreign-owner")[0], 403)
        status, owned = self.request("GET", f"/sessions/{SESSION}", query={"user_id": OWNER})
        self.assertEqual(status, 200)
        self.assertNotIn("never-public", json.dumps(owned))
        self.assertEqual((self.sessions.writes, self.chats.writes), writes)

    def test_missing_and_unavailable_database_have_safe_http_errors(self):
        self.assertEqual(self.end(session_id="missing-session")[0], 404)
        self.db = None
        for suffix in ("", "/metrics", "/tables", "/charts", "/dashboard"):
            status, data = self.owned_get(suffix)
            self.assertEqual(status, 503)
            self.assertEqual(data["detail"], "Database is unavailable")
        self.assertEqual(self.end()[0], 503)
        self.assertEqual(self.feedback()[0], 503)

    def test_computation_and_write_failure_never_claim_finalization(self):
        self.chats.rows[-1]["feedback"]["submitted"] = True
        with patch("backend.analytics.finalization.compute_session_metrics",
                   side_effect=ValueError("sensitive internal computation detail")):
            status, data = self.end()
        self.assertEqual(status, 500)
        self.assertNotIn("sensitive", json.dumps(data))
        self.assertEqual(self.sessions.rows[0]["status"], "active")
        self.assertNotIn("final_analytics", self.sessions.rows[0])
        self.sessions.fail_update = True
        self.assertEqual(self.end()[0], 503)
        self.assertEqual(self.sessions.rows[0]["status"], "active")
        self.assertNotIn("final_analytics", self.sessions.rows[0])
        self.assertEqual(self.sessions.writes, 0)

    def test_empty_finalization_keeps_valid_na_metrics_and_readable_dashboard(self):
        self.db, self.sessions, self.chats = make_database(())
        status, ended = self.end()
        self.assertEqual(status, 200)
        self.assertEqual(ended["session"]["final_analytics"]["interaction_count"], 0)
        status, dashboard = self.owned_get("/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(dashboard["overview"]["total_interactions"], 0)
        for field in ("weighted_accuracy_percentage", "strict_correct_percentage",
                      "average_rating", "average_response_time_seconds"):
            self.assertIsNone(dashboard["overview"][field])
        self.assertEqual(dashboard["metrics"]["accuracy_per_reply"], [])
        self.assertEqual(dashboard["metrics"]["response_time"]["count"], 0)
        self.assertEqual(dashboard["metrics"]["correctness"]["correct_count"], 0)
        self.assertTrue(all(row["count"] == 0 for row in
                            dashboard["metrics"]["length_distribution"].values()))

    def test_legacy_ended_history_stays_read_only_without_snapshot_backfill(self):
        self.db, self.sessions, self.chats = make_database((False,), status="ended")
        original = copy.deepcopy((self.sessions.rows, self.chats.rows))
        for suffix in ("", "/metrics", "/tables", "/charts", "/dashboard"):
            status, data = self.owned_get(suffix)
            self.assertEqual(status, 200)
            self.assertFalse(data["finalization"]["is_finalized"])
        status, ended = self.end()
        self.assertEqual(status, 200)
        self.assertFalse(ended["finalization"]["is_finalized"])
        self.assertNotIn("final_analytics", ended["session"])
        self.assertEqual(self.feedback()[0], 409)
        self.assertEqual((self.sessions.rows, self.chats.rows), original)
        self.assertEqual((self.sessions.writes, self.chats.writes), (0, 0))


if __name__ == "__main__":
    unittest.main()
