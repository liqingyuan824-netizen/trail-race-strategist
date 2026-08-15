"""W2 aggregate-only wearable training features.

This module accepts normalized activity dictionaries only.  It never reads FIT
files, GPS streams, health/wellness records, or external accounts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any


class FeatureSummaryError(ValueError):
    pass


SUMMARY_SCHEMA_VERSION = "1.0.0"
_METRICS = {"distance_km", "duration_seconds", "ascent_m"}


def _date_from_activity(activity: Mapping[str, Any]) -> date:
    started = activity.get("started_at_unix")
    if not isinstance(started, (int, float)):
        raise FeatureSummaryError("normalized_activity_missing_started_at_unix")
    return datetime.fromtimestamp(started, UTC).date()


def _validated_activities(activities: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in activities:
        if not isinstance(raw, Mapping) or raw.get("schema_name") != "wearable_normalized_activity":
            raise FeatureSummaryError("invalid_normalized_activity_schema")
        activity_id = raw.get("activity_id")
        request_id = raw.get("import_request_id")
        if not isinstance(activity_id, str) or not activity_id or not isinstance(request_id, str) or not request_id.startswith("wearable-req-"):
            raise FeatureSummaryError("normalized_activity_missing_trace_binding")
        if activity_id in seen:
            raise FeatureSummaryError("duplicate_activity_id")
        seen.add(activity_id)
        _date_from_activity(raw)
        for metric in _METRICS:
            value = raw.get(metric)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                raise FeatureSummaryError(f"invalid_normalized_activity_{metric}")
        result.append(dict(raw))
    return result


def _load_window(activities: list[dict[str, Any]], start: date, end: date) -> tuple[dict[str, float | None], dict[str, float]]:
    selected = [item for item in activities if start <= _date_from_activity(item) <= end]
    output: dict[str, float | None] = {}
    coverage: dict[str, float] = {}
    source_count = len(selected)
    for metric, output_name, divisor in (
        ("distance_km", "distance_km", 1),
        ("duration_seconds", "duration_minutes", 60),
        ("ascent_m", "ascent_m", 1),
    ):
        present = [float(item[metric]) for item in selected if item.get(metric) is not None]
        coverage[metric] = round(len(present) / source_count, 3) if source_count else 0.0
        # A partial aggregate is deliberately not represented as a complete total.
        output[output_name] = round(sum(present) / divisor, 3) if source_count and len(present) == source_count else (0.0 if not selected else None)
    return output, coverage


def _ratio(numerator: float | None, denominator: float | None, factor: float) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / (denominator / factor), 3)


def build_feature_summary(
    activities: Iterable[Mapping[str, Any]], *, generated_at: str | None = None, as_of_date: date | None = None
) -> dict[str, Any]:
    """Build an explainable W2 feature summary from normalized aggregates."""
    normalized = _validated_activities(activities)
    if as_of_date is None:
        as_of_date = max((_date_from_activity(item) for item in normalized), default=date.today())
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    windows: dict[str, dict[str, float | None]] = {}
    coverage_by_window: dict[str, dict[str, float]] = {}
    for days, label in ((7, "7d"), (28, "28d"), (84, "84d")):
        windows[label], coverage_by_window[label] = _load_window(normalized, as_of_date - timedelta(days=days - 1), as_of_date)

    all_distance = [float(item["distance_km"]) for item in normalized if item.get("distance_km") is not None]
    all_duration = [float(item["duration_seconds"]) / 60 for item in normalized if item.get("duration_seconds") is not None]
    all_ascent = [float(item["ascent_m"]) for item in normalized if item.get("ascent_m") is not None]
    recent_84 = [item for item in normalized if as_of_date - timedelta(days=83) <= _date_from_activity(item) <= as_of_date]
    recent_28 = [item for item in normalized if as_of_date - timedelta(days=27) <= _date_from_activity(item) <= as_of_date]
    recent_dates = {_date_from_activity(item) for item in recent_28}
    streak = 0
    cursor = as_of_date
    while cursor in recent_dates:
        streak += 1
        cursor -= timedelta(days=1)
    long_distance_frequency = None
    if recent_84 and all(item.get("distance_km") is not None for item in recent_84):
        long_distance_frequency = round(sum(float(item["distance_km"]) >= 20 for item in recent_84) / 12, 3)
    missing = []
    for label, coverage in coverage_by_window.items():
        for metric, value in coverage.items():
            if value < 1.0:
                missing.append(f"{label}_{metric}_coverage_{value}")
    if not normalized:
        missing.append("no_normalized_activities")
    uncertainty_level = "high" if not normalized or any(value == 0.0 for coverage in coverage_by_window.values() for value in coverage.values()) else ("medium" if missing else "low")
    source_ids = [{"activity_id": item["activity_id"], "import_request_id": item["import_request_id"], "activity_date": _date_from_activity(item).isoformat()} for item in normalized]
    summary_suffix = "empty" if not normalized else "-".join(sorted({item["import_request_id"].removeprefix("wearable-req-") for item in normalized}))
    return {
        "schema_name": "wearable_feature_summary", "schema_version": SUMMARY_SCHEMA_VERSION,
        "summary_id": f"wearable-summary-{summary_suffix}", "generated_at": generated_at,
        "aggregation_window": {"start_date": (as_of_date - timedelta(days=83)).isoformat(), "end_date": as_of_date.isoformat(), "source_activity_count": len(normalized)},
        "source_trace": {"activities": source_ids, "trace_complete": True},
        "training_load": {
            "windows": windows,
            "maxima": {"longest_activity_distance_km": max(all_distance, default=None), "longest_activity_duration_minutes": round(max(all_duration), 3) if all_duration else None, "longest_activity_ascent_m": max(all_ascent, default=None)},
            "ratios": {"load_7d_to_28d": _ratio(windows["7d"]["distance_km"], windows["28d"]["distance_km"], 4), "load_28d_to_84d": _ratio(windows["28d"]["distance_km"], windows["84d"]["distance_km"], 3), "long_distance_frequency": long_distance_frequency, "consecutive_training_days": streak, "recovery_day_ratio": round((28 - len(recent_dates)) / 28, 3)},
        },
        "quality": {"coverage": {"distance": coverage_by_window["84d"]["distance_km"], "duration": coverage_by_window["84d"]["duration_seconds"], "ascent": coverage_by_window["84d"]["ascent_m"]}, "coverage_by_window": coverage_by_window, "missing_data_flags": missing, "excluded_activity_count": 0},
        "uncertainty": {"level": uncertainty_level, "reasons": missing},
        "governance": {"allow_model_research": False, "user_facing_prediction_allowed": False},
    }


def validate_feature_summary(summary: Mapping[str, Any]) -> list[str]:
    """Small fail-closed validator used before readiness consumes a summary."""
    errors: list[str] = []
    required = {"schema_name", "schema_version", "summary_id", "generated_at", "aggregation_window", "source_trace", "training_load", "quality", "uncertainty", "governance"}
    if set(summary) != required:
        errors.append("wearable_summary:unexpected_or_missing_top_level_fields")
    if summary.get("schema_name") != "wearable_feature_summary" or summary.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        errors.append("wearable_summary:unsupported_schema")
    governance = summary.get("governance")
    if not isinstance(governance, Mapping) or governance.get("allow_model_research") is not False or governance.get("user_facing_prediction_allowed") is not False:
        errors.append("wearable_summary:governance_not_locked")
    trace = summary.get("source_trace")
    if not isinstance(trace, Mapping) or trace.get("trace_complete") is not True or not isinstance(trace.get("activities"), list):
        errors.append("wearable_summary:missing_source_trace")
    else:
        for item in trace["activities"]:
            if not isinstance(item, Mapping) or not isinstance(item.get("activity_id"), str) or not isinstance(item.get("import_request_id"), str):
                errors.append("wearable_summary:invalid_source_trace")
                break
    if not isinstance(summary.get("training_load"), Mapping) or not isinstance(summary.get("quality"), Mapping) or not isinstance(summary.get("uncertainty"), Mapping):
        errors.append("wearable_summary:invalid_structure")
    return errors
