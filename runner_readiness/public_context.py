"""Conservative readiness boundary when no current health form was supplied."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .specs import GENERATOR_VERSION, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION


def build_public_only_readiness(*, request_binding: Mapping[str, Any]) -> dict[str, Any]:
    """Do not infer health from public history; cap planning at yellow."""

    return {
        "schema_name": "current_readiness", "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(), "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION, "safety_notice": SAFETY_NOTICE,
        "request_binding": dict(request_binding),
        "assessment": {
            "risk_level": "yellow", "planning_permission": "conservative_planning_only",
            "red_flags": [], "yellow_flags": ["current_health_and_training_not_self_reported"],
            "health_state": "not_assessed_from_public_data",
            "public_history_is_not_current_health_evidence": True,
        },
        "unavailable_fields": [
            "current_injury_status", "current_illness_status", "current_fatigue", "recent_training_load",
            "carb_intake_per_hour_g", "hydration_rate_ml_per_hour", "lowest_temperature_c",
        ],
        "limitations": ["This conservative boundary enables planning structure, not a medical or readiness conclusion."],
    }
