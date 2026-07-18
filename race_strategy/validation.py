"""Validation for Phase 9 race-plan inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class StrategyValidationError(ValueError):
    """Raised when a race plan cannot be built without inventing facts."""


_STRUCTURED_CP_KINDS = {"official_cp_table", "official_structured_cp_table", "official_gpx"}
_VISUAL_CP_KINDS = {"official_visual_transcription", "official_roadbook_visual_transcription"}
_HISTORICAL_CP_KINDS = {"official_historical_reference"}


def is_historical_reference_cp_set(cp_points: Any) -> bool:
    """Return whether every CP row is explicitly a non-target-year reference."""
    return (
        isinstance(cp_points, list)
        and len(cp_points) >= 3
        and all(
            isinstance(row, Mapping)
            and row.get("evidence_tier") == "official_historical_reference"
            and row.get("source_kind") in _HISTORICAL_CP_KINDS
            for row in cp_points
        )
    )


def full_cp_evidence_errors_from_manifest(
    manifest: Mapping[str, Any], *, year: Any, group_code: Any, group_name: Any,
) -> list[str]:
    """Run the CP gate from persisted manifest evidence only."""
    if not isinstance(manifest, Mapping):
        return ["wechat_manifest_required"]
    selection = manifest.get("visual_selection")
    if not isinstance(selection, Mapping):
        return ["wechat_visual_selection_required"]
    visual_candidates = selection.get("attempts")
    if not isinstance(visual_candidates, list):
        visual_candidates = selection.get("selected")
    cp_rows = manifest.get("cp_evidence_rows")
    return full_cp_evidence_errors(
        cp_rows if isinstance(cp_rows, list) else [],
        year=year,
        group_code=group_code,
        group_name=group_name,
        visual_candidates=visual_candidates,
    )


def _suspected_route_visual_errors(visual_candidates: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(visual_candidates, list):
        return errors
    for index, candidate in enumerate(visual_candidates):
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or candidate.get("source_url") or index)
        validity = candidate.get("validity_status") or (candidate.get("content_validity") or {}).get("status")
        review = candidate.get("visual_review")
        review_status = review.get("status") if isinstance(review, Mapping) else candidate.get("review_status")
        transcription_status = review.get("transcription_status") if isinstance(review, Mapping) else candidate.get("transcription_status")
        if validity != "valid" and candidate.get("suspected_route_map"):
            errors.append(f"suspected_route_map_content_invalid:{candidate_id}")
        elif validity == "valid" and review_status in {None, "", "not_reviewed"}:
            errors.append(
                f"suspected_route_map_unreviewed:{candidate_id}"
                if candidate.get("suspected_route_map")
                else f"valid_body_image_unreviewed:{candidate_id}"
            )
        elif validity == "valid" and review_status not in {"reviewed", "reviewed_no_cp", "reviewed_cp_transcribed", "completed"}:
            errors.append(
                f"suspected_route_map_review_status_invalid:{candidate_id}"
                if candidate.get("suspected_route_map")
                else f"valid_body_image_review_status_invalid:{candidate_id}"
            )
        elif validity == "valid" and review_status in {"reviewed", "reviewed_no_cp"} and transcription_status not in {"completed", "not_required"}:
            errors.append(
                f"suspected_route_map_reviewed_without_cp_transcription:{candidate_id}"
                if candidate.get("suspected_route_map")
                else f"valid_body_image_reviewed_without_transcription_status:{candidate_id}"
            )
    return errors


def full_cp_evidence_errors(
    cp_points: Any, *, year: Any, group_code: Any, group_name: Any,
    visual_candidates: Any = None, allow_historical_reference: bool = False,
) -> list[str]:
    """Return errors when CP rows cannot support an executable strategy report."""
    visual_errors = _suspected_route_visual_errors(visual_candidates)
    if allow_historical_reference and is_historical_reference_cp_set(cp_points):
        return visual_errors
    if not isinstance(cp_points, list) or len(cp_points) < 3:
        return visual_errors or ["intermediate_official_cp_required"]
    if all(str(row.get("source_kind") or "") == "derived" for row in cp_points if isinstance(row, Mapping)):
        return visual_errors or ["derived_cp_rows_cannot_support_full_strategy"]
    errors: list[str] = list(visual_errors)
    for index, row in enumerate(cp_points):
        if not isinstance(row, Mapping):
            errors.append(f"cp_row_not_mapping:{index}")
            continue
        if row.get("evidence_tier") != "current_year_official" or row.get("source_year") != year:
            errors.append(f"cp_row_not_target_year_official:{index}")
        if row.get("applicable_group") not in {group_code, group_name}:
            errors.append(f"cp_row_group_binding_invalid:{index}")
        kind = str(row.get("source_kind") or "")
        if kind in _STRUCTURED_CP_KINDS:
            continue
        if kind not in _VISUAL_CP_KINDS:
            errors.append(f"cp_row_source_kind_invalid:{index}")
            continue
        transcription = row.get("visual_transcription")
        if not isinstance(transcription, Mapping) or not all(
            transcription.get(key) for key in ("source_url", "retrieved_at", "raw_sha256", "applicable_year", "applicable_group", "parser_method")
        ):
            errors.append(f"visual_cp_transcription_provenance_incomplete:{index}")
        elif transcription.get("applicable_year") != year or transcription.get("applicable_group") not in {group_code, group_name}:
            errors.append(f"visual_cp_transcription_binding_invalid:{index}")
    return errors


def _range_errors(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{prefix}_missing"]
    try:
        lower = float(value["lower_minutes"])
        midpoint = float(value["midpoint_minutes"])
        upper = float(value["upper_minutes"])
    except (KeyError, TypeError, ValueError):
        return [f"{prefix}_invalid"]
    if lower <= 0 or not lower <= midpoint <= upper:
        return [f"{prefix}_not_ordered"]
    return []


def validate_inputs(
    *,
    course_model: Mapping[str, Any],
    current_readiness: Mapping[str, Any],
    distance_only_baseline: Mapping[str, Any],
    allow_historical_reference: bool = False,
) -> list[str]:
    errors: list[str] = []
    if course_model.get("schema_name") != "course_model":
        errors.append("course_model_schema_required")
    event = course_model.get("event")
    if not isinstance(event, Mapping):
        errors.append("course_model_event_required")
    else:
        grade = event.get("grade", {}).get("grade")
        if grade not in {"A", "B"}:
            errors.append("course_grade_a_or_b_required")
        cp_model = event.get("course", {}).get("cp_model", {})
        if cp_model.get("status") not in {"complete", "partial"}:
            errors.append("verified_cp_model_required")
        errors.extend(full_cp_evidence_errors(
            cp_model.get("cp_points", []), year=event.get("year"),
            group_code=event.get("group_code"), group_name=event.get("group_name"),
            visual_candidates=event.get("visual_evidence_attempts") or event.get("visual_evidence"),
            allow_historical_reference=allow_historical_reference,
        ))
        capture = event.get("target_group_capture")
        if not isinstance(capture, Mapping):
            errors.append("target_group_capture_receipt_required")
        else:
            if capture.get("capture_attempt_status") != "completed":
                errors.append("official_group_capture_not_completed")
            binding = capture.get("identity_binding")
            if not isinstance(binding, Mapping) or binding.get("status") != "verified":
                errors.append("target_group_identity_not_verified")
            else:
                for field in ("official_name", "year", "group_code", "group_name"):
                    if binding.get(field) != event.get(field):
                        errors.append("target_group_capture_binding_mismatch")
                        break

    if current_readiness.get("schema_name") != "current_readiness":
        errors.append("current_readiness_schema_required")
    assessment = current_readiness.get("assessment")
    if not isinstance(assessment, Mapping):
        errors.append("readiness_assessment_required")
    else:
        if assessment.get("risk_level") not in {"green", "yellow", "red"}:
            errors.append("valid_risk_level_required")
        if not assessment.get("planning_permission"):
            errors.append("planning_permission_required")
    privacy_mode = current_readiness.get("privacy_mode", "private_alias")
    if privacy_mode not in {"authorized_private", "private_alias", "public_shareable"}:
        errors.append("privacy_mode_invalid")

    if distance_only_baseline.get("schema_name") != "internal_distance_only_baseline":
        errors.append("internal_distance_only_baseline_required")
    if distance_only_baseline.get("model_id") != "distance_only":
        errors.append("distance_only_model_required")
    if distance_only_baseline.get("selection_decision") != "retain_distance_only":
        errors.append("retain_distance_only_decision_required")
    if distance_only_baseline.get("user_facing_prediction_allowed") is not False:
        errors.append("user_facing_prediction_must_be_false")
    if distance_only_baseline.get("calibrated") is not False:
        errors.append("baseline_must_not_claim_calibration")
    errors.extend(_range_errors(distance_only_baseline.get("finish_range_minutes"), "finish_range"))
    return errors
