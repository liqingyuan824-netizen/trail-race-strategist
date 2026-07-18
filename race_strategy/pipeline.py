"""Build internal, non-user-facing Phase 9 CP schedules and strategy variants."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .constants import (
    CACHE_POLICY_VERSION,
    GENERATOR_VERSION,
    SAFETY_NOTICE,
    SCHEMA_VERSION,
    SOURCE_POLICY_VERSION,
    STRATEGY_PARAMETERS,
)
from .report import build_markdown_report
from .validation import StrategyValidationError, validate_inputs
from reporting_contract import apply_output_contract


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, Mapping) and "value" in value else value


def _minutes_hhmm(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    seconds = max(0, int(round(minutes * 60)))
    hours, remainder = divmod(seconds, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{hours}:{mins:02d}:{secs:02d}"


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _clock_time(start: datetime | None, elapsed_minutes: float | None) -> str | None:
    if start is None or elapsed_minutes is None:
        return None
    return (start + timedelta(minutes=elapsed_minutes)).isoformat()


def _cutoff_elapsed_minutes(cp: Mapping[str, Any], *, start: datetime | None, finish_cutoff: datetime | None, is_finish: bool) -> float | None:
    raw = None if cp.get("evidence_tier") == "official_historical_reference" else cp.get("timing_window", {}).get("cutoff")
    cutoff = _parse_datetime(_field_value(raw))
    if cutoff is None and is_finish:
        cutoff = finish_cutoff
    if cutoff is None or start is None:
        return None
    return round((cutoff - start).total_seconds() / 60.0, 2)


def _strategy_unavailable(name: str, reason: str) -> dict[str, Any]:
    return {
        "strategy_id": name,
        "available": False,
        "recommended": False,
        "unavailable_reason": reason,
        "finish_range": None,
        "checkpoints": [],
        "switch_conditions": [],
    }


def _injury_column_policy(current_readiness: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only a minimal display label when injury was explicitly self-reported."""

    record = current_readiness.get("health_state", {}).get("injury_status", {})
    if not isinstance(record, Mapping) or not record.get("is_user_self_report"):
        return {"enabled": False, "label": None, "basis": "no_explicit_self_report"}
    text = " ".join(str(record.get("value") or "").strip().split())
    normalized = text.casefold()
    absent = {"", "none", "no", "no injury", "no pain", "无", "没有", "无伤痛", "无伤病", "无疼痛"}
    absent_phrases = ("no injury", "no pain", "pain free", "pain-free", "not injured", "无伤", "没有伤", "无疼痛", "没有疼痛")
    if normalized in absent or any(phrase in normalized for phrase in absent_phrases):
        return {"enabled": False, "label": None, "basis": "self_reported_absent"}
    labels = []
    for label, tokens in (
        ("膝", ("膝", "knee")), ("踝", ("踝", "ankle")), ("小腿", ("小腿", "calf")),
        ("足部", ("足", "脚", "foot", "plantar")), ("髋", ("髋", "hip")), ("背部", ("背", "腰", "back")),
    ):
        if any(token in normalized for token in tokens):
            labels.append(label)
    return {
        "enabled": True,
        "label": labels[0] if len(labels) == 1 else "伤痛关注",
        "basis": "explicit_runner_self_report",
        "raw_detail_included": False,
    }


