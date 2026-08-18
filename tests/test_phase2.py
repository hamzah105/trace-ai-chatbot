import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import requests
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from backend.routes.auth import encode_oauth_state, validate_oauth_state
from backend.routes.chat import ChatRequest, chat
from backend.routes.feedback import FeedbackRequest
from backend.routes.sessions import history
from backend.services.ollama_service import OllamaTimeoutError, generate_response
from backend.services.session_service import (
    SessionOwnershipError,
    get_pending_feedback,
    get_session_history,
    get_user_sessions,
)
from backend.services.topic_service import classify_topic


class TopicServiceTests(unittest.TestCase):
    def test_all_allowed_topic_labels(self):
        cases = {
            "Train a random forest for machine learning classification": "Machine Learning",
            "Build a CNN neural network for deep learning": "Deep Learning",
            "Use medical AI for hospital diagnosis": "Healthcare AI",
            "Predict voltage in a power grid transformer": "Power Systems",
            "Improve product recommendation for an e-commerce marketplace": "E-commerce AI",
            "Tell me a short joke": "General",
        }
        for message, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(classify_topic(message), expected)


class FeedbackValidationTests(unittest.TestCase):
    def test_feedback_accepts_only_phase_2_values(self):
        valid = FeedbackRequest(
            interaction_id=str(ObjectId()),
            rating=4,
            correctness="Correct",
            length_type="To the Point",
        )
        self.assertEqual(valid.rating, 4)

        with self.assertRaises(ValidationError):
            FeedbackRequest(
                interaction_id=str(ObjectId()),
                rating=5,
                correctness="Maybe",
                length_type="Huge",
            )


class OAuthStateTests(unittest.TestCase):
    def test_signed_state_rejects_tampering(self):
        state = encode_oauth_state("test-only-secret")
        self.assertTrue(validate_oauth_state(state, "test-only-secret"))
        self.assertFalse(validate_oauth_state(state + "x", "test-only-secret"))


class ChatFlowTests(unittest.TestCase):
    @patch("backend.routes.chat.record_interaction")
    @patch("backend.routes.chat.save_chat", return_value=ObjectId())
    @patch("backend.routes.chat.generate_response", return_value="A neural network answer")
    @patch("backend.routes.chat.build_context_prompt", return_value="prompt")
    @patch("backend.routes.chat.get_pending_feedback", return_value=None)
    @patch("backend.routes.chat.ensure_active_session")
    def test_chat_stores_phase_2_fields(
        self,
        ensure_session,
        pending_feedback,
        context_prompt,
        model_response,
        save_chat_mock,
        record_interaction_mock,
    ):
        response = chat(ChatRequest(
            message="Explain a neural network",
            session_id="session-a",
            user_id="user-a",
        ))

        stored = save_chat_mock.call_args.args[0]
        for field in (
            "user_id", "session_id", "user_message", "llama_response",
            "timestamp", "request_start_time", "response_end_time",
            "response_time_seconds", "topic_label", "feedback",
        ):
            self.assertIn(field, stored)
        self.assertFalse(stored["feedback"]["submitted"])
        self.assertEqual(response["topic_label"], "Deep Learning")
        record_interaction_mock.assert_called_once_with(
            "session-a", "user-a", "Deep Learning"
        )

    @patch("backend.routes.chat.get_pending_feedback")
    @patch("backend.routes.chat.ensure_active_session")
    def test_chat_blocks_when_feedback_is_pending(self, ensure_session, pending_feedback):
        pending_id = ObjectId()
        pending_feedback.return_value = {"_id": pending_id}
        with self.assertRaises(HTTPException) as raised:
            chat(ChatRequest(
                message="Blocked message",
                session_id="session-a",
                user_id="user-a",
            ))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "feedback_required")


class PendingFeedbackStateTests(unittest.TestCase):
    @patch("backend.services.session_service._database")
    def test_new_session_has_no_pending_feedback(self, database_mock):
        chat_history = database_mock.return_value.__getitem__.return_value
        chat_history.find_one.return_value = None

        self.assertIsNone(get_pending_feedback("new-session", "user-a"))
        chat_history.find_one.assert_called_once_with(
            {"session_id": "new-session", "user_id": "user-a"},
            sort=[("timestamp", -1)],
        )

    @patch("backend.services.session_service._database")
    def test_submitted_latest_interaction_is_not_pending(self, database_mock):
        chat_history = database_mock.return_value.__getitem__.return_value
        chat_history.find_one.return_value = {
            "_id": ObjectId(),
            "feedback": {"submitted": True},
        }

        self.assertIsNone(get_pending_feedback("session-a", "user-a"))

    @patch("backend.services.session_service._database")
    def test_unsubmitted_latest_interaction_is_pending(self, database_mock):
        pending_interaction = {
            "_id": ObjectId(),
            "feedback": {"submitted": False},
        }
        chat_history = database_mock.return_value.__getitem__.return_value
        chat_history.find_one.return_value = pending_interaction

        self.assertIs(
            get_pending_feedback("session-a", "user-a"),
            pending_interaction,
        )


