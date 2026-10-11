"""Integration and access checks for the read-only Phase 3 metrics endpoint."""

import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from bson.int64 import Int64
from fastapi import HTTPException
from pymongo.errors import AutoReconnect

from backend.analytics.metrics import AnalyticsManager
from backend.routes.analytics import session_analytics, session_metrics


USER_ID = "owner-a"
SESSION_ID = "owned-session"
WHEN = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def _database_fixture(database, *, documents=None, messages=None):
    sessions, chats, cursor = MagicMock(), MagicMock(), MagicMock()
    database.return_value.__getitem__.side_effect = {
        "sessions": sessions, "chat_history": chats,
    }.__getitem__
    documents = documents if documents is not None else {
        SESSION_ID: {
            "_id": ObjectId(),
            "session_id": SESSION_ID,
            "user_id": USER_ID,
            "status": "ended",
            "message_count": 1,
            "created_at": WHEN,
            "updated_at": WHEN,
            "password_hash": "do not expose",
        }
    }
    sessions.find_one.side_effect = lambda query: documents.get(query["session_id"])
    chats.find.return_value = cursor
    cursor.sort.return_value = messages if messages is not None else [{
        "_id": ObjectId(),
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "timestamp": WHEN,
        "user_message": "Explain machine learning",
        "llama_response": "Machine learning finds patterns in data.",
        "response_time": "2.25",  # Part 1 legacy timing fallback
        "topic_label": "Machine Learning",
        "feedback": {
            "submitted": True,
            "correctness": "Partial",
            "rating": 3,
            "length_type": "Short",
        },
        "oauth_secret": "do not expose",
    }]
    return sessions, chats, cursor


