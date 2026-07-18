"""Strict no-leakage validation for Phase 7B/8B inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .constants import ALLOWED_SPLITS, FORBIDDEN_SPLITS


class ReferenceInputError(ValueError):
    """Raised before any graph or prediction is constructed."""


def parse_time(value: Any) -> datetime:
    if not value:
        raise ReferenceInputError("timestamp_required")
    text = str(value).strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReferenceInputError(f"invalid_timestamp:{value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def as_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ReferenceInputError(f"invalid_number:{field}") from exc
    if number <= 0:
        raise ReferenceInputError(f"non_positive_number:{field}")
    return number


def validate_target(target: Mapping[str, Any]) -> None:
    if not str(target.get("target_race_id") or "").strip():
        raise ReferenceInputError("target_race_id_required")
    if not str(target.get("target_runner_id") or "").startswith(("runner_", "participant_", "synthetic_")):
        raise ReferenceInputError("anonymous_target_runner_id_required")
    parse_time(target.get("prediction_as_of"))
    parse_time(target.get("race_date"))
    if parse_time(target["race_date"]) < parse_time(target["prediction_as_of"]):
        raise ReferenceInputError("target_race_must_not_precede_prediction_time")
    as_float(target.get("distance_km"), "target.distance_km")
    as_float(target.get("elevation_gain_m"), "target.elevation_gain_m")


def validate_records(records: Sequence[Mapping[str, Any]], target: Mapping[str, Any]) -> None:
    cutoff = parse_time(target["prediction_as_of"])
    target_race_id = str(target["target_race_id"])
    ids: set[str] = set()
    for record in records:
        record_id = str(record.get("record_id") or "")
        if not record_id or record_id in ids:
            raise ReferenceInputError("record_id_missing_or_duplicate")
        ids.add(record_id)
        split = str(record.get("split") or "")
        if split in FORBIDDEN_SPLITS:
            raise ReferenceInputError(f"forbidden_split:{split}:{record_id}")
        if split not in ALLOWED_SPLITS:
            raise ReferenceInputError(f"unapproved_split:{split or 'missing'}:{record_id}")
        if record.get("authorized_for_internal_research") is not True:
            raise ReferenceInputError(f"internal_research_authorization_required:{record_id}")
        if record.get("result_status") != "finish":
            raise ReferenceInputError(f"finished_record_required:{record_id}")
        observed_at = parse_time(record.get("available_at") or record.get("race_date"))
        race_date = parse_time(record.get("race_date"))
        if observed_at > cutoff or race_date > cutoff or race_date >= parse_time(target["race_date"]):
            raise ReferenceInputError(f"future_information_blocked:{record_id}")
        if str(record.get("race_id") or "") == target_race_id:
            raise ReferenceInputError(f"target_race_result_blocked:{record_id}")
        runner_id = str(record.get("runner_id") or "")
        if not runner_id.startswith(("runner_", "participant_", "synthetic_")):
            raise ReferenceInputError(f"anonymous_runner_id_required:{record_id}")
        as_float(record.get("distance_km"), f"{record_id}.distance_km")
        as_float(record.get("elevation_gain_m"), f"{record_id}.elevation_gain_m")
        as_float(record.get("finish_time_minutes"), f"{record_id}.finish_time_minutes")
        source = record.get("source")
        if not isinstance(source, Mapping):
            raise ReferenceInputError(f"source_required:{record_id}")
        for field in ("source_type", "source_uri", "source_fingerprint", "captured_at"):
            if not source.get(field):
                raise ReferenceInputError(f"source_field_required:{field}:{record_id}")
        confidence = float(source.get("confidence", -1))
        if not 0 <= confidence <= 1:
            raise ReferenceInputError(f"source_confidence_out_of_range:{record_id}")


def validate_baseline(baseline: Mapping[str, Any]) -> None:
    if baseline.get("model_id") != "distance_only":
        raise ReferenceInputError("distance_only_baseline_required")
    if baseline.get("selection_decision") != "retain_distance_only":
        raise ReferenceInputError("retain_distance_only_required")
    if baseline.get("user_facing_prediction_allowed") is not False:
        raise ReferenceInputError("baseline_user_facing_must_be_false")
    if baseline.get("calibrated") is not False:
        raise ReferenceInputError("baseline_must_not_claim_calibration")
    values = baseline.get("finish_range_minutes")
    if not isinstance(values, Mapping):
        raise ReferenceInputError("baseline_finish_range_required")
    lower = as_float(values.get("lower_minutes"), "baseline.lower")
    midpoint = as_float(values.get("midpoint_minutes"), "baseline.midpoint")
    upper = as_float(values.get("upper_minutes"), "baseline.upper")
    if not lower <= midpoint <= upper:
        raise ReferenceInputError("baseline_finish_range_not_ordered")
