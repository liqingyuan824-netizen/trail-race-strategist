"""Stable Phase 13 contracts."""

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

FORBIDDEN_GENERAL_KEYS = {
    "name",
    "itra_id",
    "email",
    "phone",
    "identity_map",
    "health_details",
    "injury_details",
    "checkpoint_rows",
    "race_history",
}
