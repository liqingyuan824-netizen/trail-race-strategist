"""Validation helpers for runner readiness inputs."""

from __future__ import annotations

from collections.abc import Mapping

from .specs import ALL_FIELDS, FIELD_SPECS, FORMAL_FIELDS, QUICK_FIELDS


class ValidationError(ValueError):
    """Raised when runner readiness input cannot be processed."""


REQUIRED_PROFILE_KEYS = {
    "schema_name",
    "schema_version",
    "generated_at",
    "generator_version",
    "safety_notice",
    "query",
    "identity",
    "performance",
    "race_results",
    "evidence",
}

REQUIRED_ANSWER_KEYS = {
    "schema_name",
    "schema_version",
    "generated_at",
    "generator_version",
    "mode",
    "subject",
    "default_source",
    "inputs",
}

FORBIDDEN_ATTACHMENTS = {
    "garmin",
    "coros",
    "strava",
    "screenshots",
    "device_exports",
    "exports",
    "watch_files",
}


def validate_runner_profile(profile: Mapping[str, object]) -> list[str]:
    """Return machine-readable validation errors for a runner profile."""

    errors: list[str] = []
    for key in REQUIRED_PROFILE_KEYS:
        if key not in profile:
            errors.append(f"missing_profile:{key}")
    if profile.get("schema_name") != "runner_profile":
        errors.append("schema_name:not_runner_profile")
    if profile.get("schema_version") != "1.0.0":
        errors.append("schema_version:unsupported")
    identity = profile.get("identity")
    performance = profile.get("performance")
    race_results = profile.get("race_results")
    if not isinstance(identity, Mapping):
        errors.append("identity:not_mapping")
    else:
        if not identity.get("runner_id"):
            errors.append("identity:missing_runner_id")
        if not identity.get("name"):
            errors.append("identity:missing_name")
    if not isinstance(performance, Mapping):
        errors.append("performance:not_mapping")
    else:
        if "general_pi" not in performance:
            errors.append("performance:missing_general_pi")
    if not isinstance(race_results, list):
        errors.append("race_results:not_list")
    if not isinstance(profile.get("evidence"), list) or not profile.get("evidence"):
        errors.append("evidence:empty_or_not_list")
    return errors


def validate_readiness_answers(answers: Mapping[str, object]) -> list[str]:
    """Return machine-readable validation errors for readiness answers."""

    errors: list[str] = []
    for key in REQUIRED_ANSWER_KEYS:
        if key not in answers:
            errors.append(f"missing_answers:{key}")
    if answers.get("schema_name") != "runner_readiness_input":
        errors.append("schema_name:not_runner_readiness_input")
    if answers.get("schema_version") != "1.0.0":
        errors.append("schema_version:unsupported")
    mode = answers.get("mode")
    if mode not in {"quick", "formal"}:
        errors.append("mode:unsupported")
    subject = answers.get("subject")
    if not isinstance(subject, Mapping):
        errors.append("subject:not_mapping")
    else:
        if not subject.get("runner_id"):
            errors.append("subject:missing_runner_id")
        if not subject.get("runner_name"):
            errors.append("subject:missing_runner_name")
    default_source = answers.get("default_source")
    if not isinstance(default_source, Mapping):
        errors.append("default_source:not_mapping")
    else:
        for key in ("source_type", "captured_at", "is_user_self_report", "confidence"):
            if key not in default_source:
                errors.append(f"default_source:missing_{key}")
    inputs = answers.get("inputs")
    if not isinstance(inputs, Mapping):
        errors.append("inputs:not_mapping")
        return errors
    for key in inputs:
        if key in FORBIDDEN_ATTACHMENTS:
            errors.append(f"forbidden_attachment:{key}")
        if key not in FIELD_SPECS and key != "goal_intensity_hint":
            errors.append(f"unknown_input:{key}")
    required_fields = QUICK_FIELDS if mode == "quick" else FORMAL_FIELDS
    for field_name in required_fields:
        if field_name not in inputs:
            errors.append(f"missing_input:{field_name}")
    return errors

