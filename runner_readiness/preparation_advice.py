"""Restricted, non-predictive training-preparation advice for W3.

This module deliberately consumes only the readiness artifact and a verified
course model.  It does not import device-ingest code, prediction code, report
renderers, or race-planning time calculations.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from race_strategy.validation import full_cp_evidence_errors

from .normalization import fingerprint


_ADVICE_CATEGORIES = (
    "conditional_training_focus",
    "conditional_load_adjustment",
    "long_distance_elevation_rehearsal",
    "fueling_rehearsal",
    "taper_timing",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _evidence_gate(course_model: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the persisted CP and target-group binding rules without using a plan."""
    errors: list[str] = []
    event = course_model.get("event") if course_model.get("schema_name") == "course_model" else None
    if event is None:
        errors.append("course_model_event_required")
    if course_model.get("schema_name") != "course_model":
        errors.insert(0, "course_model_schema_required")
    if not isinstance(event, Mapping):
        return {"target_year": None, "exact_group": None, "passed": False, "failure_codes": errors}

    course = event.get("course")
    cp_model = course.get("cp_model") if isinstance(course, Mapping) else None
    if not isinstance(cp_model, Mapping) or cp_model.get("status") not in {"complete", "partial"}:
        errors.append("verified_cp_model_required")
        cp_points: Any = []
    else:
        cp_points = cp_model.get("cp_points", [])
    errors.extend(full_cp_evidence_errors(
        cp_points,
        year=event.get("year"),
        group_code=event.get("group_code"),
        group_name=event.get("group_name"),
        visual_candidates=event.get("visual_evidence_attempts") or event.get("visual_evidence"),
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
        elif any(binding.get(field) != event.get(field) for field in ("official_name", "year", "group_code", "group_name")):
            errors.append("target_group_capture_binding_mismatch")
    return {
        "target_year": event.get("year"),
        "exact_group": event.get("group_code") or event.get("group_name"),
        "passed": not errors,
        "failure_codes": list(dict.fromkeys(errors)),
    }


def _wearable_trace(current_readiness: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    exposure = current_readiness.get("wearable_training_exposure")
    evidence = current_readiness.get("evidence")
    if not isinstance(exposure, Mapping):
        return {"wearable_summary_status": "wearable_summary_unavailable"}, None
    summary_evidence = next(
        (item for item in evidence if isinstance(item, Mapping) and item.get("source_type") == "wearable_feature_summary"),
        None,
    ) if isinstance(evidence, list) else None
    if not isinstance(summary_evidence, Mapping):
        return {"wearable_summary_status": "wearable_summary_unavailable"}, None
    trace = {
        "summary_id": exposure.get("summary_id"),
        "generated_at": exposure.get("generated_at"),
        "import_request_ids": sorted(str(item) for item in exposure.get("import_request_ids", []) if isinstance(item, str)),
        "summary_fingerprint": summary_evidence.get("source_fingerprint"),
    }
    if not all(trace.values()) or not isinstance(exposure.get("quality"), Mapping) or not isinstance(exposure.get("uncertainty"), Mapping):
        return {"wearable_summary_status": "wearable_summary_unavailable"}, None
    return trace, dict(exposure)


def _data_sufficiency(exposure: Mapping[str, Any] | None) -> dict[str, Any]:
    if exposure is None:
        return {
            "status": "insufficient",
            "quality_or_missing_reasons": ["wearable_summary_unavailable"],
            "non_private_next_steps": ["Use verified public course information and a later readiness recheck before changing the plan."],
        }
    uncertainty = exposure["uncertainty"]
    quality = exposure["quality"]
    level = uncertainty.get("level")
    if level == "low":
        status = "sufficient"
    elif level in {"medium", "high"}:
        status = "limited"
    else:
        status = "insufficient"
    reasons = uncertainty.get("reasons") or quality.get("missing_data_flags") or []
    return {
        "status": status,
        "quality_or_missing_reasons": [str(item) for item in reasons],
        "non_private_next_steps": ["Recheck readiness and the verified public course record before changing the plan."],
    }


def _advice_item(category: str, condition: str, action: str, rationale: str) -> dict[str, Any]:
    return {"category": category, "condition": condition, "action": action, "rationale": rationale, "requires_recheck": True}


def _restricted_advice(*, permission: str, uncertainty_level: str | None) -> list[dict[str, Any]]:
    constrained = permission in {"conservative_planning_only", "aggressive_plan_blocked"} or uncertainty_level in {"medium", "high", None}
    condition = "Only if the next readiness recheck keeps the same or safer permission and no red flags are present."
    if constrained:
        return [
            _advice_item("conditional_training_focus", condition, "Maintain a conservative focus and verify readiness before any change.", "Permission or data uncertainty requires a non-escalating plan."),
            _advice_item("conditional_load_adjustment", condition, "Maintain or reduce training load if the recheck is less favorable; do not escalate it.", "Wearable context may only tighten the plan."),
            _advice_item("long_distance_elevation_rehearsal", condition, "Keep any long-distance or elevation rehearsal controlled and do not escalate its demand from this summary.", "Uncertain exposure cannot justify progression."),
            _advice_item("fueling_rehearsal", condition, "Use only a conservative fueling rehearsal and recheck tolerance through the existing readiness process.", "This is practice guidance, not a performance prescription."),
            _advice_item("taper_timing", condition, "Prefer maintaining or beginning a conservative reduction when the next recheck indicates added uncertainty.", "No timing dose is inferred from the summary."),
        ]
    return [
        _advice_item("conditional_training_focus", condition, "Maintain the current training focus; do not treat this summary as a reason to intensify it.", "A validated summary supplies context only."),
        _advice_item("conditional_load_adjustment", condition, "Adjust load only after a readiness recheck; reduce or maintain it if any uncertainty increases.", "The summary cannot relax existing safety limits."),
        _advice_item("long_distance_elevation_rehearsal", condition, "Plan a controlled long-distance and elevation rehearsal only after the next safety recheck.", "The verified course gate permits preparation context, not a route substitute."),
        _advice_item("fueling_rehearsal", condition, "Practice the planned fueling approach conservatively and recheck any concerns through readiness intake.", "No intake quantity or medical conclusion is inferred."),
        _advice_item("taper_timing", condition, "Use the next readiness recheck to choose a conservative reduction phase rather than adding workload late.", "This does not prescribe a date or quantity."),
    ]


def build_training_preparation_advice(*, current_readiness: Mapping[str, Any], course_model: Mapping[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    """Build the W3 JSON artifact without predictions, route facts, or raw data."""
    assessment = current_readiness.get("assessment") if isinstance(current_readiness, Mapping) else None
    if current_readiness.get("schema_name") != "current_readiness" or not isinstance(assessment, Mapping):
        raise ValueError("current_readiness_schema_and_assessment_required")
    risk_level = assessment.get("risk_level")
    permission = assessment.get("planning_permission")
    if risk_level not in {"green", "yellow", "red"} or not isinstance(permission, str):
        raise ValueError("current_readiness_safety_gate_required")

    evidence_gate = _evidence_gate(course_model)
    trace, exposure = _wearable_trace(current_readiness)
    sufficiency = _data_sufficiency(exposure)
    uncertainty_level = exposure["uncertainty"].get("level") if exposure is not None else None
    red_or_stop = risk_level == "red" or permission == "stop_and_seek_professional_assessment" or bool(assessment.get("red_flags"))
    if not evidence_gate["passed"]:
        advice: list[dict[str, Any]] = []
        sufficiency["status"] = "insufficient"
        sufficiency["quality_or_missing_reasons"] = list(dict.fromkeys(sufficiency["quality_or_missing_reasons"] + evidence_gate["failure_codes"]))
        safety_notice = "Preparation advice is unavailable until the persisted course and target-group evidence gate passes."
    elif red_or_stop:
        advice = []
        safety_notice = "Stop planned intensity changes and seek professional assessment; wearable context cannot override this safety gate."
    else:
        advice = _restricted_advice(permission=permission, uncertainty_level=uncertainty_level)
        safety_notice = "Conditional preparation guidance only; it is not medical advice, a performance forecast, or race strategy."

    return {
        "schema_name": "training_preparation_advice",
        "schema_version": "1.0.0",
        "generated_at": generated_at or _utc_now(),
        "safety_notice": safety_notice,
        "source_trace": {"current_readiness_cache_key": current_readiness.get("cache_key"), "readiness_fingerprint": fingerprint(current_readiness), **trace},
        "evidence_gate": evidence_gate,
        "facts": {"current_readiness_available": True, "wearable_summary_status": "available" if exposure is not None else "wearable_summary_unavailable", "wearable_uncertainty_level": uncertainty_level, "safety_permission_source": "current_readiness"},
        "estimates": [],
        "advice": advice,
        "data_sufficiency": sufficiency,
        "safety_gate": {"risk_level": risk_level, "planning_permission": permission, "wearable_cannot_override": True},
        "prohibited_output_guards": {"user_facing_prediction_allowed": False, "finish_prediction_included": False, "cp_timing_included": False},
    }