class MetricsRouteTests(unittest.TestCase):
    @patch("backend.services.session_service._database")
    def test_owned_metrics_use_normalized_history_and_leave_storage_unchanged(self, database):
        sessions, chats, cursor = _database_fixture(database)

        result = session_metrics(SESSION_ID, USER_ID)

        self.assertTrue(result["success"])
        self.assertEqual(result["session"]["session_id"], SESSION_ID)
        self.assertEqual(result["session"]["status"], "ended")
        self.assertEqual(result["metrics"]["summary"]["total_interactions"], 1)
        self.assertEqual(result["metrics"]["accuracy_per_reply"][0]["accuracy_percentage"], 50.0)
        self.assertEqual(result["metrics"]["response_time"]["average_seconds"], 2.25)
        self.assertEqual(result["metrics"]["correctness"]["partial_count"], 1)
        self.assertNotIn("password_hash", json.dumps(result))
        self.assertNotIn("oauth_secret", json.dumps(result))
        json.dumps(result, allow_nan=False)
        sessions.find_one.assert_called_once_with({"session_id": SESSION_ID})
        chats.find.assert_called_once_with({"session_id": SESSION_ID, "user_id": USER_ID})
        cursor.sort.assert_called_once_with("timestamp", 1)
        for collection in (sessions, chats):
            collection.update_one.assert_not_called()
            collection.update_many.assert_not_called()
            collection.insert_one.assert_not_called()
            collection.delete_one.assert_not_called()
            collection.replace_one.assert_not_called()

    @patch("backend.services.session_service._database")
    def test_missing_and_foreign_sessions_have_distinct_errors(self, database):
        foreign_id = "foreign-session"
        documents = {
            SESSION_ID: {"session_id": SESSION_ID, "user_id": USER_ID},
            foreign_id: {"session_id": foreign_id, "user_id": "owner-b"},
        }
        sessions, chats, _ = _database_fixture(database, documents=documents)

        with self.assertRaises(HTTPException) as missing:
            session_metrics("not-a-real-session", USER_ID)
        self.assertEqual((missing.exception.status_code, missing.exception.detail),
                         (404, "Session not found"))
        sessions.find_one.assert_called_once_with({"session_id": "not-a-real-session"})
        chats.find.assert_not_called()

        sessions.find_one.reset_mock()
        with self.assertRaises(HTTPException) as foreign:
            session_metrics(foreign_id, USER_ID)
        self.assertEqual((foreign.exception.status_code, foreign.exception.detail),
                         (403, "Session belongs to another user"))
        sessions.find_one.assert_called_once_with({"session_id": foreign_id})
        chats.find.assert_not_called()

    @patch("backend.services.session_service._database", side_effect=RuntimeError("Database is unavailable"))
    def test_unavailable_database_returns_503(self, database):
        with self.assertRaises(HTTPException) as raised:
            session_metrics(SESSION_ID, USER_ID)
        self.assertEqual((raised.exception.status_code, raised.exception.detail),
                         (503, "Database is unavailable"))

    @patch("backend.services.session_service._database")
    def test_pymongo_failure_returns_safe_503(self, database):
        sessions, chats, _ = _database_fixture(database)
        sessions.find_one.side_effect = AutoReconnect("sensitive connection details")
        with self.assertRaises(HTTPException) as raised:
            session_metrics(SESSION_ID, USER_ID)
        self.assertEqual((raised.exception.status_code, raised.exception.detail),
                         (503, "Database is unavailable"))
        self.assertNotIn("sensitive", raised.exception.detail)
        chats.find.assert_not_called()

    @patch("backend.services.session_service._database")
    def test_bson_int64_rating_is_valid_and_unsubmitted_correctness_is_visible(self, database):
        _, _, cursor = _database_fixture(database)
        stored = cursor.sort.return_value[0]
        stored["feedback"]["rating"] = Int64(4)
        stale = deepcopy(stored)
        stale["_id"] = ObjectId()
        stale["timestamp"] = WHEN + timedelta(minutes=1)
        stale["response_time"] = "4.75"
        stale["feedback"]["submitted"] = False
        stale["feedback"]["correctness"] = "Correct"
        stale["feedback"]["rating"] = 2
        stale["feedback"]["length_type"] = "Lengthy"
        cursor.sort.return_value = [stored, stale]

        metrics = session_metrics(SESSION_ID, USER_ID)["metrics"]
        self.assertEqual(metrics["summary"]["total_interactions"], 2)
        self.assertEqual(metrics["summary"]["feedback_submitted_count"], 1)
        self.assertEqual(metrics["summary"]["correctness_scored_count"], 1)
        self.assertEqual(metrics["correctness"]["correct_count"], 0)
        self.assertEqual(metrics["ratings"]["count"], 1)
        self.assertEqual(metrics["ratings"]["distribution"]["4"], 1)
        self.assertEqual(metrics["ratings"]["distribution"]["2"], 0)
        self.assertEqual(metrics["ratings"]["average"], 4.0)
        self.assertEqual(metrics["length_distribution"]["Lengthy"]["count"], 0)
        self.assertEqual(metrics["length_distribution"]["Short"]["count"], 1)
        self.assertEqual(metrics["response_time"]["count"], 2)
        self.assertEqual(metrics["response_time"]["average_seconds"], 3.5)
        self.assertEqual(metrics["accuracy_per_reply"][1]["correctness"], "Correct")
        self.assertIsNone(metrics["accuracy_per_reply"][1]["accuracy_score"])
        self.assertIsNone(metrics["accuracy_per_reply"][1]["accuracy_percentage"])

    @patch("backend.services.session_service._database")
    def test_empty_session_and_existing_part1_endpoint(self, database):
        document = {"session_id": SESSION_ID, "user_id": USER_ID,
                    "status": "active", "message_count": 0}
        sessions, chats, cursor = _database_fixture(
            database, documents={SESSION_ID: document}, messages=[])

        metrics = session_metrics(SESSION_ID, USER_ID)["metrics"]
        self.assertEqual(metrics["summary"]["total_interactions"], 0)
        self.assertIsNone(metrics["correctness"]["overall_correctness_percentage"])
        self.assertEqual(metrics["response_time"]["count"], 0)
        self.assertIsNone(metrics["ratings"]["average"])
        self.assertEqual(metrics["accuracy_per_reply"], [])
        self.assertEqual(metrics["accuracy_by_topic"], [])
        self.assertEqual(metrics["accuracy_by_phase"], [])
        self.assertTrue(all(row["percentage"] == 0.0 for row in
                            metrics["length_distribution"].values()))

        old = session_analytics(SESSION_ID, USER_ID)
        self.assertTrue(old["success"])
        self.assertEqual(old["interaction_count"], 0)
        self.assertEqual(old["interactions"], [])
        self.assertEqual(chats.find.call_count, 2)
        self.assertEqual(cursor.sort.call_count, 2)
        sessions.update_one.assert_not_called()


class LegacyManagerCompatibilityTests(unittest.TestCase):
    def test_manager_retains_dataframe_add_and_show_interface(self):
        manager = AnalyticsManager()
        self.assertEqual(list(manager.metrics_df.columns), [
            "timestamp", "user_prompt", "response_time", "model_name", "tokens_used",
        ])
        manager.add_metric(WHEN, "Question", 2.0, "llama", 20)
        self.assertEqual(len(manager.metrics_df), 1)
        self.assertEqual(manager.metrics_df.iloc[0]["user_prompt"], "Question")
        with patch("builtins.print") as printed:
            manager.show_metrics()
        printed.assert_called_once_with(manager.metrics_df)


if __name__ == "__main__":
    unittest.main()
