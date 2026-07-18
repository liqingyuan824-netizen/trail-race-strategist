"""Frozen governance and formula constants for Phase 7B/8B research work."""

SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "0.1.0"
SOURCE_POLICY_VERSION = "1.0.0"
CACHE_POLICY_VERSION = "1.0.0"
MODEL_ID = "phase8b_multipath_unvalidated_v1"
ALLOWED_SPLITS = {"development", "public_authorized", "synthetic"}
FORBIDDEN_SPLITS = {"validation", "holdout"}

SAFETY_NOTICE = {
    "version": "1.0.0",
    "medical_advice": False,
    "replaces_race_rules": False,
    "message": "This tool does not replace race rules, on-site safety, or professional medical judgment.",
}

GOVERNANCE = {
    "phase8a_validation_decision": "retain_distance_only",
    "phase8a_full_model_status": "rejected",
    "retained_reference_model": "distance_only",
    "candidate_status": "internal_unvalidated_research_candidate",
    "model_validated": False,
    "user_facing_prediction_allowed": False,
    "claims_better_than_baseline": False,
    "validation_data_used": False,
    "holdout_data_used": False,
    "holdout_evaluation_run": False,
    "future_reevaluation_requires_new_data_and_new_protocol": True,
}

PATH_BASE_WEIGHTS = {
    "distance_only": 1.0,
    "same_runner_same_event": 0.82,
    "self_history_similar_course": 0.68,
    "similar_runner_cross_event": 0.50,
}

DISTANCE_BANDS = (
    (30.0, "short", 1.03, 0.08),
    (80.0, "mid_long", 1.06, 0.12),
    (130.0, "100k", 1.10, 0.17),
    (float("inf"), "100m", 1.14, 0.22),
)
