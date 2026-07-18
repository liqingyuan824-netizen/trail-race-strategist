"""Fail-closed input validation for Phase 10."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class SupportPlanValidationError(ValueError):
    """Raised when a support plan would require invented facts."""


def validate_inputs(
    *, race_plan: Mapping[str, Any], course_model: Mapping[str, Any], support_inputs: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if race_plan.get("schema_name") != "race_plan":
        errors.append("race_plan_schema_required")
    governance = race_plan.get("governance", {})
    if governance.get("phase8a_validation_decision") != "retain_distance_only":
        errors.append("retain_distance_only_required")
    if governance.get("holdout_evaluation_run") is not False:
        errors.append("holdout_must_remain_not_run")
    if governance.get("user_facing_prediction_allowed") is not False:
        errors.append("user_facing_prediction_must_be_false")
    if course_model.get("schema_name") != "course_model":
        errors.append("course_model_schema_required")
    cp_points = course_model.get("event", {}).get("course", {}).get("cp_model", {}).get("cp_points")
    if not isinstance(cp_points, list) or len(cp_points) < 2:
        errors.append("course_cp_points_required")
    if support_inputs.get("schema_name") != "race_support_inputs":
        errors.append("race_support_inputs_schema_required")
    for key in ("carbohydrate_g_per_hour", "fluid_ml_per_hour", "electrolyte_mg_per_hour"):
        item = support_inputs.get("intake_targets", {}).get(key)
        if item is not None and not isinstance(item, Mapping):
            errors.append(f"{key}_must_be_object_or_null")
        elif isinstance(item, Mapping) and item.get("verified_in_training") is not True:
            errors.append(f"{key}_requires_training_verification")
    return errors
