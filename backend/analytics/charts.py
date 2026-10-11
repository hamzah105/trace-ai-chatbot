"""Pure FR20 chart specifications over normalized interactions and metrics.

Values and percentages come from the existing analytics layers. Missing
measurements remain ``None`` so a renderer can distinguish them from zero.
"""

from collections import Counter
from math import isfinite


PHASES = ("Start", "Middle", "End")
LENGTH_TYPES = ("Short", "To the Point", "Lengthy")


def _measured(values):
    return any(isinstance(value, (int, float)) and not isinstance(value, bool)
               and isfinite(value) for value in values)


def _chart(title, chart_type, labels, dataset_label, values, unit, *, counts=False,
           **metadata):
    """Build the shared chart schema with a fresh dataset and metadata object."""
    return {
        "title": title,
        "type": chart_type,
        "labels": list(labels),
        "datasets": [{"label": dataset_label, "values": list(values)}],
        "empty": not (any(value > 0 for value in values) if counts else _measured(values)),
        "metadata": {
            "unit": unit,
            "y_min": 0,
            **({"y_max": 100} if unit == "percent" else {}),
            **metadata,
        },
    }


def build_session_charts(interactions, metrics):
    """Return all seven FR20 charts without querying or changing either input.

    Callers supply chronological, numbered Part 1 interactions and the full
    result of Part 2's ``compute_session_metrics``.
    """
    topic_counts = Counter(record["topic_label"] for record in interactions)
    topics = sorted(topic_counts)
    topic_accuracy = sorted(metrics["accuracy_by_topic"], key=lambda row: row["topic_label"])
    phase_order = {phase: index for index, phase in enumerate(PHASES)}
    phase_accuracy = sorted(metrics["accuracy_by_phase"],
                            key=lambda row: phase_order[row["phase"]])
    reply_accuracy = sorted(metrics["accuracy_per_reply"],
                            key=lambda row: row["interaction_number"])
    replies = sorted(interactions, key=lambda row: row["interaction_number"])
    rating_metrics = metrics["ratings"]
    lengths = metrics["length_distribution"]

    return {
        "topic_distribution": _chart(
            "Topic Distribution", "pie", topics, "Interactions",
            [topic_counts[topic] for topic in topics], "count", counts=True,
            total_interactions=metrics["summary"]["total_interactions"],
            total_count=sum(topic_counts.values()),
        ),
        "accuracy_per_topic": _chart(
            "Accuracy per Topic", "bar",
            [row["topic_label"] for row in topic_accuracy], "Accuracy (%)",
            [row["accuracy_percentage"] for row in topic_accuracy], "percent",
        ),
        "accuracy_vs_phase": _chart(
            "Accuracy vs Phase", "line",
            [row["phase"] for row in phase_accuracy], "Accuracy (%)",
            [row["accuracy_percentage"] for row in phase_accuracy], "percent",
        ),
        "correctness_per_reply": _chart(
            "Correctness per Reply", "bar",
            [f"Reply {row['interaction_number']}" for row in reply_accuracy],
            "Accuracy (%)", [row["accuracy_percentage"] for row in reply_accuracy],
            "percent", points=[{
                field: row.get(field) for field in (
                    "interaction_id", "interaction_number", "topic_label", "phase",
                    "correctness",
                )
            } for row in reply_accuracy],
        ),
        "response_time_trend": _chart(
            "Response Time Trend", "line",
            [f"Reply {row['interaction_number']}" for row in replies],
            "Response Time (s)", [row["response_time_seconds"] for row in replies],
            "seconds", average_seconds=metrics["response_time"]["average_seconds"],
            points=[{
                "interaction_id": row.get("interaction_id"),
                "interaction_number": row["interaction_number"],
            } for row in replies],
        ),
        "rating_distribution": _chart(
            "Rating Distribution", "bar", ["1", "2", "3", "4"], "Ratings",
            [rating_metrics["distribution"][str(rating)] for rating in range(1, 5)],
            "count", counts=True, average_rating=rating_metrics["average"],
            total_count=rating_metrics["count"],
        ),
        "length_preference": _chart(
            "Length Preference", "pie", LENGTH_TYPES, "Responses",
            [lengths[label]["count"] for label in LENGTH_TYPES], "count", counts=True,
            percentages=[lengths[label]["percentage"] for label in LENGTH_TYPES],
            total_count=metrics["summary"]["length_scored_count"],
        ),
    }
