"""FR19 route checks against the existing owned-session data service."""

import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import AutoReconnect

from backend.routes.analytics import session_analytics, session_metrics, session_tables


SESSION_ID = "session-a"
OWNER = "owner-a"
WHEN = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def _fixture(database, messages=None, documents=None):
    sessions, chats, cursor, users = (MagicMock() for _ in range(4))
    database.return_value.__getitem__.side_effect = {
        "sessions": sessions, "chat_history": chats, "users": users,
    }.__getitem__
    documents = documents if documents is not None else {
        SESSION_ID: {"_id": ObjectId(), "session_id": SESSION_ID, "user_id": OWNER,
                     "status": "ended", "message_count": 3,
                     "password_hash": "sensitive-password"}
    }
    sessions.find_one.side_effect = lambda query: documents.get(query["session_id"])
    chats.find.return_value = cursor
    cursor.sort.return_value = messages if messages is not None else [
        {
            "_id": ObjectId(), "session_id": SESSION_ID, "user_id": OWNER,
            "timestamp": WHEN + timedelta(minutes=index),
            "user_message": "Private prompt " + str(index),
            "llama_response": "Private response " + str(index),
            "topic_label": topic, "response_time_seconds": seconds,
            "feedback": {"submitted": True, "correctness": correctness,
                         "rating": rating, "length_type": length},
            "oauth_secret": "sensitive-token",
        }
        for index, topic, correctness, rating, length, seconds in (
            (2, "Healthcare AI", "Incorrect", 2, "Lengthy", 30),
            (0, "Machine Learning", "Correct", 4, "To the Point", 10),
            (1, "Machine Learning", "Partial", 3, "Short", 20),
        )
    ]
    return sessions, chats, cursor, users


