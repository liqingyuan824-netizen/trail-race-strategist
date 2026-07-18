"""Fail-closed validation for Phase 12."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .constants import ALLOWED_EVENT_TYPES, ALLOWED_SOURCE_TYPES


class LiveReplanningValidationError(ValueError):
    """Raised when a live snapshot would require invented or unsafe facts."""


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_inputs(race_plan: Mapping[str, Any], events: list[Mapping[str, Any]], as_of: str, mode: str) -> list[str]:
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
    if mode not in {"near_real_time", "delayed_replay"}:
        errors.append("invalid_processing_mode")
    as_of_dt = parse_datetime(as_of)
    if as_of_dt is None:
        errors.append("timezone_aware_as_of_required")
    for index, event in enumerate(events):
        prefix = f"event_{index}"
        if not event.get("event_id"):
            errors.append(f"{prefix}_event_id_required")
        if event.get("event_type") not in ALLOWED_EVENT_TYPES:
            errors.append(f"{prefix}_event_type_invalid")
        source = event.get("source")
        if not isinstance(source, Mapping) or source.get("source_type") not in ALLOWED_SOURCE_TYPES:
            errors.append(f"{prefix}_source_invalid")
        observed = parse_datetime(event.get("observed_at"))
        received = parse_datetime(event.get("received_at"))
        if observed is None or received is None:
            errors.append(f"{prefix}_timezone_aware_times_required")
        elif received < observed:
            errors.append(f"{prefix}_received_before_observed")
        elif as_of_dt is not None and received > as_of_dt:
            errors.append(f"{prefix}_received_after_as_of")
        try:
            confidence = float(event.get("confidence"))
            if not 0 <= confidence <= 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{prefix}_confidence_invalid")
        if not isinstance(event.get("payload"), Mapping):
            errors.append(f"{prefix}_payload_required")
        elif event.get("event_type") == "checkpoint":
            payload = event["payload"]
            try:
                sequence = int(payload.get("checkpoint_sequence"))
                elapsed = float(payload.get("elapsed_minutes"))
                if sequence < 1 or elapsed < 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{prefix}_checkpoint_payload_invalid")
            if payload.get("timing_kind", "manual") not in {"entry", "exit", "manual"}:
                errors.append(f"{prefix}_timing_kind_invalid")
    return errors
