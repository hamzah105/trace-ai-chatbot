"""FR20/FR21 routes over a query-aware fake owned-session database."""

import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import AutoReconnect

from backend.routes.analytics import (
    session_analytics, session_charts, session_dashboard, session_metrics, session_tables,
)


SESSION_ID = "session-a"
OWNER = "owner-a"
WHEN = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


def fixture(database, messages=None, documents=None):
    sessions, chats, cursor, users = (MagicMock() for _ in range(4))
    database.return_value.__getitem__.side_effect = {
        "sessions": sessions, "chat_history": chats, "users": users,
    }.__getitem__
    documents = documents if documents is not None else {
        SESSION_ID: {"_id": ObjectId(), "session_id": SESSION_ID, "user_id": OWNER,
                     "status": "ended", "message_count": 3,
                     "password_hash": "secret password"}
    }
    sessions.find_one.side_effect = lambda query: documents.get(query["session_id"])
    chats.find.return_value = cursor
    cursor.sort.return_value = messages if messages is not None else [
        {
            "_id": ObjectId(), "session_id": SESSION_ID, "user_id": OWNER,
            "timestamp": WHEN + timedelta(minutes=index),
            "user_message": f"private question {index}",
            "llama_response": f"private response {index}",
            "topic_label": topic, "response_time_seconds": seconds,
            "feedback": {"submitted": True, "correctness": correctness,
                         "rating": rating, "length_type": length},
            "oauth_secret": "secret token",
        }
        for index, topic, correctness, rating, length, seconds in (
            (2, "Healthcare AI", "Incorrect", 2, "Lengthy", 30),
            (0, "Machine Learning", "Correct", 4, "To the Point", 10),
            (1, "Machine Learning", "Partial", 3, "Short", 20),
        )
    ]
    return sessions, chats, cursor, users


