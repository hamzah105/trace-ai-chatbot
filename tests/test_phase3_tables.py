"""Pure presentation tests for Phase 3 FR19 analytics tables."""

import copy
import json
import unittest

from backend.analytics.metrics import compute_session_metrics
from backend.analytics.tables import build_session_tables


TABLE_KEYS = (
    "topic_vs_accuracy",
    "reply_correctness",
    "phase_wise_accuracy",
    "response_time_summary",
    "rating_distribution",
    "length_preference",
)


def interaction(number, **changes):
    """Build a flat normalized interaction used by the analytics services."""
    record = {
        "interaction_id": f"interaction-{number}",
        "interaction_number": number,
        "topic_label": "General",
        "phase": "Start",
        "user_message": "",
        "llama_response": "",
        "correctness": None,
        "feedback_submitted": False,
        "rating": None,
        "length_type": None,
        "response_time_seconds": None,
    }
    record.update(changes)
    return record


def reference_interactions():
    return [
        interaction(
            1, topic_label="Machine Learning", phase="Start",
            correctness="Correct", feedback_submitted=True, rating=4,
            length_type="To the Point", response_time_seconds=10,
        ),
        interaction(
            2, topic_label="Machine Learning", phase="Middle",
            correctness="Partial", feedback_submitted=True, rating=3,
            length_type="Short", response_time_seconds=20,
        ),
        interaction(
            3, topic_label="Healthcare AI", phase="End",
            correctness="Incorrect", feedback_submitted=True, rating=2,
            length_type="Lengthy", response_time_seconds=30,
        ),
    ]


def table_columns(table):
    return [column["key"] for column in table["columns"]]


def metric_fixture(**changes):
    """Return the complete metrics-engine shape with selected sentinel values."""
    metrics = {
        "accuracy_per_reply": [],
        "accuracy_by_topic": [],
        "accuracy_by_phase": [],
        "response_time": {
            "count": 0, "average_seconds": None, "minimum_seconds": None,
            "maximum_seconds": None, "median_seconds": None,
        },
        "ratings": {
            "count": 0,
            "distribution": {str(value): 0 for value in range(1, 5)},
        },
        "length_distribution": {
            label: {"count": 0, "percentage": 0.0}
            for label in ("Short", "To the Point", "Lengthy")
        },
    }
    metrics.update(changes)
    return metrics


