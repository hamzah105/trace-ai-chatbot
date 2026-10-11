"""FR22 finalization, immutable writes, ownership, and process-local races."""

import copy
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import OperationFailure

from backend.analytics.finalization import (
    FinalizationComputationError, FinalizationConflictError, PendingFeedbackError,
    finalize_session,
)
from backend.analytics.metrics import compute_session_metrics
from backend.analytics.dashboard import build_session_overview
from backend.analytics.data_service import get_session_analytics_data
from backend.routes.analytics import session_dashboard, session_metrics
from backend.routes.chat import ChatRequest, chat
from backend.routes.feedback import FeedbackRequest, submit_feedback
from backend.routes.sessions import EndSessionRequest, end, serialize_session
from backend.services.session_service import SessionNotFoundError, SessionOwnershipError
from backend.services.session_lifecycle import _entries, session_lifecycle


OWNER = "owner"
SESSION = "session-fr22"


def _matches(row, query):
    for key, expected in query.items():
        actual = row
        for part in key.split("."):
            actual = actual.get(part) if isinstance(actual, dict) else None
        if isinstance(expected, dict) and "$ne" in expected:
            if actual == expected["$ne"]:
                return False
        elif actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        if isinstance(key, list):
            key, direction = key[0]
        self.rows.sort(key=lambda row: row.get(key) or datetime.min.replace(tzinfo=timezone.utc),
                       reverse=direction == -1)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(copy.deepcopy(self.rows))


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = copy.deepcopy(rows or [])
        self.writes = 0
        self.fail_update = False
        self.before_update = None

    def find_one(self, query, sort=None):
        rows = [row for row in self.rows if _matches(row, query)]
        if sort:
            rows = list(FakeCursor(rows).sort(*sort[0]))
        return copy.deepcopy(rows[0]) if rows else None

    def find(self, query):
        return FakeCursor([row for row in self.rows if _matches(row, query)])

    def update_one(self, query, update):
        if self.fail_update:
            raise OperationFailure("write failed")
        for row in self.rows:
            if _matches(row, query):
                for key, value in update.get("$set", {}).items():
                    parts = key.split(".")
                    current = row
                    for part in parts[:-1]:
                        current = current.setdefault(part, {})
                    current[parts[-1]] = copy.deepcopy(value)
                for key, value in update.get("$inc", {}).items():
                    row[key] = row.get(key, 0) + value
                for key, value in update.get("$addToSet", {}).items():
                    values = row.setdefault(key, [])
                    if value not in values:
                        values.append(value)
                self.writes += 1
                return SimpleNamespace(modified_count=1, matched_count=1)
        return SimpleNamespace(modified_count=0, matched_count=0)

    def find_one_and_update(self, query, update, return_document=None):
        if self.before_update:
            self.before_update(self)
        result = self.update_one(query, update)
        return self.find_one({"session_id": query["session_id"]}) if result.modified_count else None

    def insert_one(self, row):
        row = copy.deepcopy(row)
        row.setdefault("_id", ObjectId())
        self.rows.append(row)
        self.writes += 1
        return SimpleNamespace(inserted_id=row["_id"])


