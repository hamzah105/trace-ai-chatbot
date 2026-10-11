"""Pure unit tests for Phase 3 metric calculations."""

import json
import unittest

from backend.analytics.metrics import compute_session_metrics


def interaction(number, **changes):
    """Create one normalized analytics record with no feedback by default."""
    record = {
        "interaction_id": f"interaction-{number}",
        "interaction_number": number,
        "topic_label": "General",
        "phase": "Start",
        "correctness": None,
        "feedback_submitted": False,
        "rating": None,
        "length_type": None,
        "response_time_seconds": None,
    }
    record.update(changes)
    return record


class Phase3MetricsTests(unittest.TestCase):
    def test_reference_dataset_computes_reply_topic_phase_and_core_metrics(self):
        records = [
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

        metrics = compute_session_metrics(records)

        self.assertEqual(set(metrics), {
            "summary", "accuracy_per_reply", "accuracy_by_topic",
            "accuracy_by_phase", "correctness", "response_time", "ratings",
            "length_distribution",
        })
        self.assertEqual(metrics["summary"], {
            "total_interactions": 3,
            "feedback_submitted_count": 3,
            "correctness_scored_count": 3,
            "rating_scored_count": 3,
            "length_scored_count": 3,
            "response_time_scored_count": 3,
        })

        replies = metrics["accuracy_per_reply"]
        self.assertEqual([row["interaction_id"] for row in replies], [
            "interaction-1", "interaction-2", "interaction-3",
        ])
        self.assertEqual([row["interaction_number"] for row in replies], [1, 2, 3])
        self.assertEqual([row["correctness"] for row in replies], [
            "Correct", "Partial", "Incorrect",
        ])
        self.assertEqual([row["accuracy_score"] for row in replies], [1.0, 0.5, 0.0])
        self.assertEqual([row["accuracy_percentage"] for row in replies], [100.0, 50.0, 0.0])

        topics = {row["topic_label"]: row for row in metrics["accuracy_by_topic"]}
        self.assertEqual(list(topics), ["Healthcare AI", "Machine Learning"])
        self.assertEqual(topics["Machine Learning"]["interaction_count"], 2)
        self.assertEqual(topics["Machine Learning"]["scored_interaction_count"], 2)
        self.assertAlmostEqual(topics["Machine Learning"]["accuracy_score"], 0.75)
        self.assertEqual(topics["Machine Learning"]["accuracy_percentage"], 75.0)
        self.assertEqual(topics["Healthcare AI"]["accuracy_percentage"], 0.0)

        phases = {row["phase"]: row for row in metrics["accuracy_by_phase"]}
        self.assertEqual(list(phases), ["Start", "Middle", "End"])
        self.assertEqual([phases[name]["accuracy_percentage"] for name in
                          ("Start", "Middle", "End")], [100.0, 50.0, 0.0])
        correctness = metrics["correctness"]
        self.assertEqual(correctness["correct_count"], 1)
        self.assertEqual(correctness["partial_count"], 1)
        self.assertEqual(correctness["incorrect_count"], 1)
        self.assertEqual(correctness["scored_reply_count"], 3)
        self.assertAlmostEqual(correctness["overall_correctness_score"], 0.5)
        self.assertEqual(correctness["overall_correctness_percentage"], 50.0)
        self.assertEqual(correctness["strict_correct_percentage"], 33.33)

        self.assertEqual(metrics["response_time"], {
            "count": 3, "average_seconds": 20.0, "minimum_seconds": 10.0,
            "maximum_seconds": 30.0, "median_seconds": 20.0,
        })
        self.assertEqual(metrics["ratings"]["count"], 3)
        self.assertEqual(metrics["ratings"]["average"], 3.0)
        self.assertEqual(metrics["ratings"]["distribution"], {
            "1": 0, "2": 1, "3": 1, "4": 1,
        })
        self.assertEqual(metrics["length_distribution"], {
            "Short": {"count": 1, "percentage": 33.33},
            "To the Point": {"count": 1, "percentage": 33.33},
            "Lengthy": {"count": 1, "percentage": 33.33},
        })

    def test_unscored_replies_have_null_accuracy_and_groups_remain_visible(self):
        metrics = compute_session_metrics([
            interaction(1, topic_label="Machine Learning", phase="Start"),
            interaction(2, topic_label="Machine Learning", phase="Start",
                        correctness="Correct", feedback_submitted=False),
            interaction(3, topic_label="Power Systems", phase="End",
                        correctness="Partial", feedback_submitted=True),
        ])

        self.assertIsNone(metrics["accuracy_per_reply"][0]["accuracy_score"])
        self.assertIsNone(metrics["accuracy_per_reply"][1]["accuracy_percentage"])
        groups = {row["topic_label"]: row for row in metrics["accuracy_by_topic"]}
        self.assertEqual(groups["Machine Learning"]["interaction_count"], 2)
        self.assertEqual(groups["Machine Learning"]["scored_interaction_count"], 0)
        self.assertIsNone(groups["Machine Learning"]["accuracy_score"])
        self.assertIsNone(groups["Machine Learning"]["accuracy_percentage"])
        phases = {row["phase"]: row for row in metrics["accuracy_by_phase"]}
        self.assertEqual(phases["Start"]["interaction_count"], 2)
        self.assertEqual(phases["Start"]["scored_interaction_count"], 0)
        self.assertIsNone(phases["Start"]["accuracy_percentage"])

    def test_only_true_submitted_feedback_is_eligible_and_metrics_have_independent_counts(self):
        stale = [
            interaction(number, correctness="Correct", rating=4,
                        length_type="Short", feedback_submitted=value,
                        response_time_seconds=number)
            for number, value in enumerate((False, "true", 1), start=1)
        ]
        metrics = compute_session_metrics(stale)

        self.assertEqual(metrics["summary"]["total_interactions"], 3)
        self.assertEqual(metrics["summary"]["feedback_submitted_count"], 0)
        self.assertEqual(metrics["summary"]["correctness_scored_count"], 0)
        self.assertEqual(metrics["summary"]["rating_scored_count"], 0)
        self.assertEqual(metrics["summary"]["length_scored_count"], 0)
        self.assertEqual(metrics["summary"]["response_time_scored_count"], 3)
        self.assertEqual(metrics["response_time"]["count"], 3)
        self.assertEqual(metrics["correctness"]["scored_reply_count"], 0)
        self.assertEqual(metrics["correctness"]["correct_count"], 0)
        self.assertEqual(metrics["ratings"]["count"], 0)
        self.assertEqual(metrics["length_distribution"]["Short"]["count"], 0)

    def test_feedback_submitted_count_does_not_require_valid_feedback_values(self):
        metrics = compute_session_metrics([
            interaction(1, feedback_submitted=True, correctness=None, rating=8,
                        length_type="Very long"),
            interaction(2, feedback_submitted=True, correctness="Correct", rating=4,
                        length_type="Short"),
        ])
        self.assertEqual(metrics["summary"]["feedback_submitted_count"], 2)
        self.assertEqual(metrics["summary"]["correctness_scored_count"], 1)
        self.assertEqual(metrics["summary"]["rating_scored_count"], 1)
        self.assertEqual(metrics["summary"]["length_scored_count"], 1)

    def test_submitted_feedback_components_have_independent_denominators(self):
        metrics = compute_session_metrics([
            interaction(1, correctness="Correct", feedback_submitted=True),
            interaction(2, rating=4, feedback_submitted=True),
            interaction(3, length_type="Short", feedback_submitted=True),
        ])

        self.assertEqual(metrics["summary"]["feedback_submitted_count"], 3)
        self.assertEqual(metrics["summary"]["correctness_scored_count"], 1)
        self.assertEqual(metrics["summary"]["rating_scored_count"], 1)
        self.assertEqual(metrics["summary"]["length_scored_count"], 1)
        self.assertEqual(metrics["correctness"]["scored_reply_count"], 1)
        self.assertEqual(metrics["ratings"]["count"], 1)
        self.assertEqual(metrics["length_distribution"]["Short"]["count"], 1)
        topic = metrics["accuracy_by_topic"][0]
        self.assertEqual(topic["topic_label"], "General")
        self.assertEqual(topic["interaction_count"], 3)
        self.assertEqual(topic["scored_interaction_count"], 1)
        self.assertEqual(topic["accuracy_percentage"], 100.0)

    def test_values_are_aggregated_at_full_precision_before_rounding(self):
        metrics = compute_session_metrics([
            interaction(1, correctness="Correct", feedback_submitted=True,
                        response_time_seconds=1.0004, rating=1),
            interaction(2, correctness="Incorrect", feedback_submitted=True,
                        response_time_seconds=1.0004, rating=1),
            interaction(3, correctness="Incorrect", feedback_submitted=True,
                        response_time_seconds=1.0014, rating=2),
        ])

        self.assertEqual(metrics["response_time"]["average_seconds"], 1.001)
        self.assertEqual(metrics["ratings"]["average"], 1.33)
        self.assertAlmostEqual(metrics["correctness"]["overall_correctness_score"], 1 / 3)
        self.assertEqual(metrics["correctness"]["overall_correctness_percentage"], 33.33)
        self.assertAlmostEqual(metrics["accuracy_by_phase"][0]["accuracy_score"], 1 / 3)
        self.assertEqual(metrics["accuracy_by_phase"][0]["accuracy_percentage"], 33.33)

    def test_non_hashable_feedback_values_are_ignored_safely(self):
        metrics = compute_session_metrics([
            interaction(1, feedback_submitted=True, correctness=["Correct"],
                        rating={"value": 4}, length_type=["Short"]),
        ])
        self.assertEqual(metrics["correctness"]["scored_reply_count"], 0)
        self.assertEqual(metrics["ratings"]["count"], 0)
        self.assertEqual(metrics["length_distribution"]["Short"]["count"], 0)
        self.assertIsNone(metrics["accuracy_per_reply"][0]["accuracy_score"])

    def test_no_scored_correctness_returns_null_scores_and_zero_counts(self):
        metrics = compute_session_metrics([
            interaction(1, correctness="Not a value", feedback_submitted=True),
        ])
        self.assertEqual(metrics["correctness"]["correct_count"], 0)
        self.assertEqual(metrics["correctness"]["partial_count"], 0)
        self.assertEqual(metrics["correctness"]["incorrect_count"], 0)
        self.assertEqual(metrics["correctness"]["scored_reply_count"], 0)
        self.assertIsNone(metrics["correctness"]["overall_correctness_score"])
        self.assertIsNone(metrics["correctness"]["overall_correctness_percentage"])
        self.assertIsNone(metrics["correctness"]["strict_correct_percentage"])

    def test_medians_cover_odd_even_sets_and_zero_is_a_valid_time(self):
        odd = compute_session_metrics([
            interaction(i, response_time_seconds=value)
            for i, value in enumerate((0, 10, 20), start=1)
        ])
        even = compute_session_metrics([
            interaction(i, response_time_seconds=value)
            for i, value in enumerate((0, 10, 20, 40), start=1)
        ])
        self.assertEqual(odd["response_time"]["median_seconds"], 10.0)
        self.assertEqual(odd["response_time"]["minimum_seconds"], 0.0)
        self.assertEqual(even["response_time"]["median_seconds"], 15.0)

    def test_invalid_times_are_ignored_and_huge_finite_values_stay_finite(self):
        invalid = [True, -1, float("inf"), float("nan"), "3.5", None]
        metrics = compute_session_metrics([
            interaction(i, response_time_seconds=value)
            for i, value in enumerate(invalid, start=1)
        ])
        self.assertEqual(metrics["response_time"]["count"], 0)
        self.assertIsNone(metrics["response_time"]["average_seconds"])
        self.assertIsNone(metrics["response_time"]["median_seconds"])

        huge = compute_session_metrics([
            interaction(1, response_time_seconds=1e308),
            interaction(2, response_time_seconds=1e308),
        ])
        self.assertEqual(huge["response_time"]["average_seconds"], 1e308)
        self.assertEqual(huge["response_time"]["median_seconds"], 1e308)
        json.dumps(huge, allow_nan=False)

    def test_ratings_require_submitted_integer_values_from_one_to_four(self):
        values = [1, 4, 0, 5, True, 2.0, "3"]
        metrics = compute_session_metrics([
            interaction(i, rating=value, feedback_submitted=True)
            for i, value in enumerate(values, start=1)
        ])
        self.assertEqual(metrics["ratings"]["count"], 2)
        self.assertEqual(metrics["ratings"]["average"], 2.5)
        self.assertEqual(metrics["ratings"]["distribution"], {
            "1": 1, "2": 0, "3": 0, "4": 1,
        })

    def test_length_distribution_uses_only_valid_submitted_values_as_denominator(self):
        values = ["Short", "To the Point", "Lengthy", "Long", None]
        metrics = compute_session_metrics([
            interaction(i, length_type=value, feedback_submitted=True)
            for i, value in enumerate(values, start=1)
        ])
        self.assertEqual(metrics["summary"]["length_scored_count"], 3)
        self.assertEqual(metrics["length_distribution"], {
            "Short": {"count": 1, "percentage": 33.33},
            "To the Point": {"count": 1, "percentage": 33.33},
            "Lengthy": {"count": 1, "percentage": 33.33},
        })

    def test_empty_input_has_complete_safe_shape_and_is_json_serializable(self):
        metrics = compute_session_metrics([])
        self.assertEqual(metrics["summary"], {
            "total_interactions": 0,
            "feedback_submitted_count": 0,
            "correctness_scored_count": 0,
            "rating_scored_count": 0,
            "length_scored_count": 0,
            "response_time_scored_count": 0,
        })
        self.assertEqual(metrics["accuracy_per_reply"], [])
        self.assertEqual(metrics["accuracy_by_topic"], [])
        self.assertEqual(metrics["accuracy_by_phase"], [])
        self.assertIsNone(metrics["correctness"]["overall_correctness_percentage"])
        self.assertIsNone(metrics["correctness"]["strict_correct_percentage"])
        self.assertIsNone(metrics["response_time"]["average_seconds"])
        self.assertIsNone(metrics["response_time"]["minimum_seconds"])
        self.assertIsNone(metrics["response_time"]["maximum_seconds"])
        self.assertIsNone(metrics["response_time"]["median_seconds"])
        self.assertIsNone(metrics["ratings"]["average"])
        self.assertEqual(metrics["ratings"]["distribution"], {
            "1": 0, "2": 0, "3": 0, "4": 0,
        })
        self.assertEqual(metrics["length_distribution"], {
            name: {"count": 0, "percentage": 0.0}
            for name in ("Short", "To the Point", "Lengthy")
        })
        json.dumps(metrics, allow_nan=False)

    def test_computation_is_deterministic_and_does_not_mutate_records(self):
        records = [
            interaction(1, topic_label="z-topic", correctness="Correct",
                        feedback_submitted=True, rating=4, length_type="Short",
                        response_time_seconds=1),
            interaction(2, topic_label="a-topic", phase="End",
                        correctness="Incorrect", feedback_submitted=True,
                        rating=2, length_type="Lengthy", response_time_seconds=3),
        ]
        before = json.loads(json.dumps(records))
        first = compute_session_metrics(records)
        second = compute_session_metrics(records)
        self.assertEqual(first, second)
        self.assertEqual(records, before)
        self.assertEqual([row["topic_label"] for row in first["accuracy_by_topic"]],
                         ["a-topic", "z-topic"])
        json.dumps(first, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
