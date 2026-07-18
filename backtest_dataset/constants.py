"""Shared constants for the Phase 8A.1 dataset layer."""

from __future__ import annotations

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

FROZEN_MODELS = [
    "distance_plus_climb_load_transfer_v2",
    "distance_only",
]

ALLOWED_SOURCE_KINDS = {
    "user_supplied",
    "race_organizer_authorized",
    "official_public",
    "open_dataset",
    "local_evidence",
    "synthetic_fixture",
}

COMPLIANCE_STATUSES = {
    "usable",
    "restricted",
    "blocked_by_data_rights",
    "insufficient_history",
    "missing_course_data",
    "invalid_record",
}

RUNNER_SPLITS = ("development", "validation", "holdout")

