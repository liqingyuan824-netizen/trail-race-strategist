"""Pipeline for Phase 7A baseline prediction."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from .constants import CACHE_POLICY_VERSION, GENERATOR_VERSION, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION
from .normalization import normalize_baseline_inputs
from .ranges import build_baseline_candidate_ranges
from .report import build_audit_report
from .selection import build_historical_race_selection
from .validation import ValidationError, validate_baseline_inputs, validate_baseline_operational_gate


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _target_event_from_course_model(course_model: Mapping[str, Any]) -> dict[str, Any]:
    event = course_model.get("event", {})
    course = event.get("course", {})
    grade = event.get("grade", {})
    route_text = course.get("route_text", {})
    route_text_value = route_text.get("value") if isinstance(route_text, Mapping) else route_text
    route_text_text = str(route_text_value or "")
    condition_tags: list[str] = []
    route_text_lower = route_text_text.lower()
    if any(keyword in route_text_lower for keyword in ("沙漠", "sand", "desert", "沙地")):
        condition_tags.append("desert_sand")
    return {
        "event_name": event.get("official_name"),
        "group_name": event.get("group_name"),
        "group_code": event.get("group_code"),
        "grade": grade.get("grade"),
        "route_version_state": event.get("route_version_state"),
        "distance_km": course.get("total_distance_km", {}).get("value"),
        "elevation_gain_m": course.get("total_elevation_gain_m", {}).get("value"),
        "distance_source_note": course.get("total_distance_km", {}).get("note"),
        "elevation_source_note": course.get("total_elevation_gain_m", {}).get("note"),
        "route_status": event.get("course", {}).get("route_version", {}).get("status"),
        "route_text": route_text_value,
        "condition_tags": condition_tags,
        "condition_status": "official_explicit" if condition_tags else "unknown",
        "condition_policy_notes": [
            "Target condition tags only come from official course text.",
            "No time adjustment is made from target surface tags alone.",
        ] if condition_tags else [
            "No official course text explicitly confirms desert / sand conditions.",
            "The condition field stays unknown and does not drive any extra time adjustment.",
        ],
    }


def build_baseline_prediction(
    *,
    runner_profile: Mapping[str, Any],
    current_readiness: Mapping[str, Any],
    course_model: Mapping[str, Any],
) -> dict[str, Any]:
    request_binding = runner_profile.get("request_binding") if isinstance(runner_profile.get("request_binding"), Mapping) else None
    readiness_binding = current_readiness.get("request_binding") if isinstance(current_readiness.get("request_binding"), Mapping) else None
    if request_binding is not None and request_binding != readiness_binding:
        raise ValidationError("REQUEST_BINDING_MISMATCH_PROFILE_READINESS")
    target_event = _target_event_from_course_model(course_model)
    inputs = {
        "schema_name": "baseline_prediction_inputs",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "runner_profile": runner_profile,
        "current_readiness": current_readiness,
        "course_model": course_model,
        "target_event": target_event,
    }
    errors = validate_baseline_inputs(inputs)
    if errors:
        raise ValidationError("; ".join(errors))

    gate_errors = validate_baseline_operational_gate(current_readiness)
    if gate_errors:
        raise ValidationError("; ".join(gate_errors))

    baseline_inputs = normalize_baseline_inputs(
        runner_profile=runner_profile,
        current_readiness=current_readiness,
        course_model=course_model,
        target_event=target_event,
    )
    if request_binding is not None:
        baseline_inputs["request_binding"] = dict(request_binding)
    try:
        historical_selection = build_historical_race_selection(
            runner_profile=baseline_inputs["runner_profile"],
            current_readiness=current_readiness,
            target_event=target_event,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if course_model.get("event", {}).get("grade", {}).get("grade") == "C":
        cp_model = course_model.get("event", {}).get("course", {}).get("cp_model", {})
        if int(cp_model.get("cp_count", 0) or 0) > 0 or int(cp_model.get("segment_count", 0) or 0) > 0:
            raise ValidationError("c_grade_cp_generation_blocked")
    try:
        candidate_ranges = build_baseline_candidate_ranges(
            baseline_inputs=baseline_inputs,
            historical_selection=historical_selection,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    outputs = {
        "baseline_prediction_inputs": baseline_inputs,
        "historical_race_selection": historical_selection,
        "baseline_candidate_ranges": candidate_ranges,
        "audit_report": build_audit_report(
            baseline_inputs=baseline_inputs,
            historical_selection=historical_selection,
            candidate_ranges=candidate_ranges,
            c_grade_source_path=str(Path(__file__).resolve().parents[1] / "course_model.json"),
            a_grade_source_path=str(Path(__file__).resolve().parents[1] / "evidence" / "phase5b-shudao-20k-20261108" / "course_model.json"),
        ),
    }
    if request_binding is not None:
        outputs["baseline_candidate_ranges"]["request_binding"] = dict(request_binding)
    return outputs


def write_baseline_outputs(outputs: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "baseline_prediction_inputs.json").write_text(
        json.dumps(outputs["baseline_prediction_inputs"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "historical_race_selection.json").write_text(
        json.dumps(outputs["historical_race_selection"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "baseline_candidate_ranges.json").write_text(
        json.dumps(outputs["baseline_candidate_ranges"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "baseline_prediction_audit_report.md").write_text(outputs["audit_report"], encoding="utf-8")


def replay_baseline_prediction(*, runner_profile_path: Path, readiness_path: Path, course_model_path: Path) -> dict[str, Any]:
    runner_profile = _load_json(runner_profile_path)
    readiness = _load_json(readiness_path)
    course_model = _load_json(course_model_path)
    return build_baseline_prediction(
        runner_profile=runner_profile,
        current_readiness=readiness,
        course_model=course_model,
    )
