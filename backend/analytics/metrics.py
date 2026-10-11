"""Pure Phase 3 session metrics over Part 1 normalized interactions."""

from math import isfinite
from statistics import mean


# TRACE Phase 3 convention: Partial correctness receives half credit.
CORRECTNESS_SCORES = {"Correct": 1.0, "Partial": 0.5, "Incorrect": 0.0}
LENGTH_TYPES = ("Short", "To the Point", "Lengthy")
PHASES = ("Start", "Middle", "End")


def _valid_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        seconds = float(value)
    except (ValueError, OverflowError):
        return None
    return seconds if isfinite(seconds) and seconds >= 0 else None


def _accuracy_rows(groups, field, ordering=None):
    keys = (key for key in ordering if key in groups) if ordering else sorted(groups)
    rows = []
    for key in keys:
        group = groups[key]
        scores = group["scores"]
        average = mean(scores) if scores else None
        rows.append({
            field: key,
            "interaction_count": group["interaction_count"],
            "scored_interaction_count": len(scores),
            "accuracy_score": average,
            "accuracy_percentage": round(average * 100, 2) if average is not None else None,
        })
    return rows


def compute_session_metrics(interactions):
    """Compute FR17/FR18 metrics without database access or input mutation.

    Correct=1, Partial=0.5, Incorrect=0. Only strictly submitted and valid
    feedback contributes to correctness, rating, or length metrics.
    """
    replies = []
    topic_groups = {}
    phase_groups = {}
    correctness_counts = {"Correct": 0, "Partial": 0, "Incorrect": 0}
    rating_counts = {str(value): 0 for value in range(1, 5)}
    length_counts = {label: 0 for label in LENGTH_TYPES}
    seconds = []
    feedback_count = 0
    rating_count = 0
    length_count = 0
    total = 0

    for record in interactions:
        total += 1
        submitted = record.get("feedback_submitted") is True
        feedback_count += submitted

        correctness = record.get("correctness")
        if not isinstance(correctness, str) or correctness not in CORRECTNESS_SCORES:
            correctness = None
        score = CORRECTNESS_SCORES[correctness] if submitted and correctness else None
        if score is not None:
            correctness_counts[correctness] += 1

        topic = record.get("topic_label", "General")
        phase = record.get("phase")
        for groups, key in ((topic_groups, topic), (phase_groups, phase)):
            group = groups.setdefault(key, {"interaction_count": 0, "scores": []})
            group["interaction_count"] += 1
            if score is not None:
                group["scores"].append(score)

        replies.append({
            "interaction_id": record.get("interaction_id"),
            "interaction_number": record.get("interaction_number"),
            "topic_label": topic,
            "phase": phase,
            "correctness": correctness,
            "accuracy_score": score,
            "accuracy_percentage": round(score * 100, 2) if score is not None else None,
        })

        rating = record.get("rating")
        if submitted and isinstance(rating, int) and not isinstance(rating, bool) and 1 <= rating <= 4:
            rating_counts[str(rating)] += 1
            rating_count += 1

        length = record.get("length_type")
        if submitted and isinstance(length, str) and length in length_counts:
            length_counts[length] += 1
            length_count += 1

        response_time = _valid_seconds(record.get("response_time_seconds"))
        if response_time is not None:
            seconds.append(response_time)

    scored = sum(correctness_counts.values())
    overall = (sum(CORRECTNESS_SCORES[label] * count
                   for label, count in correctness_counts.items()) / scored) if scored else None
    seconds.sort()
    middle = len(seconds) // 2
    if not seconds:
        median = None
    elif len(seconds) % 2:
        median = seconds[middle]
    else:
        median = mean((seconds[middle - 1], seconds[middle]))

    return {
        "summary": {
            "total_interactions": total,
            "feedback_submitted_count": feedback_count,
            "correctness_scored_count": scored,
            "rating_scored_count": rating_count,
            "length_scored_count": length_count,
            "response_time_scored_count": len(seconds),
        },
        "accuracy_per_reply": replies,
        "accuracy_by_topic": _accuracy_rows(topic_groups, "topic_label"),
        "accuracy_by_phase": _accuracy_rows(phase_groups, "phase", PHASES),
        "correctness": {
            "correct_count": correctness_counts["Correct"],
            "partial_count": correctness_counts["Partial"],
            "incorrect_count": correctness_counts["Incorrect"],
            "scored_reply_count": scored,
            "overall_correctness_score": overall,
            "overall_correctness_percentage": round(overall * 100, 2) if overall is not None else None,
            "strict_correct_percentage": round(correctness_counts["Correct"] / scored * 100, 2)
            if scored else None,
        },
        "response_time": {
            "count": len(seconds),
            "average_seconds": round(mean(seconds), 3) if seconds else None,
            "minimum_seconds": round(seconds[0], 3) if seconds else None,
            "maximum_seconds": round(seconds[-1], 3) if seconds else None,
            "median_seconds": round(median, 3) if median is not None else None,
        },
        "ratings": {
            "count": rating_count,
            "average": round(sum(int(key) * count for key, count in rating_counts.items()) /
                             rating_count, 2) if rating_count else None,
            "distribution": rating_counts,
        },
        "length_distribution": {
            label: {
                "count": length_counts[label],
                "percentage": round(length_counts[label] / length_count * 100, 2)
                if length_count else 0.0,
            }
            for label in LENGTH_TYPES
        },
    }


class AnalyticsManager:
    """Legacy Phase 1 placeholder retained for import compatibility."""

    def __init__(self):
        import pandas as pd

        self.metrics_df = pd.DataFrame(columns=[
            "timestamp", "user_prompt", "response_time", "model_name", "tokens_used",
        ])

    def add_metric(self, timestamp, user_prompt, response_time, model_name, tokens_used):
        new_row = {
            "timestamp": timestamp,
            "user_prompt": user_prompt,
            "response_time": response_time,
            "model_name": model_name,
            "tokens_used": tokens_used,
        }
        self.metrics_df.loc[len(self.metrics_df)] = new_row

    def show_metrics(self):
        print(self.metrics_df)