def _build_strategy(
    *,
    strategy_id: str,
    params: Mapping[str, Any],
    cp_points: list[Mapping[str, Any]],
    baseline_range: Mapping[str, Any],
    start: datetime | None,
    finish_cutoff: datetime | None,
    total_distance: float,
    total_gain: float,
    recommended: bool,
    unavailable_fields: set[str],
) -> dict[str, Any]:
    factor = float(params["finish_multiplier"])
    stop_minutes = float(params["checkpoint_stop_minutes"])
    exponent = float(params["progress_exponent"])
    lower_total = float(baseline_range["lower_minutes"]) * factor
    midpoint_total = float(baseline_range["midpoint_minutes"]) * factor
    upper_total = float(baseline_range["upper_minutes"]) * factor
    total_planned_stops = stop_minutes * max(len(cp_points) - 2, 0)
    lower_movement = max(lower_total - total_planned_stops, 0.0)
    midpoint_movement = max(midpoint_total - total_planned_stops, 0.0)
    upper_movement = max(upper_total - total_planned_stops, 0.0)
    total_effort = max(total_distance + total_gain / 100.0, 0.001)
    schedule: list[dict[str, Any]] = []
    prior_stops = 0.0

    for index, cp in enumerate(cp_points):
        is_start = index == 0
        is_finish = index == len(cp_points) - 1
        distance = float(cp.get("distance_km") or 0.0)
        gain = float(cp.get("cumulative_gain_m") or 0.0)
        progress = min(max((distance + gain / 100.0) / total_effort, 0.0), 1.0)
        shaped_progress = progress**exponent if progress > 0 else 0.0
        stop = 0.0 if is_start or is_finish else stop_minutes
        arrival_lower = round(lower_movement * shaped_progress + prior_stops, 2)
        arrival_midpoint = round(midpoint_movement * shaped_progress + prior_stops, 2)
        arrival_upper = round(upper_movement * shaped_progress + prior_stops, 2)
        cutoff_elapsed = _cutoff_elapsed_minutes(cp, start=start, finish_cutoff=finish_cutoff, is_finish=is_finish)
        if cutoff_elapsed is None:
            margin = None
            margin_status = "not_yet_verified"
        else:
            margin = {
                "minimum_minutes": round(cutoff_elapsed - arrival_upper, 2),
                "midpoint_minutes": round(cutoff_elapsed - arrival_midpoint, 2),
                "maximum_minutes": round(cutoff_elapsed - arrival_lower, 2),
            }
            margin_status = "derived_from_official_cutoff"
        third_index = min(int(progress * 3), 2)
        rpe = params["rpe_by_third"][third_index]
        schedule.append(
            {
                "sequence": cp.get("sequence", index + 1),
                "name": cp.get("name"),
                "role": cp.get("role"),
                "distance_km": distance,
                "cumulative_gain_m": gain,
                "cumulative_loss_m": cp.get("cumulative_loss_m"),
                "segment_distance_km": cp.get("segment_distance_km"),
                "segment_elevation_gain_m": cp.get("segment_elevation_gain_m"),
                "segment_elevation_loss_m": cp.get("segment_elevation_loss_m"),
                "previous_cp": cp_points[index - 1].get("name") if index else None,
                "source_layer": cp.get("evidence_tier", "course_model_fact"),
                "source_year": cp.get("source_year"),
                "applicable_year": cp.get("applicable_year"),
                "applicable_group": cp.get("applicable_group"),
                "route_version": cp.get("route_version"),
                "current_year_applicability": cp.get("current_year_applicability"),
                "services": cp.get("services", cp.get("supplies")),
                "equipment_notes": cp.get("equipment_notes"),
                "support_restrictions": cp.get("support_restrictions"),
                "terrain_notes": cp.get("terrain_notes", []),
                "risk_notes": cp.get("risk_notes", []),
                "arrival_elapsed_range_minutes": {
                    "lower": arrival_lower,
                    "midpoint": arrival_midpoint,
                    "upper": arrival_upper,
                },
                "arrival_elapsed_range_hhmmss": {
                    "lower": _minutes_hhmm(arrival_lower),
                    "midpoint": _minutes_hhmm(arrival_midpoint),
                    "upper": _minutes_hhmm(arrival_upper),
                },
                "planned_arrival_clock_range": {
                    "lower": _clock_time(start, arrival_lower),
                    "midpoint": _clock_time(start, arrival_midpoint),
                    "upper": _clock_time(start, arrival_upper),
                },
                "planned_stop_minutes": stop,
                "planned_departure_elapsed_midpoint_minutes": round(arrival_midpoint + stop, 2),
                "planned_departure_clock": _clock_time(start, arrival_midpoint + stop),
                "departure_is_planned_not_observed": True,
                "official_cutoff_elapsed_minutes": cutoff_elapsed,
                "official_cutoff": _field_value(cp.get("timing_window", {}).get("cutoff")),
                "cutoff_margin_range": margin,
                "cutoff_margin_status": margin_status,
                "rpe_range": rpe,
                "movement_actions": {
                    "run_walk": params["run_walk_rule"],
                    "technical_descent": params["technical_descent_rule"],
                    "night": params["night_rule"],
                },
                "optional_performance_targets": {
                    "heart_rate_bpm": None,
                    "power_watts": None,
                    "vertical_speed_m_per_hour": None,
                    "runnable_pace_min_per_km": None,
                    "status": "not_available_not_guessed",
                },
                "fueling_action": {
                    "action": "仅使用已耐受的食物和饮水；离站前重新评估。",
                    "carbohydrate_g_per_hour": None if "carb_intake_per_hour_g" in unavailable_fields else None,
                    "fluid_ml_per_hour": None if "hydration_rate_ml_per_hour" in unavailable_fields else None,
                    "quantity_status": "unknown_not_guessed",
                },
                "derivation": {
                    "method": "cumulative_distance_plus_gain_effort_fraction",
                    "effort_fraction": round(progress, 6),
                    "progress_exponent": exponent,
                    "finish_multiplier": factor,
                    "prior_planned_stops_minutes": prior_stops,
                    "total_planned_stops_minutes": total_planned_stops,
                    "baseline_finish_range_includes_planned_stops": True,
                },
            }
        )
        prior_stops += stop

    finish = schedule[-1]["arrival_elapsed_range_minutes"]
    return {
        "strategy_id": strategy_id,
        "available": True,
        "recommended": recommended,
        "unavailable_reason": None,
        "parameter_set": dict(params),
        "finish_range": {
            "lower_minutes": finish["lower"],
            "midpoint_minutes": finish["midpoint"],
            "upper_minutes": finish["upper"],
            "lower_hhmmss": _minutes_hhmm(finish["lower"]),
            "midpoint_hhmmss": _minutes_hhmm(finish["midpoint"]),
            "upper_hhmmss": _minutes_hhmm(finish["upper"]),
        },
        "checkpoints": schedule,
        "switch_conditions": [
            "疼痛、疾病、热应激、补给失败、装备故障或关门风险上升时，切换至安全完成。",
            "出现任何红旗时停止成绩规划，遵从赛事或医疗人员指令。",
            "不得试图在单一赛段一次性追回全部落后时间。",
        ],
    }


