"""Public projection of stored final analytics; never expose raw Mongo fields."""

from datetime import datetime
from math import isfinite


FINAL_ANALYTICS_VERSION = 1
FINALIZATION_EMPTY = {"is_finalized": False, "finalized_at": None, "analytics_version": None}

_OVERVIEW = frozenset({
    "total_interactions", "feedback_submitted_count", "weighted_accuracy_percentage",
    "strict_correct_percentage", "average_rating", "average_response_time_seconds",
    "dominant_topic", "dominant_length_preference",
})
_METRIC_FIELDS = {
    "summary": frozenset({"total_interactions", "feedback_submitted_count", "correctness_scored_count", "rating_scored_count", "length_scored_count", "response_time_scored_count"}),
    "correctness": frozenset({"correct_count", "partial_count", "incorrect_count", "scored_reply_count", "overall_correctness_score", "overall_correctness_percentage", "strict_correct_percentage"}),
    "response_time": frozenset({"count", "average_seconds", "minimum_seconds", "maximum_seconds", "median_seconds"}),
    "ratings": frozenset({"count", "average", "distribution"}),
}
_ROW_FIELDS = {
    "accuracy_per_reply": frozenset({"interaction_id", "interaction_number", "topic_label", "phase", "correctness", "accuracy_score", "accuracy_percentage"}),
    "accuracy_by_topic": frozenset({"topic_label", "interaction_count", "scored_interaction_count", "accuracy_score", "accuracy_percentage"}),
    "accuracy_by_phase": frozenset({"phase", "interaction_count", "scored_interaction_count", "accuracy_score", "accuracy_percentage"}),
}


def _scalar(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    return None


def _fields(value, names):
    if not isinstance(value, dict):
        return {}
    text_fields = {"interaction_id", "topic_label", "phase", "correctness",
                   "dominant_topic", "dominant_length_preference"}
    result = {}
    for key in names:
        if key not in value:
            continue
        item = _scalar(value[key])
        if item is not None:
            if key in text_fields and not isinstance(item, str):
                item = None
            elif key not in text_fields and (isinstance(item, bool) or not isinstance(item, (int, float))):
                item = None
        result[key] = item
    return result


def public_metrics(metrics):
    if not isinstance(metrics, dict):
        return None
    result = {key: _fields(metrics.get(key), names) for key, names in _METRIC_FIELDS.items()}
    for key, names in _ROW_FIELDS.items():
        rows = metrics.get(key)
        result[key] = [_fields(row, names) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    ratings = metrics.get("ratings")
    distribution = ratings.get("distribution") if isinstance(ratings, dict) else None
    result["ratings"]["distribution"] = _fields(distribution, {"1", "2", "3", "4"})
    lengths = metrics.get("length_distribution")
    result["length_distribution"] = {
        key: _fields(lengths.get(key), {"count", "percentage"})
        for key in ("Short", "To the Point", "Lengthy")
    } if isinstance(lengths, dict) else {}
    return result


def public_snapshot(session):
    snapshot = session.get("final_analytics")
    if session.get("status") != "ended" or not isinstance(snapshot, dict):
        return None
    finalized_at = snapshot.get("finalized_at")
    metrics = snapshot.get("metrics")
    overview = snapshot.get("overview")
    if (type(snapshot.get("version")) is not int
            or snapshot["version"] != FINAL_ANALYTICS_VERSION
            or not isinstance(finalized_at, datetime)
            or type(snapshot.get("interaction_count")) is not int
            or not isinstance(metrics, dict) or not isinstance(overview, dict)
            or not all(isinstance(metrics.get(key), dict)
                       and fields.issubset(metrics[key])
                       for key, fields in _METRIC_FIELDS.items())
            or not all(isinstance(metrics.get(key), list)
                       and all(isinstance(row, dict) and fields.issubset(row)
                               for row in metrics[key])
                       for key, fields in _ROW_FIELDS.items())
            or not isinstance(metrics.get("length_distribution"), dict)
            or not all(isinstance(metrics["length_distribution"].get(key), dict)
                       and {"count", "percentage"}.issubset(metrics["length_distribution"][key])
                       for key in ("Short", "To the Point", "Lengthy"))
            or not isinstance(metrics["ratings"].get("distribution"), dict)
            or not {"1", "2", "3", "4"}.issubset(metrics["ratings"]["distribution"])
            or not _OVERVIEW.issubset(overview)):
        return None
    return {
        "version": snapshot.get("version") if type(snapshot.get("version")) is int else None,
        "finalized_at": finalized_at.isoformat() if isinstance(finalized_at, datetime) else None,
        "interaction_count": snapshot.get("interaction_count") if type(snapshot.get("interaction_count")) is int else None,
        "overview": _fields(overview, _OVERVIEW),
        "metrics": public_metrics(metrics),
    }


def finalization_metadata(session):
    snapshot = public_snapshot(session)
    if snapshot is None:
        return FINALIZATION_EMPTY.copy()
    return {
        "is_finalized": True,
        "finalized_at": snapshot["finalized_at"],
        "analytics_version": snapshot["version"],
    }
