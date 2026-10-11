"""Pure FR20 chart and FR21 overview tests without database or web services."""

import copy
import json
import unittest

from backend.analytics.charts import build_session_charts
from backend.analytics.dashboard import build_session_overview
from backend.analytics.metrics import compute_session_metrics


CHART_KEYS = (
    "topic_distribution", "accuracy_per_topic", "accuracy_vs_phase",
    "correctness_per_reply", "response_time_trend", "rating_distribution",
    "length_preference",
)


def interaction(number, **changes):
    row = {
        "interaction_id": f"interaction-{number}", "interaction_number": number,
        "topic_label": "General", "phase": "Start", "feedback_submitted": False,
        "correctness": None, "rating": None, "length_type": None,
        "response_time_seconds": None,
    }
    row.update(changes)
    return row


def reference():
    return [
        interaction(1, topic_label="Machine Learning", phase="Start",
                    feedback_submitted=True, correctness="Correct", rating=4,
                    length_type="To the Point", response_time_seconds=10),
        interaction(2, topic_label="Machine Learning", phase="Middle",
                    feedback_submitted=True, correctness="Partial", rating=3,
                    length_type="Short", response_time_seconds=20),
        interaction(3, topic_label="Healthcare AI", phase="End",
                    feedback_submitted=True, correctness="Incorrect", rating=2,
                    length_type="Lengthy", response_time_seconds=30),
    ]


def values(charts, name):
    return charts[name]["datasets"][0]["values"]


class ChartsTests(unittest.TestCase):
    def test_seven_charts_have_one_coherent_json_safe_schema(self):
        rows = reference()
        charts = build_session_charts(rows, compute_session_metrics(rows))
        self.assertEqual(tuple(charts), CHART_KEYS)
        self.assertEqual([charts[key]["type"] for key in CHART_KEYS],
                         ["pie", "bar", "line", "bar", "line", "bar", "pie"])
        for chart in charts.values():
            self.assertEqual(set(chart), {"title", "type", "labels", "datasets", "empty", "metadata"})
            self.assertEqual(len(chart["datasets"]), 1)
            self.assertEqual(len(chart["labels"]), len(chart["datasets"][0]["values"]))
            self.assertFalse(chart["empty"])
            self.assertEqual(chart["metadata"]["y_min"], 0)
            if chart["metadata"]["unit"] == "percent":
                self.assertEqual(chart["metadata"]["y_max"], 100)
        json.dumps(charts, allow_nan=False)

    def test_reference_values_match_existing_metrics_and_normalized_rows(self):
        rows = reference()
        metrics = compute_session_metrics(rows)
        charts = build_session_charts(rows, metrics)
        self.assertEqual(charts["topic_distribution"]["labels"],
                         ["Healthcare AI", "Machine Learning"])
        self.assertEqual(values(charts, "topic_distribution"), [1, 2])
        self.assertEqual(charts["topic_distribution"]["metadata"]["total_count"], 3)
        self.assertEqual(values(charts, "accuracy_per_topic"), [0.0, 75.0])
        self.assertEqual(charts["accuracy_vs_phase"]["labels"], ["Start", "Middle", "End"])
        self.assertEqual(values(charts, "accuracy_vs_phase"), [100.0, 50.0, 0.0])
        self.assertEqual(values(charts, "correctness_per_reply"), [100.0, 50.0, 0.0])
        self.assertEqual(values(charts, "response_time_trend"), [10, 20, 30])
        self.assertEqual(values(charts, "rating_distribution"), [0, 1, 1, 1])
        self.assertEqual(values(charts, "length_preference"), [1, 1, 1])
        self.assertEqual(charts["length_preference"]["metadata"]["percentages"],
                         [33.33, 33.33, 33.33])
        self.assertEqual(charts["rating_distribution"]["metadata"]["average_rating"], 3.0)

    def test_accuracy_null_is_distinct_from_measured_zero(self):
        rows = [interaction(1, topic_label="General", correctness="Incorrect",
                            feedback_submitted=True),
                interaction(2, topic_label="Power Systems", correctness="Correct",
                            feedback_submitted=False)]
        charts = build_session_charts(rows, compute_session_metrics(rows))
        self.assertEqual(values(charts, "accuracy_per_topic"), [0.0, None])
        self.assertFalse(charts["accuracy_per_topic"]["empty"])
        self.assertEqual(values(charts, "correctness_per_reply"), [0.0, None])

    def test_all_null_accuracy_is_empty_but_all_zero_accuracy_is_measured(self):
        rows = [interaction(1, topic_label="General", phase="Start",
                            correctness="Incorrect", feedback_submitted=False),
                interaction(2, topic_label="Power Systems", phase="End",
                            correctness="Incorrect", feedback_submitted=False)]
        all_null = build_session_charts(rows, compute_session_metrics(rows))
        for key in ("accuracy_per_topic", "accuracy_vs_phase", "correctness_per_reply"):
            self.assertTrue(all_null[key]["empty"], key)
            self.assertTrue(all(value is None for value in values(all_null, key)))

        for row in rows:
            row["feedback_submitted"] = True
        all_zero = build_session_charts(rows, compute_session_metrics(rows))
        for key in ("accuracy_per_topic", "accuracy_vs_phase", "correctness_per_reply"):
            self.assertFalse(all_zero[key]["empty"], key)
            self.assertTrue(all(value == 0.0 for value in values(all_zero, key)))

    def test_empty_session_keeps_rating_and_length_categories(self):
        charts = build_session_charts([], compute_session_metrics([]))
        self.assertEqual(charts["rating_distribution"]["labels"], ["1", "2", "3", "4"])
        self.assertEqual(values(charts, "rating_distribution"), [0, 0, 0, 0])
        self.assertEqual(charts["length_preference"]["labels"],
                         ["Short", "To the Point", "Lengthy"])
        self.assertEqual(values(charts, "length_preference"), [0, 0, 0])
        for key in CHART_KEYS:
            self.assertTrue(charts[key]["empty"], key)
        for key in CHART_KEYS[:5]:
            self.assertEqual(charts[key]["labels"], [])
            self.assertEqual(values(charts, key), [])
        json.dumps(charts, allow_nan=False)

    def test_zero_seconds_is_a_measured_timing_even_without_feedback(self):
        rows = [interaction(2, response_time_seconds=None),
                interaction(1, response_time_seconds=0)]
        chart = build_session_charts(rows, compute_session_metrics(rows))["response_time_trend"]
        self.assertEqual(chart["labels"], ["Reply 1", "Reply 2"])
        self.assertEqual(chart["datasets"][0]["values"], [0, None])
        self.assertFalse(chart["empty"])
        self.assertEqual(chart["metadata"]["average_seconds"], 0.0)

    def test_metric_order_and_precision_are_copied_without_recalculation(self):
        rows = reference()
        metrics = compute_session_metrics(rows)
        metrics["accuracy_by_phase"].reverse()
        metrics["accuracy_by_phase"][0]["accuracy_percentage"] = 12.345
        metrics["accuracy_by_topic"][0]["accuracy_percentage"] = None
        metrics["accuracy_per_reply"].reverse()
        metrics["accuracy_per_reply"][0]["accuracy_percentage"] = 23.456
        charts = build_session_charts(rows, metrics)
        self.assertEqual(charts["accuracy_vs_phase"]["labels"], ["Start", "Middle", "End"])
        self.assertEqual(values(charts, "accuracy_vs_phase")[-1], 12.345)
        self.assertIsNone(values(charts, "accuracy_per_topic")[0])
        self.assertEqual(charts["correctness_per_reply"]["labels"],
                         ["Reply 1", "Reply 2", "Reply 3"])
        self.assertEqual(values(charts, "correctness_per_reply")[-1], 23.456)

    def test_metadata_is_small_and_contains_no_chat_text_or_secrets(self):
        rows = reference()
        rows[0].update(user_message="secret question", llama_response="secret answer",
                       password_hash="secret password", oauth_token="secret token")
        charts = build_session_charts(rows, compute_session_metrics(rows))
        points = charts["correctness_per_reply"]["metadata"]["points"]
        self.assertEqual(set(points[0]), {"interaction_id", "interaction_number",
                                          "topic_label", "phase", "correctness"})
        payload = json.dumps(charts)
        for secret in ("secret question", "secret answer", "secret password", "secret token"):
            self.assertNotIn(secret, payload)

    def test_inputs_are_unchanged_and_outputs_are_fresh(self):
        rows = reference()
        metrics = compute_session_metrics(rows)
        rows_before, metrics_before = copy.deepcopy(rows), copy.deepcopy(metrics)
        first = build_session_charts(rows, metrics)
        second = build_session_charts(rows, metrics)
        first["correctness_per_reply"]["metadata"]["points"][0]["phase"] = "changed"
        first["rating_distribution"]["datasets"][0]["values"][0] = 99
        self.assertEqual(rows, rows_before)
        self.assertEqual(metrics, metrics_before)
        self.assertEqual(second, build_session_charts(rows, metrics))