class DashboardRouteTests(unittest.TestCase):
    @patch("backend.services.session_service._database")
    def test_owned_charts_and_dashboard_are_json_safe_and_read_only(self, database):
        sessions, chats, cursor, users = fixture(database)
        before = deepcopy(cursor.sort.return_value)

        charts_response = session_charts(SESSION_ID, OWNER)
        dashboard_response = session_dashboard(SESSION_ID, OWNER)

        self.assertTrue(charts_response["success"])
        self.assertTrue(dashboard_response["success"])
        self.assertEqual(charts_response["session"], dashboard_response["session"])
        self.assertEqual(charts_response["charts"], dashboard_response["charts"])
        self.assertEqual(len(dashboard_response["charts"]), 7)
        self.assertEqual(len(dashboard_response["tables"]), 6)
        self.assertEqual(dashboard_response["overview"]["dominant_topic"], "Machine Learning")
        self.assertEqual(dashboard_response["overview"]["total_interactions"], 3)
        self.assertEqual(dashboard_response["metrics"]["summary"]["total_interactions"], 3)
        payload = json.dumps(dashboard_response, allow_nan=False)
        charts_payload = json.dumps(charts_response, allow_nan=False)
        for secret in ("secret password", "secret token"):
            self.assertNotIn(secret, payload)
            self.assertNotIn(secret, charts_payload)
        for private in ("private question", "private response"):
            self.assertNotIn(private, payload)
            self.assertNotIn(private, charts_payload)
        self.assertEqual(cursor.sort.return_value, before)
        self.assertEqual(sessions.find_one.call_count, 2)
        self.assertEqual(chats.find.call_count, 2)
        chats.find.assert_called_with({"session_id": SESSION_ID, "user_id": OWNER})
        for collection in (sessions, chats, users):
            for method in ("update_one", "update_many", "insert_one", "insert_many",
                           "replace_one", "delete_one", "delete_many"):
                getattr(collection, method).assert_not_called()

    @patch("backend.routes.analytics.build_session_charts")
    @patch("backend.routes.analytics.build_session_tables")
    @patch("backend.routes.analytics.compute_session_metrics")
    @patch("backend.routes.analytics.get_session_analytics_data")
    def test_dashboard_retrieves_once_and_calculates_once(self, get_data, compute, tables, charts):
        get_data.return_value = {"session": {"session_id": SESSION_ID}, "interactions": [
            {"interaction_number": 1},
        ]}
        compute.return_value = {
            "summary": {"total_interactions": 1, "feedback_submitted_count": 0},
            "accuracy_by_topic": [],
            "length_distribution": {key: {"count": 0} for key in
                                    ("Short", "To the Point", "Lengthy")},
            "correctness": {"overall_correctness_percentage": None,
                            "strict_correct_percentage": None},
            "ratings": {"average": None}, "response_time": {"average_seconds": None},
        }
        tables.return_value = {"table": "sentinel"}
        charts.return_value = {"chart": "sentinel"}

        response = session_dashboard(SESSION_ID, OWNER)

        get_data.assert_called_once_with(SESSION_ID, OWNER)
        compute.assert_called_once_with(get_data.return_value["interactions"])
        tables.assert_called_once_with(get_data.return_value["interactions"], compute.return_value)
        charts.assert_called_once_with(get_data.return_value["interactions"], compute.return_value)
        self.assertIs(response["metrics"], compute.return_value)
        self.assertEqual(response["tables"], {"table": "sentinel"})
        self.assertEqual(response["charts"], {"chart": "sentinel"})

    @patch("backend.services.session_service._database")
    def test_empty_owned_session_is_complete(self, database):
        fixture(database, messages=[], documents={SESSION_ID: {
            "session_id": SESSION_ID, "user_id": OWNER,
            "status": "active", "message_count": 0,
        }})
        dashboard = session_dashboard(SESSION_ID, OWNER)
        self.assertEqual(dashboard["overview"]["total_interactions"], 0)
        self.assertIsNone(dashboard["overview"]["dominant_topic"])
        self.assertTrue(all(chart["empty"] for chart in dashboard["charts"].values()))
        self.assertEqual(dashboard["charts"]["rating_distribution"]["labels"],
                         ["1", "2", "3", "4"])
        self.assertEqual(dashboard["tables"]["topic_vs_accuracy"]["row_count"], 0)

    @patch("backend.routes.analytics.build_session_charts")
    @patch("backend.routes.analytics.build_session_tables")
    @patch("backend.routes.analytics.compute_session_metrics")
    @patch("backend.services.session_service._database")
    def test_missing_and_wrong_owner_block_both_routes_before_calculation(
            self, database, compute, tables, charts):
        foreign = "foreign-session"
        sessions, chats, _, _ = fixture(database, documents={
            foreign: {"session_id": foreign, "user_id": "owner-b"},
        })
        for route in (session_charts, session_dashboard):
            for session_id, expected in (("missing-session", 404), (foreign, 403)):
                with self.subTest(route=route.__name__, session_id=session_id):
                    with self.assertRaises(HTTPException) as raised:
                        route(session_id, OWNER)
                    self.assertEqual(raised.exception.status_code, expected)
        self.assertEqual(sessions.find_one.call_count, 4)
        chats.find.assert_not_called()
        compute.assert_not_called()
        tables.assert_not_called()
        charts.assert_not_called()

    @patch("backend.services.session_service._database", side_effect=RuntimeError("Database is unavailable"))
    def test_unavailable_database_returns_503_for_both_routes(self, database):
        for route in (session_charts, session_dashboard):
            with self.subTest(route=route.__name__):
                with self.assertRaises(HTTPException) as raised:
                    route(SESSION_ID, OWNER)
                self.assertEqual((raised.exception.status_code, raised.exception.detail),
                                 (503, "Database is unavailable"))

    @patch("backend.services.session_service._database")
    def test_pymongo_error_is_sanitized(self, database):
        sessions, _, _, _ = fixture(database)
        sessions.find_one.side_effect = AutoReconnect("secret connection string")
        for route in (session_charts, session_dashboard):
            with self.subTest(route=route.__name__):
                with self.assertRaises(HTTPException) as raised:
                    route(SESSION_ID, OWNER)
                self.assertEqual((raised.exception.status_code, raised.exception.detail),
                                 (503, "Database is unavailable"))

    @patch("backend.services.session_service._database")
    def test_previous_endpoints_are_unchanged(self, database):
        fixture(database)
        self.assertEqual(session_analytics(SESSION_ID, OWNER)["interaction_count"], 3)
        self.assertEqual(session_metrics(SESSION_ID, OWNER)["metrics"]["summary"][
            "total_interactions"], 3)
        self.assertEqual(session_tables(SESSION_ID, OWNER)["tables"][
            "reply_correctness"]["row_count"], 3)


if __name__ == "__main__":
    unittest.main()
