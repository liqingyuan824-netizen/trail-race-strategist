"""Mapping helpers for runner readiness outputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .completeness import assess_completeness
from .health_rules import assess_health_and_planning, readiness_explanation
from .specs import CACHE_POLICY_VERSION, FIELD_SPECS, GENERATOR_VERSION, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION
from .normalization import fingerprint


def _source_ref(record: Mapping[str, Any]) -> dict[str, Any]:
    source = record.get("source", {})
    return {
        "source_type": source.get("source_type"),
        "source_uri": source.get("source_uri"),
        "captured_at": source.get("captured_at"),
        "is_user_self_report": bool(source.get("is_user_self_report", False)),
        "confidence": float(source.get("confidence", 0.5)),
    }


def _field_output(field_name: str, record: Mapping[str, Any]) -> dict[str, Any]:
    spec = FIELD_SPECS.get(field_name, {})
    sensitive = bool(record.get("sensitive", spec.get("sensitive", False)))
    return {
        "value": record.get("value"),
        "raw_range": record.get("raw_range"),
        "source": _source_ref(record),
        "sensitive": sensitive,
        "confidence": float(record.get("confidence", 0.5)),
        "captured_at": record.get("captured_at"),
        "is_user_self_report": bool(record.get("is_user_self_report", False)),
        "local_only": bool(record.get("local_only", sensitive)),
        "note": record.get("note"),
    }


def build_profile_output(profile: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(profile)
    output["schema_name"] = "runner_profile"
    output["schema_version"] = SCHEMA_VERSION
    output["generator_version"] = GENERATOR_VERSION
    output["source_policy_version"] = SOURCE_POLICY_VERSION
    output["cache_policy_version"] = CACHE_POLICY_VERSION
    output["safety_notice"] = profile.get("safety_notice", SAFETY_NOTICE)
    return output


def build_current_readiness_output(
    *,
    profile: Mapping[str, Any],
    normalized_answers: Mapping[str, Any],
    completeness: Mapping[str, Any],
    health: Mapping[str, Any],
    cache_key: str,
    wearable_feature_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = normalized_answers["inputs"]
    history_races = profile.get("historical_races", [])
    missing_field_names = [item["field"] for item in completeness.get("missing_fields", [])]
    output = {
        "schema_name": "current_readiness",
        "schema_version": SCHEMA_VERSION,
        "generated_at": normalized_answers["generated_at"],
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "cache_key": cache_key,
        "mode": normalized_answers["mode"],
        "subject": normalized_answers["subject"],
        "privacy": {
            "sensitive_health_local_only": True,
            "shared_with_general_model": False,
            "note": "Sensitive health details are intended to remain local.",
        },
        "evidence": [
            {
                "source_type": "runner_profile",
                "source_uri": profile.get("evidence", [None])[0],
                "source_fingerprint": profile.get("source_profile_fingerprint"),
                "captured_at": profile.get("generated_at"),
                "is_user_self_report": False,
                "confidence": 0.96,
                "immutable": True,
            },
            {
                "source_type": "runner_readiness_input",
                "source_uri": normalized_answers.get("default_source", {}).get("source_uri"),
                "source_fingerprint": normalized_answers.get("raw_input_fingerprint"),
                "captured_at": normalized_answers["generated_at"],
                "is_user_self_report": bool(normalized_answers.get("default_source", {}).get("is_user_self_report", False)),
                "confidence": float(normalized_answers.get("default_source", {}).get("confidence", 0.5)),
                "immutable": True,
            },
        ],
        "history_reference": {
            "runner_profile_fingerprint": profile.get("source_profile_fingerprint"),
            "general_pi_is_historical_only": True,
            "recent_race_count": len(history_races),
        },
        "current_training_state": {
            "weekly_km": _field_output("weekly_km", inputs.get("weekly_km", {})),
            "weekly_elevation_m": _field_output("weekly_elevation_m", inputs.get("weekly_elevation_m", {})),
            "continuity_weeks": _field_output("continuity_weeks", inputs.get("continuity_weeks", {})),
            "longest_session_distance_km": _field_output("longest_session_distance_km", inputs.get("longest_session_distance_km", {})),
            "longest_session_elevation_m": _field_output("longest_session_elevation_m", inputs.get("longest_session_elevation_m", {})),
            "longest_session_duration_min": _field_output("longest_session_duration_min", inputs.get("longest_session_duration_min", {})),
            "training_break_days": _field_output("training_break_days", inputs.get("training_break_days", {})),
            "recovery_days": _field_output("recovery_days", inputs.get("recovery_days", {})),
        },
        "health_state": {
            "injury_status": _field_output("injury_status", inputs.get("injury_status", {})),
            "illness_status": _field_output("illness_status", inputs.get("illness_status", {})),
            "sleep_hours": _field_output("sleep_hours", inputs.get("sleep_hours", {})),
            "subjective_fatigue": _field_output("subjective_fatigue", inputs.get("subjective_fatigue", {})),
            "red_flag_symptoms": _field_output("red_flag_symptoms", inputs.get("red_flag_symptoms", {})),
        },
        "experience": {
            "representative_races": _field_output("representative_races", inputs.get("representative_races", {})),
            "night_experience": _field_output("night_experience", inputs.get("night_experience", {})),
            "heat_experience": _field_output("heat_experience", inputs.get("heat_experience", {})),
            "cold_experience": _field_output("cold_experience", inputs.get("cold_experience", {})),
            "altitude_experience": _field_output("altitude_experience", inputs.get("altitude_experience", {})),
            "technical_terrain_experience": _field_output("technical_terrain_experience", inputs.get("technical_terrain_experience", {})),
            "fueling_tolerance": _field_output("fueling_tolerance", inputs.get("fueling_tolerance", {})),
            "pole_experience": _field_output("pole_experience", inputs.get("pole_experience", {})),
            "gear_experience": _field_output("gear_experience", inputs.get("gear_experience", {})),
            "support_arrangements": _field_output("support_arrangements", inputs.get("support_arrangements", {})),
        },
        "goal": _field_output("race_goal", inputs.get("race_goal", {})),
        "warnings": [
            "Current readiness does not use general PI as a substitute for current training state.",
        ] + (
            ["Red flags were detected; stop and seek professional assessment."]
            if health["planning_permission"] == "stop_and_seek_professional_assessment"
            else []
        ),
        "unavailable_fields": missing_field_names,
        "assessment": {
            "risk_level": health["risk_level"],
            "planning_permission": health["planning_permission"],
            "goal_intensity": health["goal_intensity"],
            "readiness_score": health["readiness_score"],
            "score_type": "internal_heuristic",
            "validated_metric": False,
            "readiness_band": _readiness_band(health["readiness_score"]),
            "red_flags": list(health["red_flags"]),
            "yellow_flags": list(health["yellow_flags"]),
            "reason_codes": list(health["reason_codes"]),
            "summary": _summary_text(health, completeness),
        },
        "completeness": dict(completeness),
        "diagnostics": {
            "input_validation": {
                "status": "passed",
                "error_count": 0,
            },
            "history_reference": {
                "profile_fingerprint": profile.get("source_profile_fingerprint"),
                "history_race_count": len(history_races),
            },
            "planning_cap": health["planning_permission"],
            "partial_reasons": missing_field_names,
        },
    }
    if wearable_feature_summary is not None:
        trace = wearable_feature_summary["source_trace"]
        output["wearable_training_exposure"] = {
            "source": "wearable_feature_summary",
            "summary_id": wearable_feature_summary["summary_id"],
            "generated_at": wearable_feature_summary["generated_at"],
            "aggregation_window": dict(wearable_feature_summary["aggregation_window"]),
            "training_load": dict(wearable_feature_summary["training_load"]),
            "quality": dict(wearable_feature_summary["quality"]),
            "uncertainty": dict(wearable_feature_summary["uncertainty"]),
            "source_activity_count": len(trace["activities"]),
            "import_request_ids": sorted({item["import_request_id"] for item in trace["activities"]}),
            "read_only_context": True,
            "does_not_override_self_report_or_health": True,
        }
        output["evidence"].append(
            {
                "source_type": "wearable_feature_summary",
                "source_uri": None,
                "source_fingerprint": fingerprint(wearable_feature_summary),
                "captured_at": wearable_feature_summary["generated_at"],
                "is_user_self_report": False,
                "confidence": 1.0 if wearable_feature_summary["uncertainty"]["level"] == "low" else 0.5,
                "immutable": True,
            }
        )
    return output


def _summary_text(health: Mapping[str, Any], completeness: Mapping[str, Any]) -> str:
    if health["planning_permission"] == "aggressive_plan_blocked":
        return "The goal is more aggressive than the current evidence supports."
    if health["planning_permission"] == "stop_and_seek_professional_assessment":
        return readiness_explanation(completeness=completeness, health=health)
    return readiness_explanation(completeness=completeness, health=health)


def _readiness_band(score: float) -> dict[str, Any]:
    if score >= 75:
        return {"label": "high", "range": {"min": 75, "max": 100}, "user_facing": True}
    if score >= 55:
        return {"label": "moderate", "range": {"min": 55, "max": 74.9}, "user_facing": True}
    if score >= 35:
        return {"label": "conservative", "range": {"min": 35, "max": 54.9}, "user_facing": True}
    return {"label": "low", "range": {"min": 0, "max": 34.9}, "user_facing": True}


def build_missing_information_output(
    *,
    normalized_answers: Mapping[str, Any],
    completeness: Mapping[str, Any],
    profile: Mapping[str, Any],
    cache_key: str,
) -> dict[str, Any]:
    missing_fields = []
    for item in completeness["missing_fields"]:
        missing_fields.append(
            {
                **item,
                "priority_rank": {"high": 0, "medium": 1, "low": 2}.get(item["priority"], 99),
            }
        )
    unavailable_fields = [item["field"] for item in missing_fields]
    return {
        "schema_name": "missing_information",
        "schema_version": SCHEMA_VERSION,
        "generated_at": normalized_answers["generated_at"],
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "cache_key": cache_key,
        "mode": normalized_answers["mode"],
        "subject": normalized_answers["subject"],
        "completeness": dict(completeness),
        "missing_fields": missing_fields,
        "unavailable_fields": unavailable_fields,
        "question_queue": [
            {
                "field": item["field"],
                "label": item["label"],
                "prompt": item["question_prompt"],
                "priority": item["priority"],
                "sensitive": item["sensitive"],
                "local_only": item.get("local_only", item["sensitive"]),
                "required": item.get("required", False),
                "recommended": item.get("recommended", False),
            }
            for item in missing_fields
        ],
        "privacy": {
            "sensitive_health_local_only": True,
            "shared_with_general_model": False,
        },
        "evidence": [
            {
                "source_type": "runner_profile",
                "source_uri": profile.get("evidence", [None])[0],
                "source_fingerprint": profile.get("source_profile_fingerprint"),
                "captured_at": profile.get("generated_at"),
                "is_user_self_report": False,
                "confidence": 0.96,
                "immutable": True,
            },
            {
                "source_type": "runner_readiness_input",
                "source_uri": normalized_answers.get("default_source", {}).get("source_uri"),
                "source_fingerprint": normalized_answers.get("raw_input_fingerprint"),
                "captured_at": normalized_answers["generated_at"],
                "is_user_self_report": bool(normalized_answers.get("default_source", {}).get("is_user_self_report", False)),
                "confidence": float(normalized_answers.get("default_source", {}).get("confidence", 0.5)),
                "immutable": True,
            },
        ],
        "history_reference": {
            "runner_profile_fingerprint": profile.get("source_profile_fingerprint"),
            "historical_race_count": len(profile.get("historical_races", [])),
        },
        "diagnostics": {
            "missing_count": len(missing_fields),
            "filled_field_count": completeness["filled_field_count"],
            "partial_reasons": unavailable_fields,
        },
    }