class DashboardOverviewTests(unittest.TestCase):
    def test_reference_overview_copies_metrics(self):
        metrics = compute_session_metrics(reference())
        overview = build_session_overview(metrics)
        self.assertEqual(overview, {
            "total_interactions": 3, "feedback_submitted_count": 3,
            "weighted_accuracy_percentage": 50.0,
            "strict_correct_percentage": 33.33,
            "average_rating": 3.0,
            "average_response_time_seconds": 20.0,
            "dominant_topic": "Machine Learning",
            "dominant_length_preference": "Short",
        })

    def test_empty_overview_has_nulls_for_unavailable_values(self):
        overview = build_session_overview(compute_session_metrics([]))
        self.assertEqual(overview["total_interactions"], 0)
        self.assertEqual(overview["feedback_submitted_count"], 0)
        for key in ("weighted_accuracy_percentage", "strict_correct_percentage",
                    "average_rating", "average_response_time_seconds", "dominant_topic",
                    "dominant_length_preference"):
            self.assertIsNone(overview[key])

    def test_dominant_topic_ties_alphabetically_and_length_uses_fixed_order(self):
        rows = [interaction(1, topic_label="Power Systems", length_type="Lengthy",
                            feedback_submitted=True),
                interaction(2, topic_label="Healthcare AI", length_type="Short",
                            feedback_submitted=True)]
        overview = build_session_overview(compute_session_metrics(rows))
        self.assertEqual(overview["dominant_topic"], "Healthcare AI")
        self.assertEqual(overview["dominant_length_preference"], "Short")


if __name__ == "__main__":
    unittest.main()