class SessionHistoryTests(unittest.TestCase):
    @patch("backend.services.session_service._database")
    def test_session_list_is_sorted_and_titled_from_first_message(self, database_mock):
        sessions = MagicMock()
        chats = MagicMock()
        cursor = MagicMock()
        database_mock.return_value.__getitem__.side_effect = {
            "sessions": sessions,
            "chat_history": chats,
        }.__getitem__
        sessions.find.return_value = cursor
        cursor.sort.return_value = [
            {"session_id": "session-a", "user_id": "user-a"},
            {"session_id": "session-b", "user_id": "user-a"},
        ]
        chats.find_one.side_effect = [
            {"user_message": "  Explain   neural networks clearly  "},
            None,
        ]

        result = get_user_sessions("user-a")

        sessions.find.assert_called_once_with({"user_id": "user-a"})
        cursor.sort.assert_called_once_with("updated_at", -1)
        self.assertEqual(result[0]["title"], "Explain neural networks clearly")
        self.assertEqual(result[1]["title"], "New chat")
        chats.find_one.assert_any_call(
            {"session_id": "session-a", "user_id": "user-a"},
            sort=[("timestamp", 1)],
        )

    @patch("backend.services.session_service._database")
    def test_long_session_title_is_limited(self, database_mock):
        sessions = MagicMock()
        chats = MagicMock()
        cursor = MagicMock()
        database_mock.return_value.__getitem__.side_effect = {
            "sessions": sessions,
            "chat_history": chats,
        }.__getitem__
        sessions.find.return_value = cursor
        cursor.sort.return_value = [
            {"session_id": "session-a", "user_id": "user-a"},
        ]
        chats.find_one.return_value = {"user_message": "x" * 60}

        result = get_user_sessions("user-a")

        self.assertEqual(len(result[0]["title"]), 40)
        self.assertTrue(result[0]["title"].endswith("..."))

    @patch("backend.services.session_service._database")
    def test_history_is_owned_filtered_and_sorted_oldest_first(self, database_mock):
        sessions = MagicMock()
        chats = MagicMock()
        cursor = MagicMock()
        interaction = {"_id": ObjectId(), "session_id": "session-a"}

        database_mock.return_value.__getitem__.side_effect = {
            "sessions": sessions,
            "chat_history": chats,
        }.__getitem__
        sessions.find_one.return_value = {
            "session_id": "session-a",
            "user_id": "user-a",
            "status": "active",
        }
        chats.find.return_value = cursor
        cursor.sort.return_value = [interaction]

        session, messages = get_session_history("session-a", "user-a")

        self.assertEqual(session["status"], "active")
        self.assertEqual(messages, [interaction])
        chats.find.assert_called_once_with({
            "session_id": "session-a",
            "user_id": "user-a",
        })
        cursor.sort.assert_called_once_with("timestamp", 1)

    @patch("backend.services.session_service._database")
    def test_history_rejects_a_different_session_owner(self, database_mock):
        sessions = MagicMock()
        database_mock.return_value.__getitem__.return_value = sessions
        sessions.find_one.return_value = {
            "session_id": "session-a",
            "user_id": "user-b",
        }

        with self.assertRaises(SessionOwnershipError):
            get_session_history("session-a", "user-a")

    @patch("backend.routes.sessions.get_session_history")
    def test_history_endpoint_reports_latest_pending_interaction(self, history_mock):
        interaction_id = ObjectId()
        now = datetime.now(timezone.utc)
        history_mock.return_value = (
            {
                "session_id": "session-a",
                "user_id": "user-a",
                "status": "active",
            },
            [{
                "_id": interaction_id,
                "session_id": "session-a",
                "user_id": "user-a",
                "user_message": "Hello",
                "llama_response": "Hi",
                "timestamp": now,
                "feedback": {"submitted": False, "submitted_at": None},
            }],
        )

        response = history("session-a", "user-a")

        self.assertTrue(response["pending_feedback"])
        self.assertEqual(response["pending_interaction_id"], str(interaction_id))
        self.assertEqual(response["message_count"], 1)
        self.assertEqual(response["messages"][0]["timestamp"], now.isoformat())

    @patch("backend.routes.sessions.get_session_history")
    def test_history_endpoint_clears_pending_after_feedback(self, history_mock):
        history_mock.return_value = (
            {
                "session_id": "session-a",
                "user_id": "user-a",
                "status": "active",
            },
            [{
                "_id": ObjectId(),
                "feedback": {"submitted": True},
            }],
        )

        response = history("session-a", "user-a")

        self.assertFalse(response["pending_feedback"])
        self.assertIsNone(response["pending_interaction_id"])

    @patch("backend.routes.sessions.get_session_history")
    def test_empty_session_history_has_no_pending_feedback(self, history_mock):
        history_mock.return_value = (
            {
                "session_id": "new-session",
                "user_id": "user-a",
                "status": "active",
            },
            [],
        )

        response = history("new-session", "user-a")

        self.assertEqual(response["messages"], [])
        self.assertFalse(response["pending_feedback"])
        self.assertIsNone(response["pending_interaction_id"])


class OllamaErrorTests(unittest.TestCase):
    @patch("backend.services.ollama_service.requests.post", side_effect=requests.Timeout())
    def test_timeout_has_specific_error(self, post_mock):
        with self.assertRaises(OllamaTimeoutError):
            generate_response("test prompt")


if __name__ == "__main__":
    unittest.main()
