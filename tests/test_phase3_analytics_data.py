"""Phase 3 Part 1 data retrieval, isolation, and normalization tests."""

import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import AutoReconnect

from backend.analytics.data_service import get_session_analytics_data, phase_for_position
from backend.routes.analytics import session_analytics
from backend.services.session_service import SessionNotFoundError, SessionOwnershipError


SESSION_ID = "session-a"
USER_ID = "user-a"
START = datetime(2026, 1, 2, 10, tzinfo=timezone.utc)


def session(**changes):
    result = {
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "status": "active",
        "message_count": 0,
        "created_at": START,
        "updated_at": START,
    }
    result.update(changes)
    return result


def interaction(index, **changes):
    result = {
        "_id": ObjectId(),
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "user_message": f"Question {index}",
        "llama_response": f"Answer {index}",
        "timestamp": START + timedelta(minutes=index),
        "request_start_time": START + timedelta(minutes=index),
        "response_end_time": START + timedelta(minutes=index, seconds=2),
        "response_time_seconds": 2.0,
        "topic_label": "General",
        "feedback": {
            "rating": 4,
            "correctness": "Correct",
            "length_type": "To the Point",
            "submitted": True,
        },
    }
    result.update(changes)
    return result


class AnalyticsDataTests(unittest.TestCase):
    @patch("backend.analytics.data_service.get_session_history")
    def test_owned_history_is_ordered_and_numbered_without_changing_documents(self, history):
        first, second, third = interaction(1), interaction(2), interaction(3)
        first["password_hash"] = "never expose"
        owned = session(message_count=3, oauth_secret="never expose")
        originals = deepcopy((owned, first, second, third))
        history.return_value = (owned, [third, first, second])

        result = get_session_analytics_data(SESSION_ID, USER_ID)

        history.assert_called_once_with(SESSION_ID, USER_ID)
        self.assertEqual(result["interaction_count"], 3)
        self.assertEqual([row["user_message"] for row in result["interactions"]],
                         ["Question 1", "Question 2", "Question 3"])
        self.assertEqual([row["interaction_number"] for row in result["interactions"]],
                         [1, 2, 3])
        self.assertEqual([row["phase"] for row in result["interactions"]],
                         ["Start", "Middle", "End"])
        self.assertNotIn("password_hash", result["interactions"][0])
        self.assertNotIn("oauth_secret", result["session"])
        self.assertEqual((owned, first, second, third), originals)

    @patch("backend.analytics.data_service.get_session_history")
    def test_empty_session_has_no_interactions(self, history):
        history.return_value = (session(), [])
        result = session_analytics(SESSION_ID, USER_ID)
        self.assertTrue(result["success"])
        self.assertEqual(result["interaction_count"], 0)
        self.assertEqual(result["interactions"], [])
        self.assertEqual(result["session"]["message_count"], 0)

    @patch("backend.analytics.data_service.get_session_history")
    def test_ended_session_returns_full_history_beyond_context_limit(self, history):
        records = [interaction(i) for i in range(12)]
        history.return_value = (session(status="ended", message_count=12), records)

        result = get_session_analytics_data(SESSION_ID, USER_ID)

        self.assertEqual(result["session"]["status"], "ended")
        self.assertEqual(result["interaction_count"], 12)
        self.assertEqual(result["session"]["message_count"], 12)
        self.assertEqual(len(result["interactions"]), 12)
        self.assertEqual(result["interactions"][-1]["interaction_number"], 12)
        history.assert_called_once_with(SESSION_ID, USER_ID)

    @patch("backend.analytics.data_service.get_session_history")
    def test_valid_stored_count_is_preserved_even_for_legacy_history(self, history):
        history.return_value = (session(message_count=4), [interaction(1)])
        result = get_session_analytics_data(SESSION_ID, USER_ID)
        self.assertEqual(result["session"]["message_count"], 4)
        self.assertEqual(result["interaction_count"], 1)

    @patch("backend.analytics.data_service.get_session_history")
    def test_one_and_two_interaction_special_cases(self, history):
        for size, expected in ((1, ["Start"]), (2, ["Start", "End"])):
            with self.subTest(size=size):
                history.return_value = (session(message_count=size),
                                        [interaction(i) for i in range(size)])
                result = get_session_analytics_data(SESSION_ID, USER_ID)
                self.assertEqual([row["phase"] for row in result["interactions"]], expected)

    def test_phase_boundaries_for_longer_sessions(self):
        for total, expected in (
            (3, ["Start", "Middle", "End"]),
            (4, ["Start", "Middle", "End", "End"]),
            (6, ["Start", "Start", "Middle", "Middle", "End", "End"]),
            (10, ["Start"] * 3 + ["Middle"] * 3 + ["End"] * 4),
        ):
            with self.subTest(total=total):
                phases = [phase_for_position(index, total) for index in range(total)]
                self.assertEqual(phases, expected)
                self.assertTrue(all(phase in {"Start", "Middle", "End"} for phase in phases))
        with self.assertRaises(ValueError):
            phase_for_position(0, 0)

    @patch("backend.analytics.data_service.get_session_history")
    def test_topics_reuse_valid_label_and_reclassify_missing_or_invalid(self, history):
        records = [
            interaction(1, topic_label="Power Systems", user_message="medical diagnosis"),
            interaction(2, topic_label=None, user_message="machine learning regression"),
            interaction(3, topic_label="", llama_response="Use a neural network"),
            interaction(4, topic_label={"unexpected": "shape"}, user_message="patient diagnosis"),
            interaction(5, topic_label="Not a topic", user_message="plain greeting"),
        ]
        history.return_value = (session(message_count=5), records)
        result = get_session_analytics_data(SESSION_ID, USER_ID)
        self.assertEqual([row["topic_label"] for row in result["interactions"]], [
            "Power Systems", "Machine Learning", "Deep Learning", "Healthcare AI", "General"
        ])
        self.assertEqual(records[1]["topic_label"], None)

    @patch("backend.analytics.data_service.get_session_history")
    def test_missing_topic_and_feedback_use_safe_defaults(self, history):
        legacy = interaction(1)
        legacy.pop("topic_label")
        legacy.pop("feedback")
        legacy["user_message"] = "Diagnose a hospital patient"
        history.return_value = (session(message_count=1), [legacy])

        record = get_session_analytics_data(SESSION_ID, USER_ID)["interactions"][0]

        self.assertEqual(record["topic_label"], "Healthcare AI")
        self.assertIsNone(record["rating"])
        self.assertIsNone(record["correctness"])
        self.assertIsNone(record["length_type"])
        self.assertFalse(record["feedback_submitted"])
        self.assertNotIn("topic_label", legacy)

    @patch("backend.analytics.data_service.get_session_history")
    def test_legacy_times_ties_and_undated_records_sort_deterministically(self, history):
        older = interaction(1, timestamp=None,
                            request_start_time="2026-01-02T09:00:00Z")
        same_time_a = interaction(2, _id="a", timestamp=START.replace(tzinfo=None))
        same_time_b = interaction(3, _id="b", timestamp="2026-01-02T10:00:00+00:00")
        undated = interaction(4, timestamp="not a date", request_start_time=None)
        history.return_value = (session(message_count="bad"),
                                [undated, same_time_b, older, same_time_a])
        result = get_session_analytics_data(SESSION_ID, USER_ID)
        self.assertEqual([row["interaction_id"] for row in result["interactions"]],
                         [str(older["_id"]), "a", "b", str(undated["_id"])])
        self.assertIsNone(result["interactions"][-1]["timestamp"])
        self.assertEqual(result["session"]["message_count"], 4)

    @patch("backend.analytics.data_service.get_session_history")
    def test_invalid_feedback_and_times_are_safe_json_values(self, history):
        source = interaction(
            1,
            feedback={"rating": True, "correctness": ["Correct"],
                      "length_type": {"type": "Short"}, "submitted": "true"},
            response_time_seconds=float("nan"), response_time="3.5",
        )
        other = interaction(2, feedback=["invalid"], response_time_seconds=-2,
                            response_time=None)
        history.return_value = (session(message_count=2), [source, other])
        result = get_session_analytics_data(SESSION_ID, USER_ID)
        first, second = result["interactions"]
        self.assertEqual(first["response_time_seconds"], 3.5)
        self.assertIsNone(second["response_time_seconds"])
        for row in (first, second):
            self.assertIsNone(row["rating"])
            self.assertIsNone(row["correctness"])
            self.assertIsNone(row["length_type"])
            self.assertFalse(row["feedback_submitted"])
        self.assertEqual(first["interaction_id"], str(source["_id"]))
        self.assertEqual(first["timestamp"], source["timestamp"].isoformat())
        encoded = json.dumps(result, allow_nan=False)
        self.assertEqual(json.loads(encoded)["interaction_count"], 2)

    @patch("backend.analytics.data_service.get_session_history")
    def test_valid_feedback_remains_available(self, history):
        history.return_value = (session(message_count=1), [interaction(1)])
        record = get_session_analytics_data(SESSION_ID, USER_ID)["interactions"][0]
        self.assertEqual(record["rating"], 4)
        self.assertEqual(record["correctness"], "Correct")
        self.assertEqual(record["length_type"], "To the Point")
        self.assertTrue(record["feedback_submitted"])


