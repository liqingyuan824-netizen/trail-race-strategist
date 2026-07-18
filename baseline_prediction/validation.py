"""Input validation for Phase 7A baseline prediction."""

from __future__ import annotations

from collections.abc import Mapping


class ValidationError(ValueError):
    """Raised when a baseline prediction input cannot be processed."""


REQUIRED_TOP_LEVEL_KEYS = {
    "schema_name",
    "schema_version",
    "generated_at",
    "generator_version",
    "safety_notice",
    "runner_profile",
    "current_readiness",
    "course_model",
    "target_event",
}

ALLOWED_PLANNING_PERMISSIONS = {
    "normal_planning_allowed",
    "conservative_planning_only",
    "aggressive_plan_blocked",
}


def validate_baseline_inputs(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in payload:
            errors.append(f"missing_top_level:{key}")

    if payload.get("schema_name") != "baseline_prediction_inputs":
        errors.append("schema_name:not_baseline_prediction_inputs")
    if payload.get("schema_version") != "1.0.0":
        errors.append("schema_version:unsupported")

    runner_profile = payload.get("runner_profile")
    current_readiness = payload.get("current_readiness")
    course_model = payload.get("course_model")
    target_event = payload.get("target_event")

    if not isinstance(runner_profile, Mapping):
        errors.append("runner_profile:not_mapping")
    if not isinstance(current_readiness, Mapping):
        errors.append("current_readiness:not_mapping")
    if not isinstance(course_model, Mapping):
        errors.append("course_model:not_mapping")
    if not isinstance(target_event, Mapping):
        errors.append("target_event:not_mapping")
    else:
        for key in ("event_name", "group_name", "grade", "distance_km", "elevation_gain_m"):
            if key not in target_event:
                errors.append(f"target_event:missing_{key}")

    return errors


def validate_baseline_operational_gate(current_readiness: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    assessment = current_readiness.get("assessment")
    if not isinstance(assessment, Mapping):
        errors.append("assessment:not_mapping")
        return errors
    if assessment.get("risk_level") == "red":
        errors.append("readiness:red_flag_block")
    planning_permission = assessment.get("planning_permission")
    if planning_permission not in ALLOWED_PLANNING_PERMISSIONS:
        errors.append("planning_permission:unsupported")
    return errors


def validate_user_facing_prediction_gate(current_readiness: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    assessment = current_readiness.get("assessment")
    if not isinstance(assessment, Mapping):
        return ["assessment:not_mapping"]
    if assessment.get("planning_permission") != "normal_planning_allowed":
        errors.append("user_facing_prediction:planning_restricted")
    if assessment.get("risk_level") != "green":
        errors.append("user_facing_prediction:not_green")
    return errors