def _official_sand_desert(course: Mapping[str, Any], cp_points: list[Mapping[str, Any]]) -> bool:
    """Recognize only explicitly captured official terrain wording."""
    values: list[str] = []
    for value in (course.get("route_text"), course.get("terrain_notes")):
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
    for point in cp_points:
        values.extend(str(item) for item in point.get("terrain_notes", []) or [])
    return any(token in " ".join(values).lower() for token in ("沙地", "沙漠", "sand", "desert"))


def _sand_adjustment(*, course: Mapping[str, Any], cp_points: list[Mapping[str, Any],], readiness: Mapping[str, Any]) -> dict[str, Any] | None:
    if not _official_sand_desert(course, cp_points):
        return None
    adaptation = readiness.get("terrain_adaptation")
    if isinstance(adaptation, Mapping) and adaptation.get("sand_or_desert_evidence"):
        return None
    comparison = course.get("sand_or_desert_comparator_history")
    if isinstance(comparison, Mapping) and comparison.get("evidence"):
        return None
    return {
        "status": "unvalidated_conservative_assumption",
        "reason": "official_sand_desert_confirmed_but_runner_adaptation_and_comparator_history_missing",
        "midpoint_multiplier": 1.20,
        "range_multiplier_lower": 1.12,
        "range_multiplier_upper": 1.30,
        "overridden_by_specific_evidence": False,
    }


