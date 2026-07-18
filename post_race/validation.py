"""Validation for Phase 13 inputs and isolation boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class PostRaceValidationError(ValueError):
    """Raised when a retro would violate evidence or privacy boundaries."""


def validate_inputs(race_plan: Mapping[str, Any], actual_result: Mapping[str, Any], conditions: Mapping[str, Any], validation_context: str) -> list[str]:
    errors: list[str] = []
    if race_plan.get("schema_name") != "race_plan":
        errors.append("race_plan_required")
    governance = race_plan.get("governance", {})
    if governance.get("phase8a_validation_decision") != "retain_distance_only":
        errors.append("retain_distance_only_required")
    selected_model = governance.get("selected_model", race_plan.get("baseline_binding", {}).get("model_id"))
    if selected_model != "distance_only":
        errors.append("distance_only_required")
    if governance.get("full_model_status") not in {None, "rejected"}:
        errors.append("full_model_must_be_rejected")
    if governance.get("holdout_evaluation_run") is not False:
        errors.append("holdout_must_remain_unrun")
    if governance.get("user_facing_prediction_allowed") is not False:
        errors.append("user_facing_prediction_must_be_false")
    if actual_result.get("schema_name") != "actual_race_result":
        errors.append("actual_race_result_required")
    status = actual_result.get("result_status")
    if status not in {"finish", "dnf", "dns"}:
        errors.append("result_status_invalid")
    finish = actual_result.get("finish_time_minutes")
    if status == "finish" and not isinstance(finish, (int, float)):
        errors.append("finish_time_required_for_finish")
    if status != "finish" and finish is not None:
        errors.append("nonfinish_time_must_be_null")
    if not isinstance(actual_result.get("checkpoints", []), list):
        errors.append("checkpoints_must_be_list")
    else:
        for index, row in enumerate(actual_result.get("checkpoints", [])):
            if not isinstance(row, Mapping) or not isinstance(row.get("sequence"), int) or row.get("sequence", 0) < 1:
                errors.append(f"checkpoint_{index}_sequence_invalid")
                continue
            if row.get("elapsed_minutes") is not None and (not isinstance(row.get("elapsed_minutes"), (int, float)) or row["elapsed_minutes"] < 0):
                errors.append(f"checkpoint_{index}_elapsed_invalid")
            if row.get("source_type") not in {"official_timing", "participant_confirmation", "device_export", "synthetic"}:
                errors.append(f"checkpoint_{index}_source_type_invalid")
    source = actual_result.get("source")
    if not isinstance(source, Mapping) or source.get("source_type") not in {"official_result", "official_timing", "participant_confirmation", "device_export", "public_official_result", "synthetic"}:
        errors.append("actual_result_source_required")
    if conditions.get("schema_name") != "post_race_conditions":
        errors.append("post_race_conditions_required")
    if validation_context not in {"synthetic", "historical_replay", "future_event"}:
        errors.append("validation_context_invalid")
    return errors
