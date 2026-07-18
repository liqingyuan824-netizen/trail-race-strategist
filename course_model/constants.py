"""Shared constants for the course model pipeline."""

SCHEMA_NAME = "course_model"
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

UNIFIED_CP_TYPES = (
    "single_timing",
    "entry_exit_timing",
    "manual_observation",
    "estimated_station",
    "no_live_timing",
)