class AnalyticsAccessTests(unittest.TestCase):
    @patch("backend.services.session_service._database")
    def test_correct_owner_queries_history_with_both_ids(self, database):
        sessions, chats, cursor = MagicMock(), MagicMock(), MagicMock()
        database.return_value.__getitem__.side_effect = {
            "sessions": sessions, "chat_history": chats,
        }.__getitem__
        sessions.find_one.return_value = session(message_count=1)
        chats.find.return_value = cursor
        cursor.sort.return_value = [interaction(1)]
        result = session_analytics(SESSION_ID, USER_ID)
        self.assertEqual(result["interaction_count"], 1)
        sessions.find_one.assert_called_once_with({"session_id": SESSION_ID})
        chats.find.assert_called_once_with({"session_id": SESSION_ID, "user_id": USER_ID})
        cursor.sort.assert_called_once_with("timestamp", 1)
        sessions.update_one.assert_not_called()
        chats.update_one.assert_not_called()
        sessions.insert_one.assert_not_called()
        chats.insert_one.assert_not_called()

    @patch("backend.services.session_service._database")
    def test_other_owner_is_forbidden_before_history_query(self, database):
        sessions, chats = MagicMock(), MagicMock()
        database.return_value.__getitem__.side_effect = {
            "sessions": sessions, "chat_history": chats,
        }.__getitem__
        sessions.find_one.return_value = session(user_id="user-b")
        with self.assertRaises(HTTPException) as raised:
            session_analytics(SESSION_ID, USER_ID)
        self.assertEqual(raised.exception.status_code, 403)
        chats.find.assert_not_called()

    @patch("backend.services.session_service._database")
    def test_missing_session_is_not_found(self, database):
        sessions = MagicMock()
        database.return_value.__getitem__.return_value = sessions
        sessions.find_one.return_value = None
        with self.assertRaises(HTTPException) as raised:
            session_analytics(SESSION_ID, USER_ID)
        self.assertEqual(raised.exception.status_code, 404)

    @patch("backend.services.session_service._database")
    def test_unknown_id_stays_404_when_other_sessions_exist(self, database):
        sessions, chats, cursor = MagicMock(), MagicMock(), MagicMock()
        database.return_value.__getitem__.side_effect = {
            "sessions": sessions, "chat_history": chats,
        }.__getitem__
        stored = {
            SESSION_ID: session(),
            "session-b": session(session_id="session-b", user_id="user-b"),
        }
        sessions.find_one.side_effect = lambda query: stored.get(query["session_id"])

        with self.assertRaises(HTTPException) as missing:
            session_analytics("not-a-real-session", USER_ID)
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(missing.exception.detail, "Session not found")
        sessions.find_one.assert_called_once_with({"session_id": "not-a-real-session"})
        chats.find.assert_not_called()

        sessions.find_one.reset_mock()
        with self.assertRaises(HTTPException) as foreign:
            session_analytics("session-b", USER_ID)
        self.assertEqual(foreign.exception.status_code, 403)
        sessions.find_one.assert_called_once_with({"session_id": "session-b"})
        chats.find.assert_not_called()

        sessions.find_one.reset_mock()
        chats.find.return_value = cursor
        cursor.sort.return_value = [interaction(1)]
        owned = session_analytics(SESSION_ID, USER_ID)
        self.assertEqual(owned["interaction_count"], 1)
        sessions.find_one.assert_called_once_with({"session_id": SESSION_ID})
        chats.find.assert_called_once_with({"session_id": SESSION_ID, "user_id": USER_ID})

    @patch("backend.analytics.data_service.get_session_history",
           side_effect=AutoReconnect("internal database details"))
    def test_pymongo_failure_becomes_safe_unavailable_response(self, history):
        with self.assertRaises(HTTPException) as raised:
            session_analytics(SESSION_ID, USER_ID)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "Database is unavailable")

    @patch("backend.analytics.data_service.get_session_history",
           side_effect=RuntimeError("Database is unavailable"))
    def test_disconnected_database_is_unavailable(self, history):
        with self.assertRaises(HTTPException) as raised:
            session_analytics(SESSION_ID, USER_ID)
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
