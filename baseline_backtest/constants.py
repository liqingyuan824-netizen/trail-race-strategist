"""Shared constants for the Phase 8A baseline backtest module."""

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

MODEL_NAME = "distance_plus_climb_load_transfer_v2"
MODEL_CODE_VERSION = "phase8a.backtest.freeze.v1"
MODEL_FORMULA_VERSION = "distance_plus_climb_load_transfer_v2"
MODEL_PARAMETERS = {
    "distance_component": "target_distance_km / source_distance_km",
    "climb_component": "(target_distance_km + target_elevation_gain_m / 100) / (source_distance_km + source_elevation_gain_m / 100)",
    "recency_half_life_days": 150.0,
    "source_quality_provenance_floor": 0.97,
    "official_data_confidence_default": 0.96,
    "self_report_data_confidence_default": 0.98,
    "condition_similarity_default": 0.5,
    "course_grade_penalty_default": 0.0,
}

MIN_PREDICTION_HISTORY = 1
MIN_CALIBRATION_SAMPLES = 30
MAX_CALIBRATION_SAMPLES = 50