class Phase3TablesTests(unittest.TestCase):
    def test_all_six_tables_have_the_stable_generic_table_shape(self):
        tables = build_session_tables([], compute_session_metrics([]))

        self.assertEqual(tuple(tables), TABLE_KEYS)
        for table in tables.values():
            with self.subTest(title=table.get("title")):
                self.assertIsInstance(table["title"], str)
                self.assertTrue(table["title"])
                self.assertIsInstance(table["columns"], list)
                self.assertTrue(table["columns"])
                self.assertTrue(all(set(column) == {"key", "label"}
                                    for column in table["columns"]))
                self.assertTrue(all(isinstance(column["key"], str)
                                    and isinstance(column["label"], str)
                                    for column in table["columns"]))
                self.assertIsInstance(table["rows"], list)
                self.assertEqual(table["row_count"], len(table["rows"]))
                self.assertTrue(all(isinstance(row, dict) for row in table["rows"]))

    def test_reference_dataset_transforms_all_six_tables(self):
        interactions = reference_interactions()
        tables = build_session_tables(interactions, compute_session_metrics(interactions))

        topic_rows = {row["topic_label"]: row
                      for row in tables["topic_vs_accuracy"]["rows"]}
        self.assertEqual(topic_rows, {
            "Healthcare AI": {
                "topic_label": "Healthcare AI", "interaction_count": 1,
                "scored_interaction_count": 1, "accuracy_percentage": 0.0,
            },
            "Machine Learning": {
                "topic_label": "Machine Learning", "interaction_count": 2,
                "scored_interaction_count": 2, "accuracy_percentage": 75.0,
            },
        })

        reply_table = tables["reply_correctness"]
        self.assertEqual(reply_table["row_count"], 3)
        self.assertEqual(table_columns(reply_table), [
            "interaction_number", "topic_label", "phase", "correctness",
            "accuracy_percentage", "rating", "length_type",
            "response_time_seconds",
        ])
        self.assertEqual([
            (row["interaction_number"], row["topic_label"], row["phase"],
             row["correctness"], row["accuracy_percentage"], row["rating"],
             row["length_type"], row["response_time_seconds"])
            for row in reply_table["rows"]
        ], [
            (1, "Machine Learning", "Start", "Correct", 100.0, 4, "To the Point", 10),
            (2, "Machine Learning", "Middle", "Partial", 50.0, 3, "Short", 20),
            (3, "Healthcare AI", "End", "Incorrect", 0.0, 2, "Lengthy", 30),
        ])
        self.assertEqual([row["phase"] for row in
                          tables["phase_wise_accuracy"]["rows"]],
                         ["Start", "Middle", "End"])
        self.assertEqual([row["accuracy_percentage"] for row in
                          tables["phase_wise_accuracy"]["rows"]], [100.0, 50.0, 0.0])
        self.assertEqual(tables["response_time_summary"]["rows"], [
            {"metric": "Average", "seconds": 20.0},
            {"metric": "Minimum", "seconds": 10.0},
            {"metric": "Maximum", "seconds": 30.0},
            {"metric": "Median", "seconds": 20.0},
        ])
        self.assertEqual(tables["response_time_summary"]["valid_response_count"], 3)
        self.assertEqual(tables["rating_distribution"]["rows"], [
            {"rating": 1, "count": 0, "percentage": 0.0},
            {"rating": 2, "count": 1, "percentage": 33.33},
            {"rating": 3, "count": 1, "percentage": 33.33},
            {"rating": 4, "count": 1, "percentage": 33.33},
        ])
        self.assertEqual(tables["length_preference"]["rows"], [
            {"length_type": "Short", "count": 1, "percentage": 33.33},
            {"length_type": "To the Point", "count": 1, "percentage": 33.33},
            {"length_type": "Lengthy", "count": 1, "percentage": 33.33},
        ])

    def test_topic_table_copies_metric_values_including_null_accuracy(self):
        metrics = metric_fixture(accuracy_by_topic=[
                {"topic_label": "Custom", "interaction_count": 7,
                 "scored_interaction_count": 3, "accuracy_percentage": 12.345},
                {"topic_label": "Unscored", "interaction_count": 2,
                 "scored_interaction_count": 0, "accuracy_percentage": None},
            ])
        rows = build_session_tables([], metrics)["topic_vs_accuracy"]["rows"]
        self.assertEqual(rows, [
            {"topic_label": "Custom", "interaction_count": 7,
             "scored_interaction_count": 3, "accuracy_percentage": 12.345},
            {"topic_label": "Unscored", "interaction_count": 2,
             "scored_interaction_count": 0, "accuracy_percentage": None},
        ])

    def test_reply_accuracy_joins_by_interaction_id_despite_metric_order(self):
        interactions = [
            interaction(2, interaction_id="reply-b", feedback_submitted=True,
                        correctness="Correct"),
            interaction(1, interaction_id="reply-a", feedback_submitted=True,
                        correctness="Partial"),
        ]
        metrics = metric_fixture(accuracy_per_reply=[
                {"interaction_id": "reply-b", "interaction_number": 1,
                 "accuracy_percentage": 21.5},
                {"interaction_id": "reply-a", "interaction_number": 2,
                 "accuracy_percentage": 98.25},
            ])

        rows = build_session_tables(interactions, metrics)["reply_correctness"]["rows"]
        self.assertEqual([row["interaction_number"] for row in rows], [1, 2])
        self.assertEqual([row["accuracy_percentage"] for row in rows], [98.25, 21.5])

    def test_missing_id_falls_back_to_unique_number_but_conflicts_do_not(self):
        interactions = [
            interaction(1, interaction_id=None, feedback_submitted=True),
            interaction(2, interaction_id="known", feedback_submitted=True),
            interaction(3, interaction_id=None, feedback_submitted=True),
        ]
        metrics = metric_fixture(accuracy_per_reply=[
                {"interaction_id": None, "interaction_number": 3,
                 "accuracy_percentage": 30.0},
                {"interaction_id": "different-known-id", "interaction_number": 2,
                 "accuracy_percentage": 22.0},
                {"interaction_id": None, "interaction_number": 1,
                 "accuracy_percentage": 10.0},
            ])

        rows = build_session_tables(interactions, metrics)["reply_correctness"]["rows"]
        self.assertEqual([row["accuracy_percentage"] for row in rows],
                         [10.0, None, 30.0])

    def test_ambiguous_duplicate_ids_fall_back_by_unique_interaction_number(self):
        interactions = [
            interaction(4, interaction_id="duplicate", feedback_submitted=True),
            interaction(5, interaction_id="duplicate", feedback_submitted=True),
        ]
        metrics = metric_fixture(accuracy_per_reply=[
            {"interaction_id": "duplicate", "interaction_number": 5,
             "accuracy_percentage": 55.0},
            {"interaction_id": "duplicate", "interaction_number": 4,
             "accuracy_percentage": 44.0},
        ])

        rows = build_session_tables(interactions, metrics)["reply_correctness"]["rows"]
        self.assertEqual([row["accuracy_percentage"] for row in rows], [44.0, 55.0])

    def test_reply_table_retains_unsubmitted_rows_and_suppresses_feedback_values(self):
        interactions = [
            interaction(1, correctness="Correct", rating=4, length_type="Short",
                        feedback_submitted=False, response_time_seconds=0),
            interaction(2, correctness=None, rating=None, length_type=None,
                        feedback_submitted=True, response_time_seconds=None),
        ]
        tables = build_session_tables(interactions, compute_session_metrics(interactions))
        rows = tables["reply_correctness"]["rows"]

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["feedback_submitted"], False)
        self.assertIsNone(rows[0]["correctness"])
        self.assertIsNone(rows[0]["accuracy_percentage"])
        self.assertIsNone(rows[0]["rating"])
        self.assertIsNone(rows[0]["length_type"])
        self.assertEqual(rows[0]["response_time_seconds"], 0)
        self.assertTrue(rows[1]["feedback_submitted"])
        self.assertIsNone(rows[1]["correctness"])
        self.assertIsNone(rows[1]["rating"])
        self.assertIsNone(rows[1]["length_type"])
        self.assertIsNone(rows[1]["response_time_seconds"])

    def test_reply_table_does_not_include_full_chat_text(self):
        long_text = "secret chat detail " * 100
        interactions = [interaction(
            1, user_message=long_text, llama_response=long_text,
            feedback_submitted=True, correctness="Correct",
        )]
        table = build_session_tables(
            interactions, compute_session_metrics(interactions),
        )["reply_correctness"]

        self.assertNotIn("user_message", table["rows"][0])
        self.assertNotIn("llama_response", table["rows"][0])
        self.assertNotIn(long_text, json.dumps(table))

    def test_phase_table_keeps_metrics_values_and_orders_only_represented_phases(self):
        metrics = metric_fixture(accuracy_by_phase=[
                {"phase": "End", "interaction_count": 9,
                 "scored_interaction_count": 4, "accuracy_percentage": None},
                {"phase": "Start", "interaction_count": 2,
                 "scored_interaction_count": 1, "accuracy_percentage": 61.123},
            ])

        rows = build_session_tables([], metrics)["phase_wise_accuracy"]["rows"]
        self.assertEqual([row["phase"] for row in rows], ["Start", "End"])
        self.assertEqual(rows, [
            {"phase": "Start", "interaction_count": 2,
             "scored_interaction_count": 1, "accuracy_percentage": 61.123},
            {"phase": "End", "interaction_count": 9,
             "scored_interaction_count": 4, "accuracy_percentage": None},
        ])

    def test_response_time_table_copies_metric_sentinels_and_keeps_missing_null(self):
        metrics = metric_fixture(response_time={
                "count": 17, "average_seconds": 123.456789,
                "minimum_seconds": None, "maximum_seconds": 987.654,
                "median_seconds": None,
            })

        table = build_session_tables([], metrics)["response_time_summary"]
        self.assertEqual(table["valid_response_count"], 17)
        self.assertEqual(table["rows"], [
            {"metric": "Average", "seconds": 123.456789},
            {"metric": "Minimum", "seconds": None},
            {"metric": "Maximum", "seconds": 987.654},
            {"metric": "Median", "seconds": None},
        ])

    def test_rating_distribution_always_has_four_rows_and_handles_zero_count(self):
        interactions = reference_interactions()
        metrics = compute_session_metrics(interactions)
        rows = build_session_tables(interactions, metrics)["rating_distribution"]["rows"]
        self.assertEqual([row["rating"] for row in rows], [1, 2, 3, 4])
        self.assertEqual([row["percentage"] for row in rows],
                         [0.0, 33.33, 33.33, 33.33])

        no_ratings = copy.deepcopy(metrics)
        no_ratings["ratings"] = {"count": 0, "distribution": {
            "1": 0, "2": 0, "3": 0, "4": 0,
        }}
        zero_rows = build_session_tables(interactions, no_ratings)[
            "rating_distribution"]["rows"]
        self.assertEqual([row["count"] for row in zero_rows], [0, 0, 0, 0])
        self.assertEqual([row["percentage"] for row in zero_rows],
                         [0.0, 0.0, 0.0, 0.0])

    def test_length_preference_copies_metrics_in_required_order(self):
        metrics = metric_fixture(length_distribution={
                "Lengthy": {"count": 8, "percentage": 77.77},
                "Short": {"count": 3, "percentage": 22.23},
                "To the Point": {"count": 0, "percentage": 0.0},
            })

        rows = build_session_tables([], metrics)["length_preference"]["rows"]
        self.assertEqual([row["length_type"] for row in rows],
                         ["Short", "To the Point", "Lengthy"])
        self.assertEqual([row["count"] for row in rows], [3, 0, 8])
        self.assertEqual([row["percentage"] for row in rows], [22.23, 0.0, 77.77])

    def test_empty_session_produces_safe_json_serializable_tables(self):
        tables = build_session_tables([], compute_session_metrics([]))
        self.assertEqual(tables["topic_vs_accuracy"]["rows"], [])
        self.assertEqual(tables["reply_correctness"]["rows"], [])
        self.assertEqual(tables["phase_wise_accuracy"]["rows"], [])
        self.assertEqual(tables["response_time_summary"]["valid_response_count"], 0)
        self.assertTrue(all(row["seconds"] is None for row in
                            tables["response_time_summary"]["rows"]))
        self.assertEqual(tables["rating_distribution"]["rows"], [
            {"rating": 1, "count": 0, "percentage": 0.0},
            {"rating": 2, "count": 0, "percentage": 0.0},
            {"rating": 3, "count": 0, "percentage": 0.0},
            {"rating": 4, "count": 0, "percentage": 0.0},
        ])
        self.assertEqual(tables["length_preference"]["rows"], [
            {"length_type": "Short", "count": 0, "percentage": 0.0},
            {"length_type": "To the Point", "count": 0, "percentage": 0.0},
            {"length_type": "Lengthy", "count": 0, "percentage": 0.0},
        ])
        json.dumps(tables, allow_nan=False)

    def test_output_is_deterministic_does_not_mutate_inputs_and_is_fresh(self):
        interactions = reference_interactions()
        metrics = compute_session_metrics(interactions)
        interactions_before = copy.deepcopy(interactions)
        metrics_before = copy.deepcopy(metrics)

        first = build_session_tables(interactions, metrics)
        second = build_session_tables(interactions, metrics)
        self.assertEqual(first, second)
        self.assertEqual(interactions, interactions_before)
        self.assertEqual(metrics, metrics_before)
        json.dumps(first, allow_nan=False)

        first["reply_correctness"]["rows"][0]["correctness"] = "changed"
        first["reply_correctness"]["columns"][0]["label"] = "changed"
        third = build_session_tables(interactions, metrics)
        self.assertEqual(third, second)
        self.assertNotEqual(third["reply_correctness"]["rows"][0]["correctness"],
                            "changed")
        self.assertNotEqual(third["reply_correctness"]["columns"][0]["label"],
                            "changed")


if __name__ == "__main__":
    unittest.main()
