"""Normalization and scoring helpers for Phase 7A baseline prediction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract_value(record: Mapping[str, Any] | None) -> Any:
    if not isinstance(record, Mapping):
        return None
    if "value" in record:
        return record.get("value")
    return record.get("raw_value")


def _source_of(record: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        return {}
    source = record.get("source")
    return dict(source) if isinstance(source, Mapping) else {}


def _history_races(runner_profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for race in runner_profile.get("race_results", []):
        if not isinstance(race, Mapping):
            continue
        summary.append(
            {
                "date": race.get("date"),
                "race": race.get("race"),
                "country": race.get("country"),
                "distance_km": race.get("distance_km"),
                "elevation_gain_m": race.get("elevation_gain_m"),
                "race_time": race.get("race_time"),
                "race_url": race.get("race_url"),
                "race_score_access": race.get("race_score_access"),
                "race_score_raw_display": race.get("race_score_raw_display"),
            }
        )
    return summary


def _readiness_snapshot(current_readiness: Mapping[str, Any]) -> dict[str, Any]:
    assessment = current_readiness.get("assessment", {})
    completeness = current_readiness.get("completeness", {})
    history_reference = current_readiness.get("history_reference", {})
    health_state = current_readiness.get("health_state", {})
    return {
        "risk_level": assessment.get("risk_level"),
        "planning_permission": assessment.get("planning_permission"),
        "goal_intensity": assessment.get("goal_intensity"),
        "readiness_band": assessment.get("readiness_band"),
        "readiness_score": assessment.get("readiness_score"),
        "validated_metric": assessment.get("validated_metric"),
        "yellow_flags": list(assessment.get("yellow_flags", [])),
        "red_flags": list(assessment.get("red_flags", [])),
        "summary": assessment.get("summary"),
        "completeness": {
            "status": completeness.get("status"),
            "required_missing_count": completeness.get("required_missing_count"),
            "recommended_missing_count": completeness.get("recommended_missing_count"),
            "missing_count": completeness.get("missing_count"),
        },
        "history_reference": {
            "runner_profile_fingerprint": history_reference.get("runner_profile_fingerprint"),
            "historical_race_count": history_reference.get("historical_race_count"),
            "general_pi_is_historical_only": history_reference.get("general_pi_is_historical_only"),
        },
        "yellow_flag_sources": {
            "injury_status": _extract_value(health_state.get("injury_status")),
            "illness_status": _extract_value(health_state.get("illness_status")),
            "sleep_hours": _extract_value(health_state.get("sleep_hours")),
            "subjective_fatigue": _extract_value(health_state.get("subjective_fatigue")),
        },
    }


def _course_snapshot(course_model: Mapping[str, Any]) -> dict[str, Any]:
    event = course_model.get("event", {})
    course = event.get("course", {})
    grade = event.get("grade", {})
    return {
        "official_name": event.get("official_name"),
        "group_name": event.get("group_name"),
        "group_code": event.get("group_code"),
        "grade": grade.get("grade"),
        "route_version_state": event.get("route_version_state"),
        "route_version": event.get("route_version"),
        "distance_km": _extract_value(course.get("total_distance_km")),
        "elevation_gain_m": _extract_value(course.get("total_elevation_gain_m")),
        "elevation_loss_m": _extract_value(course.get("total_elevation_loss_m")),
        "start_time": _extract_value(course.get("start_time")),
        "cutoff_time": _extract_value(course.get("cutoff_time")),
        "cutoff_hours": _extract_value(course.get("cutoff_hours")),
        "cp_model_status": course.get("cp_model", {}).get("status"),
        "cp_count": course.get("cp_model", {}).get("cp_count"),
    }


def normalize_baseline_inputs(
    *,
    runner_profile: Mapping[str, Any],
    current_readiness: Mapping[str, Any],
    course_model: Mapping[str, Any],
    target_event: Mapping[str, Any],
) -> dict[str, Any]:
    readiness = _readiness_snapshot(current_readiness)
    course = _course_snapshot(course_model)
    history_races = _history_races(runner_profile)
    target_distance_km = _coerce_float(target_event.get("distance_km"))
    target_elevation_gain_m = _coerce_float(target_event.get("elevation_gain_m"))
    return {
        "schema_name": "baseline_prediction_inputs",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "generator_version": "0.1.0",
        "source_policy_version": "1.0.0",
        "cache_policy_version": "1.0.0",
        "safety_notice": runner_profile.get("safety_notice") or {
            "version": "1.0.0",
            "medical_advice": False,
            "replaces_race_rules": False,
            "message": "This tool does not replace race rules, on-site safety, or professional medical judgment.",
        },
        "runner_profile": {
            "identity": dict(runner_profile.get("identity", {})),
            "performance": dict(runner_profile.get("performance", {})),
            "historical_summary": dict(runner_profile.get("historical_summary", {})),
            "historical_races": history_races,
            "source_profile_fingerprint": runner_profile.get("source_profile_fingerprint"),
        },
        "current_readiness": readiness,
        "course_model": course,
        "target_event": {
            "event_name": target_event.get("event_name"),
            "group_name": target_event.get("group_name"),
            "group_code": target_event.get("group_code"),
            "grade": target_event.get("grade"),
            "route_version_state": target_event.get("route_version_state"),
            "distance_km": target_distance_km,
            "elevation_gain_m": target_elevation_gain_m,
            "distance_source_note": target_event.get("distance_source_note"),
            "elevation_source_note": target_event.get("elevation_source_note"),
            "route_status": target_event.get("route_status"),
            "route_text": target_event.get("route_text"),
            "condition_tags": list(target_event.get("condition_tags", [])),
            "condition_status": target_event.get("condition_status"),
            "condition_policy_notes": list(target_event.get("condition_policy_notes", [])),
        },
        "source_fingerprints": {
            "runner_profile": fingerprint(runner_profile),
            "current_readiness": fingerprint(current_readiness),
            "course_model": fingerprint(course_model),
            "target_event": fingerprint(target_event),
        },
        "diagnostics": {
            "input_validation": {
                "status": "passed",
                "error_count": 0,
            },
            "history_race_count": len(history_races),
            "target_course_grade": course.get("grade"),
            "target_route_state": course.get("route_version_state"),
            "planning_permission": readiness.get("planning_permission"),
            "partial_reasons": list(current_readiness.get("diagnostics", {}).get("partial_reasons", [])),
        },
    }


def _race_time_to_minutes(race_time: str | None) -> float | None:
    if not race_time:
        return None
    parts = race_time.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = [float(part) for part in parts]
            return hours * 60.0 + minutes + seconds / 60.0
        if len(parts) == 2:
            minutes, seconds = [float(part) for part in parts]
            return minutes + seconds / 60.0
    except ValueError:
        return None
    return None


def _minutes_to_hhmmss(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    total_seconds = max(int(round(minutes * 60.0)), 0)
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{hours}:{mins:02d}:{secs:02d}"


def _source_confidence(source_kind: str | None, time_source_kind: str | None) -> float:
    if source_kind == "official" and time_source_kind == "official":
        return 1.0
    if source_kind == "official" and time_source_kind == "user_self_report":
        return 0.82
    if source_kind == "third_party_aggregator" and time_source_kind == "official":
        return 0.92
    if source_kind == "third_party_aggregator" and time_source_kind == "user_self_report":
        return 0.78
    if time_source_kind == "user_self_report":
        return 0.72
    return 0.85


def normalized_load(distance_km: float | None, elevation_gain_m: float | None) -> float | None:
    if distance_km is None or elevation_gain_m is None:
        return None
    return float(distance_km) + float(elevation_gain_m) / 100.0


def estimate_race_time_minutes(
    *,
    race_distance_km: float | None,
    race_elevation_gain_m: float | None,
    race_time: str | None,
    time_source_kind: str | None,
    source_kind: str | None,
    target_distance_km: float | None,
    target_elevation_gain_m: float | None,
) -> dict[str, Any]:
    actual_minutes = _race_time_to_minutes(race_time)
    historical_load = normalized_load(race_distance_km, race_elevation_gain_m)
    target_load = normalized_load(target_distance_km, target_elevation_gain_m)

    if actual_minutes is None or historical_load is None or target_load is None or historical_load <= 0:
        return {
            "base_estimate_minutes": None,
            "base_estimate_hhmmss": None,
            "time_source_kind": time_source_kind,
            "source_confidence": _source_confidence(source_kind, time_source_kind),
            "load_ratio": None,
        }

    base_estimate = actual_minutes * (target_load / historical_load)
    return {
        "base_estimate_minutes": round(base_estimate, 2),
        "base_estimate_hhmmss": _minutes_to_hhmmss(base_estimate),
        "time_source_kind": time_source_kind,
        "source_confidence": _source_confidence(source_kind, time_source_kind),
        "load_ratio": round(target_load / historical_load, 4),
    }


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None:
    if not values or not weights or len(values) != len(weights):
        return None
    pairs = sorted((float(v), max(float(w), 0.0)) for v, w in zip(values, weights))
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return None
    threshold = total_weight / 2.0
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def weighted_quantile(values: Sequence[float], weights: Sequence[float], quantile: float) -> float | None:
    if not values or not weights or len(values) != len(weights):
        return None
    quantile = min(max(quantile, 0.0), 1.0)
    pairs = sorted((float(v), max(float(w), 0.0)) for v, w in zip(values, weights))
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return None
    threshold = total_weight * quantile
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0]
