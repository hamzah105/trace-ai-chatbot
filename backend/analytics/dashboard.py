"""Concise FR21 session overview projected from authoritative Part 2 metrics."""


LENGTH_TYPES = ("Short", "To the Point", "Lengthy")


def build_session_overview(metrics):
    """Select display values; ties follow topic alphabet and fixed length order."""
    topics = metrics["accuracy_by_topic"]
    dominant_topic = None
    if topics:
        ranked = sorted(topics, key=lambda row: (-row["interaction_count"], row["topic_label"]))
        if ranked[0]["interaction_count"] > 0:
            dominant_topic = ranked[0]["topic_label"]

    lengths = metrics["length_distribution"]
    dominant_length = max(LENGTH_TYPES, key=lambda label: lengths[label]["count"])
    if lengths[dominant_length]["count"] <= 0:
        dominant_length = None

    return {
        "total_interactions": metrics["summary"]["total_interactions"],
        "feedback_submitted_count": metrics["summary"]["feedback_submitted_count"],
        "weighted_accuracy_percentage": metrics["correctness"]["overall_correctness_percentage"],
        "strict_correct_percentage": metrics["correctness"]["strict_correct_percentage"],
        "average_rating": metrics["ratings"]["average"],
        "average_response_time_seconds": metrics["response_time"]["average_seconds"],
        "dominant_topic": dominant_topic,
        "dominant_length_preference": dominant_length,
    }
