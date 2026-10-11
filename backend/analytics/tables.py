"""FR19 presentation tables built from normalized interactions and Part 2 metrics.

The metrics engine owns calculations. This module only selects and orders values
for display; it never reads or writes persistent data.
"""

from collections import Counter


def _table(title, columns, rows, **metadata):
    return {
        "title": title,
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": rows,
        "row_count": len(rows),
        **metadata,
    }


def _project(row, fields):
    return {field: row[field] for field in fields}


def _reply_rows(interactions, metric_replies):
    """Match unique IDs first, then unique numbers when an ID is unavailable.

    A number never overrides two different known IDs. Duplicate IDs can use a
    unique number instead, but ambiguous numbers remain unmatched.
    """
    source_ids = Counter(record.get("interaction_id") for record in interactions
                         if record.get("interaction_id"))
    metric_ids = Counter(row.get("interaction_id") for row in metric_replies
                         if row.get("interaction_id"))
    source_numbers = Counter(record.get("interaction_number") for record in interactions)
    metric_numbers = Counter(row.get("interaction_number") for row in metric_replies)
    by_id = {row["interaction_id"]: row for row in metric_replies
             if row.get("interaction_id") and metric_ids[row["interaction_id"]] == 1}
    by_number = {row["interaction_number"]: row for row in metric_replies
                 if metric_numbers[row.get("interaction_number")] == 1}

    rows = []
    for record in sorted(interactions, key=lambda item: item["interaction_number"]):
        identifier = record.get("interaction_id")
        number = record["interaction_number"]
        matched = None
        if identifier and source_ids[identifier] == 1 and metric_ids[identifier] == 1:
            matched = by_id[identifier]
        elif source_numbers[number] == 1 and metric_numbers[number] == 1:
            candidate = by_number[number]
            candidate_id = candidate.get("interaction_id")
            if not (identifier and candidate_id and identifier != candidate_id):
                matched = candidate

        submitted = record.get("feedback_submitted") is True
        rows.append({
            "interaction_number": number,
            "interaction_id": identifier,
            "topic_label": record.get("topic_label"),
            "phase": record.get("phase"),
            "correctness": (matched.get("correctness") if matched else record.get("correctness"))
            if submitted else None,
            "accuracy_percentage": matched.get("accuracy_percentage") if submitted and matched else None,
            "rating": record.get("rating") if submitted else None,
            "length_type": record.get("length_type") if submitted else None,
            "response_time_seconds": record.get("response_time_seconds"),
            "feedback_submitted": submitted,
        })
    return rows


def build_session_tables(interactions, metrics):
    """Return six JSON-ready FR19 tables without mutating either input.

    Inputs are chronological, numbered Part 1 records and the complete result
    of compute_session_metrics, never raw Mongo documents or client metrics.
    """
    accuracy_fields = ("interaction_count", "scored_interaction_count", "accuracy_percentage")
    topic_rows = [_project(row, ("topic_label", *accuracy_fields))
                  for row in metrics["accuracy_by_topic"]]
    phase_rows = [_project(row, ("phase", *accuracy_fields))
                  for row in metrics["accuracy_by_phase"]]
    phase_order = {phase: index for index, phase in enumerate(("Start", "Middle", "End"))}
    phase_rows.sort(key=lambda row: phase_order[row["phase"]])

    timing = metrics["response_time"]
    timing_rows = [
        {"metric": label, "seconds": timing[field]}
        for label, field in (("Average", "average_seconds"),
                             ("Minimum", "minimum_seconds"),
                             ("Maximum", "maximum_seconds"),
                             ("Median", "median_seconds"))
    ]
    rating_metrics = metrics["ratings"]
    rating_total = rating_metrics["count"]
    rating_rows = [
        {
            "rating": rating,
            "count": rating_metrics["distribution"][str(rating)],
            "percentage": round(rating_metrics["distribution"][str(rating)] / rating_total * 100, 2)
            if rating_total else 0.0,
        }
        for rating in range(1, 5)
    ]
    length_rows = [
        {"length_type": label, **_project(metrics["length_distribution"][label],
                                          ("count", "percentage"))}
        for label in ("Short", "To the Point", "Lengthy")
    ]

    return {
        "topic_vs_accuracy": _table("Topic vs Accuracy", (
            ("topic_label", "Topic"), ("interaction_count", "Interactions"),
            ("scored_interaction_count", "Scored Replies"),
            ("accuracy_percentage", "Accuracy (%)")), topic_rows),
        "reply_correctness": _table("Reply Correctness", (
            ("interaction_number", "Reply #"), ("topic_label", "Topic"),
            ("phase", "Phase"), ("correctness", "Correctness"),
            ("accuracy_percentage", "Accuracy (%)"), ("rating", "Rating"),
            ("length_type", "Length"), ("response_time_seconds", "Response Time (s)")),
            _reply_rows(interactions, metrics["accuracy_per_reply"])),
        "phase_wise_accuracy": _table("Phase-wise Accuracy", (
            ("phase", "Phase"), ("interaction_count", "Interactions"),
            ("scored_interaction_count", "Scored Replies"),
            ("accuracy_percentage", "Accuracy (%)")), phase_rows),
        "response_time_summary": _table("Response Time Summary", (
            ("metric", "Metric"), ("seconds", "Seconds")), timing_rows,
            valid_response_count=timing["count"]),
        "rating_distribution": _table("Rating Distribution", (
            ("rating", "Rating"), ("count", "Count"),
            ("percentage", "Percentage (%)")), rating_rows),
        "length_preference": _table("Length Preference", (
            ("length_type", "Length"), ("count", "Count"),
            ("percentage", "Percentage (%)")), length_rows),
    }