def make_database(feedback=(True,), status="active"):
    now = datetime.now(timezone.utc)
    sessions = FakeCollection([{
        "session_id": SESSION, "user_id": OWNER, "status": status,
        "created_at": now, "updated_at": now, "message_count": len(feedback),
        "topics": [], "summary": "", "password_hash": "never-public",
        "oauth_token": "never-public", "private_mongo_field": "never-public",
    }])
    chats = FakeCollection([{
        "_id": ObjectId(), "session_id": SESSION, "user_id": OWNER,
        "user_message": f"question {number}", "llama_response": "answer",
        "timestamp": now.replace(microsecond=number),
        "response_time_seconds": 1.0, "topic_label": "General",
        "feedback": {"submitted": submitted, "rating": 4,
                     "correctness": "Correct", "length_type": "Short"},
        "oauth_secret": "never-public",
    } for number, submitted in enumerate(feedback)])
    return {"sessions": sessions, "chat_history": chats}, sessions, chats


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.db, self.sessions, self.chats = make_database()
        self.db_patch = patch("backend.services.session_service.get_database", side_effect=lambda: self.db)
        self.data_patch = patch("backend.analytics.finalization.get_database", side_effect=lambda: self.db)
        self.feedback_patch = patch("backend.routes.feedback.get_database", side_effect=lambda: self.db)
        self.db_patch.start(); self.data_patch.start(); self.feedback_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.data_patch.stop)
        self.addCleanup(self.feedback_patch.stop)

    def test_owned_finalization_persists_one_snapshot_without_history_changes(self):
        original = copy.deepcopy(self.chats.rows)
        expected_data = get_session_analytics_data(SESSION, OWNER)
        expected_metrics = compute_session_metrics(expected_data["interactions"])
        result = finalize_session(SESSION, OWNER)
        snapshot = result["final_analytics"]
        self.assertEqual(result["status"], "ended")
        self.assertIsInstance(result["ended_at"], datetime)
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["finalized_at"], result["ended_at"])
        self.assertEqual(snapshot["interaction_count"], 1)
        self.assertEqual(snapshot["metrics"], expected_metrics)
        self.assertEqual(snapshot["overview"], build_session_overview(expected_metrics))
        self.assertEqual(self.chats.rows, original)
        self.assertEqual(self.sessions.writes, 1)
        self.assertEqual(self.chats.writes, 0)
        self.assertEqual(finalize_session(SESSION, OWNER), result)
        self.assertEqual(self.sessions.writes, 1)
        self.assertNotIn("password_hash", serialize_session(result))
        self.assertNotIn("oauth_token", str(serialize_session(result)))
        self.assertNotIn("private_mongo_field", str(serialize_session(result)))

    def test_pending_older_record_and_strict_true_block_finalization(self):
        self.db, self.sessions, self.chats = make_database((None, True))
        with self.assertRaises(PendingFeedbackError) as caught:
            finalize_session(SESSION, OWNER)
        self.assertEqual(caught.exception.count, 1)
        self.assertEqual(self.sessions.rows[0]["status"], "active")
        self.assertNotIn("final_analytics", self.sessions.rows[0])
        with self.assertRaises(HTTPException) as response:
            end(SESSION, EndSessionRequest(user_id=OWNER))
        self.assertEqual(response.exception.status_code, 409)
        self.assertEqual(response.exception.detail["code"], "feedback_required")

    def test_feedback_marker_must_be_boolean_true(self):
        for value in ("true", 1, None, False):
            with self.subTest(value=value):
                self.db, self.sessions, self.chats = make_database((value, True))
                with self.assertRaises(PendingFeedbackError) as caught:
                    finalize_session(SESSION, OWNER)
                self.assertEqual(caught.exception.count, 1)
                self.assertEqual(self.sessions.writes, 0)

    def test_empty_and_legacy_ended(self):
        self.db, self.sessions, self.chats = make_database(())
        result = finalize_session(SESSION, OWNER)
        self.assertEqual(result["final_analytics"]["metrics"]["summary"]["total_interactions"], 0)
        self.assertIsNone(result["final_analytics"]["overview"]["average_rating"])
        self.db, self.sessions, self.chats = make_database((), "ended")
        self.assertEqual(finalize_session(SESSION, OWNER), self.sessions.rows[0])
        self.assertEqual(self.sessions.writes, 0)

    def test_ownership_precedes_history_and_computation(self):
        with patch("backend.analytics.finalization.get_session_analytics_data") as history:
            with self.assertRaises(SessionOwnershipError):
                finalize_session(SESSION, "stranger")
            history.assert_not_called()
        with self.assertRaises(SessionNotFoundError):
            finalize_session("missing", OWNER)

    def test_computation_database_and_compare_and_swap_failures(self):
        with patch("backend.analytics.finalization.compute_session_metrics", side_effect=ValueError):
            with self.assertRaises(FinalizationComputationError):
                finalize_session(SESSION, OWNER)
        self.assertEqual(self.sessions.writes, 0)
        self.sessions.fail_update = True
        with self.assertRaises(RuntimeError):
            finalize_session(SESSION, OWNER)
        self.sessions.fail_update = False
        self.sessions.before_update = lambda collection: collection.rows[0].update(message_count=99)
        with self.assertRaises(FinalizationConflictError):
            finalize_session(SESSION, OWNER)
        self.assertEqual(self.sessions.rows[0]["status"], "active")

    def test_cas_loser_returns_authoritative_winner_without_overwrite(self):
        winner_time = datetime(2024, 1, 2, tzinfo=timezone.utc)
        data = get_session_analytics_data(SESSION, OWNER)
        winner_metrics = compute_session_metrics(data["interactions"])
        winner_metrics["ratings"]["average"] = 2.0
        winner_snapshot = {
            "version": 1, "finalized_at": winner_time,
            "interaction_count": 1,
            "metrics": winner_metrics,
            "overview": build_session_overview(winner_metrics),
        }

        def finish_elsewhere(collection):
            collection.before_update = None
            collection.rows[0].update(status="ended", ended_at=winner_time,
                                      final_analytics=copy.deepcopy(winner_snapshot))

        self.sessions.before_update = finish_elsewhere
        result = finalize_session(SESSION, OWNER)
        self.assertEqual(result["ended_at"], winner_time)
        self.assertEqual(result["final_analytics"], winner_snapshot)
        self.assertEqual(self.sessions.writes, 0)

    def test_finalized_analytics_uses_stored_values_and_read_only_gets(self):
        finalize_session(SESSION, OWNER)
        self.sessions.rows[0]["final_analytics"]["overview"]["average_rating"] = 2.5
        self.sessions.rows[0]["final_analytics"]["metrics"]["ratings"]["average"] = 2.5
        baseline = self.sessions.writes, self.chats.writes
        dashboard = session_dashboard(SESSION, OWNER)
        self.assertTrue(dashboard["finalization"]["is_finalized"])
        self.assertEqual(dashboard["overview"]["average_rating"], 2.5)
        self.assertEqual(session_metrics(SESSION, OWNER)["metrics"]["ratings"]["average"], 2.5)
        self.assertEqual((self.sessions.writes, self.chats.writes), baseline)
        self.assertNotIn("oauth_secret", str(dashboard))

    def test_ended_chat_and_feedback_rejected_without_writes(self):
        finalize_session(SESSION, OWNER)
        with patch("backend.routes.chat.generate_response") as generate:
            with self.assertRaises(HTTPException) as caught:
                chat(ChatRequest(message="late", session_id=SESSION, user_id=OWNER))
            self.assertEqual(caught.exception.status_code, 409)
            generate.assert_not_called()
        interaction = self.chats.rows[0]
        with self.assertRaises(HTTPException) as caught:
            submit_feedback(FeedbackRequest(interaction_id=str(interaction["_id"]),
                                             rating=2, correctness="Partial",
                                             length_type="Short"))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.chats.writes, 0)

    def test_chat_generation_holds_lifecycle_until_saved(self):
        self.db, self.sessions, self.chats = make_database(())
        generating = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        outcomes = {}

        def generate(_prompt):
            generating.set()
            self.assertTrue(release.wait(3))
            return "answer"

        def run_chat():
            try:
                outcomes["chat"] = chat(ChatRequest(message="hello", session_id=SESSION, user_id=OWNER))
            except Exception as error:
                outcomes["chat_error"] = error

        def run_end():
            try:
                outcomes["end"] = finalize_session(SESSION, OWNER)
            except Exception as error:
                outcomes["end_error"] = error
            finally:
                finished.set()

        with patch("backend.routes.chat.build_context_prompt", return_value="prompt"), \
             patch("backend.routes.chat.generate_response", side_effect=generate), \
             patch("backend.routes.chat.save_chat", side_effect=self.chats.insert_one):
            first = threading.Thread(target=run_chat)
            second = threading.Thread(target=run_end)
            first.start()
            try:
                self.assertTrue(generating.wait(3))
                second.start()
                self.assertFalse(finished.wait(0.05))
                release.set()
                first.join(3); second.join(3)
            finally:
                release.set()
                first.join(3)
                if second.ident:
                    second.join(3)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertIn("chat", outcomes)
        self.assertIsInstance(outcomes.get("end_error"), PendingFeedbackError)
        self.assertEqual(self.sessions.rows[0]["status"], "active")
        self.assertEqual(len(self.chats.rows), 1)

    def test_finalization_holds_lifecycle_against_late_feedback(self):
        computing = threading.Event()
        release = threading.Event()
        outcomes = {}
        original_compute = compute_session_metrics

        def compute(interactions):
            computing.set()
            self.assertTrue(release.wait(3))
            return original_compute(interactions)

        def run_end():
            try:
                outcomes["end"] = finalize_session(SESSION, OWNER)
            except Exception as error:
                outcomes["end_error"] = error

        def run_feedback():
            row = self.chats.rows[0]
            try:
                outcomes["feedback"] = submit_feedback(FeedbackRequest(
                    interaction_id=str(row["_id"]), rating=1,
                    correctness="Incorrect", length_type="Lengthy"))
            except Exception as error:
                outcomes["feedback_error"] = error

        with patch("backend.analytics.finalization.compute_session_metrics", side_effect=compute):
            first = threading.Thread(target=run_end)
            second = threading.Thread(target=run_feedback)
            first.start()
            try:
                self.assertTrue(computing.wait(3))
                second.start()
                release.set()
                first.join(3); second.join(3)
            finally:
                release.set()
                first.join(3)
                if second.ident:
                    second.join(3)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertIn("end", outcomes)
        self.assertEqual(outcomes["feedback_error"].status_code, 409)
        self.assertEqual(self.chats.writes, 0)
        self.assertEqual(self.chats.rows[0]["feedback"]["rating"], 4)

    def test_malformed_legacy_snapshot_is_not_exposed_or_backfilled(self):
        self.db, self.sessions, self.chats = make_database((True,), "ended")
        self.sessions.rows[0]["final_analytics"] = {"version": 1, "secret": "never-public"}
        dashboard = session_dashboard(SESSION, OWNER)
        self.assertFalse(dashboard["finalization"]["is_finalized"])
        self.assertNotIn("never-public", str(dashboard))
        self.assertEqual(self.sessions.writes, 0)

    def test_snapshot_projection_filters_nested_unknown_fields_and_invalid_versions(self):
        finalize_session(SESSION, OWNER)
        raw = self.sessions.rows[0]["final_analytics"]
        raw["oauth_token"] = "secret-token"
        raw["overview"]["password_hash"] = "secret-password"
        raw["metrics"]["oauth_secret"] = "secret-oauth"
        raw["metrics"]["summary"]["private_mongo_field"] = "secret-mongo"
        raw["metrics"]["accuracy_per_reply"][0]["password_hash"] = "secret-row"
        raw["metrics"]["ratings"]["distribution"]["oauth_token"] = "secret-rating"
        public = serialize_session(self.sessions.rows[0])
        for secret in ("secret-token", "secret-password", "secret-oauth",
                       "secret-mongo", "secret-row", "secret-rating"):
            self.assertNotIn(secret, str(public))
        self.assertTrue(public["finalization"]["is_finalized"])
        for invalid in (True, 1.0):
            with self.subTest(version=invalid):
                raw["version"] = invalid
                public = serialize_session(self.sessions.rows[0])
                self.assertFalse(public["finalization"]["is_finalized"])
                self.assertNotIn("final_analytics", public)

    def test_lock_registry_reclaims_reentrant_and_exceptional_entries(self):
        with self.assertRaises(ValueError):
            with session_lifecycle("fr22-lock-reclaim"):
                with session_lifecycle("fr22-lock-reclaim"):
                    self.assertIn("fr22-lock-reclaim", _entries)
                    raise ValueError("expected")
        self.assertNotIn("fr22-lock-reclaim", _entries)

    def test_different_sessions_can_enter_lifecycle_concurrently(self):
        holding = threading.Event()
        release = threading.Event()
        other_entered = threading.Event()

        def hold_first():
            with session_lifecycle("fr22-first"):
                holding.set()
                release.wait(3)

        def enter_second():
            with session_lifecycle("fr22-second"):
                other_entered.set()

        first = threading.Thread(target=hold_first)
        second = threading.Thread(target=enter_second)
        first.start()
        try:
            self.assertTrue(holding.wait(3))
            second.start()
            self.assertTrue(other_entered.wait(3))
        finally:
            release.set()
            first.join(3)
            if second.ident:
                second.join(3)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertNotIn("fr22-first", _entries)
        self.assertNotIn("fr22-second", _entries)


if __name__ == "__main__":
    unittest.main()