def build_race_plan(
    *,
    course_model: Mapping[str, Any],
    current_readiness: Mapping[str, Any],
    distance_only_baseline: Mapping[str, Any],
    case_reference: str = "anonymous_internal_case",
    historical_reference_consent: bool = False,
) -> dict[str, Any]:
    readiness_binding = current_readiness.get("request_binding") if isinstance(current_readiness.get("request_binding"), Mapping) else None
    baseline_binding = distance_only_baseline.get("request_binding") if isinstance(distance_only_baseline.get("request_binding"), Mapping) else None
    course_binding = course_model.get("request_binding") if isinstance(course_model.get("request_binding"), Mapping) else None
    if readiness_binding is not None and readiness_binding != baseline_binding:
        raise StrategyValidationError("REQUEST_BINDING_MISMATCH_READINESS_BASELINE")
    request_ids = {
        str(binding.get("request_id")) for binding in (readiness_binding, baseline_binding, course_binding)
        if binding is not None and binding.get("request_id")
    }
    if len(request_ids) > 1:
        raise StrategyValidationError("REQUEST_ID_MISMATCH_COURSE_READINESS_BASELINE")
    errors = validate_inputs(
        course_model=course_model,
        current_readiness=current_readiness,
        distance_only_baseline=distance_only_baseline,
        allow_historical_reference=historical_reference_consent,
    )
    if errors:
        raise StrategyValidationError("; ".join(errors))

    assessment = current_readiness["assessment"]
    risk_level = assessment["risk_level"]
    permission = assessment["planning_permission"]
    course = course_model["event"]["course"]
    cp_points = list(course["cp_model"]["cp_points"])
    sand_adjustment = _sand_adjustment(course=course, cp_points=cp_points, readiness=current_readiness)
    total_distance = float(_field_value(course.get("total_distance_km")) or cp_points[-1].get("distance_km") or 0.0)
    total_gain = float(_field_value(course.get("total_elevation_gain_m")) or cp_points[-1].get("cumulative_gain_m") or 0.0)
    start = _parse_datetime(_field_value(course.get("start_time")))
    finish_cutoff = _parse_datetime(_field_value(course.get("cutoff_time")))
    unavailable_fields = set(current_readiness.get("unavailable_fields", []))
    target_group_capture = course_model["event"].get("target_group_capture", {})
    capture_completed = target_group_capture.get("capture_attempt_status") == "completed"
    capture_identity_verified = target_group_capture.get("identity_binding", {}).get("status") == "verified"
    cp_official = all(bool(point.get("officially_confirmed")) for point in cp_points)
    cp_historical_reference = bool(cp_points) and all(
        point.get("evidence_tier") == "official_historical_reference" for point in cp_points
    )
    cp_cutoffs_verified = all(_parse_datetime(_field_value(point.get("timing_window", {}).get("cutoff"))) is not None for point in cp_points)
    historical_anchor_available = bool(distance_only_baseline.get("source_reference"))
    conditional_time_plan_allowed = bool(
        risk_level != "red"
        and permission != "stop_and_seek_professional_assessment"
        and cp_official
        and cp_cutoffs_verified
        and historical_anchor_available
        and capture_completed
        and capture_identity_verified
    )
    conditional_reference_windows_allowed = bool(
        risk_level != "red"
        and permission != "stop_and_seek_professional_assessment"
        and cp_historical_reference
        and historical_anchor_available
        and capture_completed
        and capture_identity_verified
    )
    conditional_time_plan_missing = [
        name for name, ready in {
            "official_cp_points": cp_official,
            "official_cp_cutoffs": cp_cutoffs_verified,
            "historical_anchor": historical_anchor_available,
            "current_safety_permission": risk_level != "red" and permission != "stop_and_seek_professional_assessment",
            "target_group_capture_completed": capture_completed,
            "target_group_identity_verified": capture_identity_verified,
        }.items() if not ready
    ]

    if risk_level == "red" or permission == "stop_and_seek_professional_assessment":
        strategies = {
            name: _strategy_unavailable(name, "red_flag_stop_condition") for name in STRATEGY_PARAMETERS
        }
        plan_status = "stopped_red_flag"
        recommended_strategy = None
    else:
        recommended_strategy = "safe_finish" if permission in {"conservative_planning_only", "aggressive_plan_blocked"} or risk_level == "yellow" else "stable"
        strategies = {}
        for name, params in STRATEGY_PARAMETERS.items():
            if name == "aggressive" and (risk_level == "yellow" or permission != "normal_planning_allowed"):
                strategies[name] = _strategy_unavailable(name, "aggressive_blocked_by_readiness_safety_cap")
                continue
            baseline_range = dict(distance_only_baseline["finish_range_minutes"])
            if sand_adjustment:
                baseline_range = {
                    "lower_minutes": round(float(baseline_range["lower_minutes"]) * sand_adjustment["range_multiplier_lower"], 2),
                    "midpoint_minutes": round(float(baseline_range["midpoint_minutes"]) * sand_adjustment["midpoint_multiplier"], 2),
                    "upper_minutes": round(float(baseline_range["upper_minutes"]) * sand_adjustment["range_multiplier_upper"], 2),
                }
            strategies[name] = _build_strategy(
                strategy_id=name,
                params=params,
                cp_points=cp_points,
                baseline_range=baseline_range,
                start=start,
                finish_cutoff=finish_cutoff,
                total_distance=total_distance,
                total_gain=total_gain,
                recommended=name == recommended_strategy,
                unavailable_fields=unavailable_fields,
            )
        plan_status = "internal_research_plan_only"

    execution_budget_available = any(
        checkpoint.get("arrival_elapsed_range_minutes", {}).get("midpoint") is not None
        for strategy in strategies.values()
        for checkpoint in strategy.get("checkpoints", [])
    )

    result = {
        "schema_name": "race_plan",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "case_reference": case_reference,
        "privacy": {
            "identity_included": False,
            "health_details_included": False,
            "local_internal_validation_only": True,
            "mode": str(current_readiness.get("privacy_mode") or "private_alias"),
        },
        "governance": {
            "phase8a_validation_decision": "retain_distance_only",
            "holdout_evaluation_run": False,
            "model_validated": False,
            "user_facing_prediction_allowed": False,
            "output_scope": "internal_research_strategy_validation_only",
            "not_a_validated_personal_prediction": True,
        },
        "plan_status": plan_status,
        "recommended_strategy": recommended_strategy,
        "facts": {
            "event": {
                "official_name": course_model["event"].get("official_name"),
                "year": course_model["event"].get("year"),
                "group_code": course_model["event"].get("group_code"),
                "group_name": course_model["event"].get("group_name"),
                "course_grade": course_model["event"].get("grade", {}).get("grade"),
                "distance_km": total_distance,
                "elevation_gain_m": total_gain,
                "start_time": _field_value(course.get("start_time")),
                "cutoff_time": _field_value(course.get("cutoff_time")),
            },
            "readiness_safety_cap": {
                "risk_level": risk_level,
                "planning_permission": permission,
                "red_flags_present": bool(assessment.get("red_flags")),
                "yellow_flags_present": bool(assessment.get("yellow_flags")),
            },
            "report_column_policy": {
                "injury": _injury_column_policy(current_readiness),
                "day_night": {"enabled": "derive_from_official_start_and_course_window"},
            },
            "unknown_inputs": {
                "carb_intake_per_hour_g": None,
                "hydration_rate_ml_per_hour": None,
                "lowest_temperature_c": None,
                "status": "unknown_not_guessed",
            },
            "terrain_adjustment": sand_adjustment,
        },
        "baseline_binding": {
            "model_id": "distance_only",
            "selection_decision": "retain_distance_only",
            "source_reference": distance_only_baseline.get("source_reference"),
            "formula_reference": distance_only_baseline.get("formula_reference"),
            "calibrated": False,
        },
        "conditional_time_plan": {
            "status": (
                "available_conditional_execution_window" if conditional_time_plan_allowed
                else "available_historical_reference_window" if conditional_reference_windows_allowed
                else "available_nonofficial_execution_budget" if execution_budget_available
                else "insufficient_evidence"
            ),
            "allowed": conditional_time_plan_allowed,
            "display_allowed": execution_budget_available,
            "mode": (
                "current_year_official" if conditional_time_plan_allowed
                else "historical_route_reference" if conditional_reference_windows_allowed
                else "nonofficial_execution_budget" if execution_budget_available
                else "insufficient_evidence"
            ),
            "execution_budget_label": (
                "conditional_execution_window" if conditional_time_plan_allowed or conditional_reference_windows_allowed
                else "nonofficial_execution_budget" if execution_budget_available
                else "pending_inputs"
            ),
            "not_a_validated_personal_prediction": True,
            "requirements": {
                "official_cp_points": cp_official,
                "official_cp_cutoffs": cp_cutoffs_verified,
                "historical_reference_cp_points": cp_historical_reference,
                "historical_anchor": historical_anchor_available,
                "current_safety_permission": risk_level != "red" and permission != "stop_and_seek_professional_assessment",
                "target_group_capture_completed": capture_completed,
                "target_group_identity_verified": capture_identity_verified,
            },
            "missing_requirements": conditional_time_plan_missing,
            "target_group_capture": target_group_capture,
        },
        "historical_reference": {
            "user_confirmed": bool(historical_reference_consent and cp_historical_reference),
            "reference_only": cp_historical_reference,
            "current_year_cp_confirmed": cp_official,
            "required_pre_race_action": (
                "赛前按当年官方公告复核 CP、补给、关门与路线版本"
                if cp_historical_reference else None
            ),
        },
        "derivation_policy": {
            "cp_time_method": "cumulative distance plus gain effort fraction, shaped by frozen strategy parameters",
            "planned_stop_values_are_observations": False,
            "unknown_values_are_imputed": False,
            "strategy_differences_are_parameterized": True,
        },
        "strategies": strategies,
        "warnings": [
            "This output is internal research evidence and is not an approved user-facing prediction.",
            "Checkpoint arrival times are derived planning ranges, not observed timing results.",
            "Missing carbohydrate, fluid, and temperature tolerance quantities remain unknown.",
        ],
        "diagnostics": {
            "input_validation": "passed",
            "cp_count": len(cp_points),
            "available_strategy_count": sum(1 for item in strategies.values() if item["available"]),
            "red_flag_stop": plan_status == "stopped_red_flag",
        },
    }
    if readiness_binding is not None:
        result["request_binding"] = dict(readiness_binding)
    return result


def replay_race_plan(*, course_model_path: Path, readiness_path: Path, baseline_path: Path, case_reference: str) -> dict[str, Any]:
    return build_race_plan(
        course_model=json.loads(course_model_path.read_text(encoding="utf-8")),
        current_readiness=json.loads(readiness_path.read_text(encoding="utf-8")),
        distance_only_baseline=json.loads(baseline_path.read_text(encoding="utf-8")),
        case_reference=case_reference,
    )


def write_race_plan(plan: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    artifact = apply_output_contract(plan, report_type="race_strategy", workflow_stage="phase9", report_status=str(plan.get("plan_status")))
    (output_dir / "race_plan.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "race_plan.md").write_text(build_markdown_report(artifact), encoding="utf-8")
