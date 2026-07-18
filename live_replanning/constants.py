"""Stable Phase 12 contracts."""

SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "0.1.0"
SOURCE_POLICY_VERSION = "1.0.0"
CACHE_POLICY_VERSION = "1.0.0"

SAFETY_NOTICE = {
    "version": "1.0.0",
    "medical_advice": False,
    "replaces_race_rules": False,
    "message": "This tool does not replace race rules, on-site safety, or professional medical judgment.",
}

ALLOWED_SOURCE_TYPES = {
    "official_timing",
    "family_observation",
    "runner_report",
    "weather_event",
    "course_event",
    "race_staff",
    "medical_staff",
    "system_estimate",
}
ALLOWED_EVENT_TYPES = {
    "checkpoint",
    "runner_state",
    "weather",
    "course",
    "race_instruction",
    "medical_instruction",
    "equipment",
    "fueling",
}
RED_FLAGS = {
    "chest_pain",
    "fainting",
    "altered_consciousness",
    "severe_breathing_difficulty",
    "severe_dehydration",
    "heat_illness",
    "confusion",
    "uncontrolled_vomiting",
    "suspected_fracture",
    "cannot_bear_weight",
    "acute_severe_pain",
}