class TablesRouteTests(unittest.TestCase):
    @patch("backend.services.session_service._database")
    def test_owned_reference_dataset_serializes_without_mutating_storage(self, database):
        sessions, chats, cursor, users = _fixture(database)
        stored_before = deepcopy(cursor.sort.return_value)

        result = session_tables(SESSION_ID, OWNER)

        self.assertTrue(result["success"])
        self.assertEqual(result["session"]["session_id"], SESSION_ID)
        self.assertEqual(result["session"]["status"], "ended")
        tables = result["tables"]
        self.assertEqual(len(tables), 6)
        self.assertEqual([row["topic_label"] for row in tables["topic_vs_accuracy"]["rows"]],
                         ["Healthcare AI", "Machine Learning"])
        self.assertEqual([row["accuracy_percentage"] for row in
                          tables["topic_vs_accuracy"]["rows"]], [0.0, 75.0])
        replies = tables["reply_correctness"]["rows"]
        self.assertEqual([row["interaction_number"] for row in replies], [1, 2, 3])
        self.assertEqual([row["accuracy_percentage"] for row in replies], [100.0, 50.0, 0.0])
        self.assertEqual([row["response_time_seconds"] for row in replies], [10.0, 20.0, 30.0])
        self.assertEqual([row["phase"] for row in tables["phase_wise_accuracy"]["rows"]],
                         ["Start", "Middle", "End"])
        self.assertEqual([row["seconds"] for row in
                          tables["response_time_summary"]["rows"]], [20.0, 10.0, 30.0, 20.0])
        self.assertEqual(tables["response_time_summary"]["valid_response_count"], 3)
        self.assertEqual([row["percentage"] for row in
                          tables["rating_distribution"]["rows"]], [0.0, 33.33, 33.33, 33.33])
        self.assertEqual([row["length_type"] for row in tables["length_preference"]["rows"]],
                         ["Short", "To the Point", "Lengthy"])
        payload = json.dumps(result, allow_nan=False)
        for secret in ("sensitive-password", "sensitive-token", "Private prompt", "Private response"):
            self.assertNotIn(secret, payload)
        self.assertEqual(cursor.sort.return_value, stored_before)
        sessions.find_one.assert_called_once_with({"session_id": SESSION_ID})
        chats.find.assert_called_once_with({"session_id": SESSION_ID, "user_id": OWNER})
        cursor.sort.assert_called_once_with("timestamp", 1)
        for collection in (sessions, chats, users):
            for method in ("update_one", "update_many", "insert_one", "insert_many",
                           "replace_one", "delete_one", "delete_many"):
                getattr(collection, method).assert_not_called()

    @patch("backend.routes.analytics.build_session_tables")
    @patch("backend.routes.analytics.compute_session_metrics")
    @patch("backend.services.session_service._database")
    def test_missing_and_wrong_owner_stop_before_analytics(self, database, compute, build):
        foreign = "foreign-session"
        sessions, chats, _, _ = _fixture(database, documents={
            foreign: {"session_id": foreign, "user_id": "owner-b"},
        })
        for session_id, expected in (("missing-session", 404), (foreign, 403)):
            with self.subTest(session_id=session_id):
                with self.assertRaises(HTTPException) as raised:
                    session_tables(session_id, OWNER)
                self.assertEqual(raised.exception.status_code, expected)
        self.assertEqual(sessions.find_one.call_count, 2)
        chats.find.assert_not_called()
        compute.assert_not_called()
        build.assert_not_called()

    @patch("backend.routes.analytics.build_session_tables")
    @patch("backend.routes.analytics.compute_session_metrics")
    @patch("backend.services.session_service._database", side_effect=RuntimeError("Database is unavailable"))
    def test_database_unavailable_returns_503(self, database, compute, build):
        with self.assertRaises(HTTPException) as raised:
            session_tables(SESSION_ID, OWNER)
        self.assertEqual((raised.exception.status_code, raised.exception.detail),
                         (503, "Database is unavailable"))
        compute.assert_not_called()
        build.assert_not_called()

    @patch("backend.services.session_service._database")
    def test_pymongo_error_is_sanitized(self, database):
        sessions, _, _, _ = _fixture(database)
        sessions.find_one.side_effect = AutoReconnect("connection string with secrets")
        with self.assertRaises(HTTPException) as raised:
            session_tables(SESSION_ID, OWNER)
        self.assertEqual((raised.exception.status_code, raised.exception.detail),
                         (503, "Database is unavailable"))

    @patch("backend.services.session_service._database")
    def test_empty_session_and_part1_part2_compatibility(self, database):
        session = {"session_id": SESSION_ID, "user_id": OWNER,
                   "status": "active", "message_count": 0}
        sessions, chats, _, _ = _fixture(database, messages=[], documents={SESSION_ID: session})

        tables = session_tables(SESSION_ID, OWNER)["tables"]
        self.assertEqual(tables["topic_vs_accuracy"]["rows"], [])
        self.assertEqual(tables["reply_correctness"]["rows"], [])
        self.assertEqual(tables["phase_wise_accuracy"]["rows"], [])
        self.assertEqual(tables["response_time_summary"]["valid_response_count"], 0)
        self.assertEqual([row["seconds"] for row in
                          tables["response_time_summary"]["rows"]], [None] * 4)
        self.assertEqual([row["count"] for row in tables["rating_distribution"]["rows"]],
                         [0, 0, 0, 0])
        self.assertEqual([row["percentage"] for row in
                          tables["length_preference"]["rows"]], [0.0, 0.0, 0.0])
        self.assertEqual(session_analytics(SESSION_ID, OWNER)["interaction_count"], 0)
        self.assertEqual(session_metrics(SESSION_ID, OWNER)["metrics"]["summary"]["total_interactions"], 0)
        self.assertEqual(sessions.find_one.call_count, 3)
        self.assertEqual(chats.find.call_count, 3)

    @patch("backend.services.session_service._database")
    def test_stale_feedback_stays_hidden_but_timing_remains(self, database):
        _, _, cursor, _ = _fixture(database)
        stale = cursor.sort.return_value[0]
        stale["feedback"]["submitted"] = False
        stale["feedback"]["correctness"] = "Correct"
        stale["feedback"]["rating"] = 4
        stale["feedback"]["length_type"] = "Short"
        stale.pop("response_time_seconds")
        stale["response_time"] = "30"

        rows = session_tables(SESSION_ID, OWNER)["tables"]["reply_correctness"]["rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]["response_time_seconds"], 30.0)
        for field in ("correctness", "accuracy_percentage", "rating", "length_type"):
            self.assertIsNone(rows[2][field])


if __name__ == "__main__":
    unittest.main()
