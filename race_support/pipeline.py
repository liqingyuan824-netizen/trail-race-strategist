"""Build versioned CP-aligned fueling, equipment, and private-support plans."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import CACHE_POLICY_VERSION, FAILURE_PLAYBOOK, GENERATOR_VERSION, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION
from .report import build_markdown_report
from .validation import SupportPlanValidationError, validate_inputs
from reporting_contract import apply_output_contract

_OFFICIAL_CP_SOURCE_KINDS = {
    "official",
    "official_cp_table",
    "official_structured_cp_table",
    "official_gpx",
    "official_visual_transcription",
    "official_roadbook_visual_transcription",
}


def _is_current_official_cp_fact(cp: Mapping[str, Any]) -> bool:
    return cp.get("officially_confirmed") is True and cp.get("source_kind") in _OFFICIAL_CP_SOURCE_KINDS


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _intake_item(value: Any) -> dict[str, Any]:
    if value is None:
        return {"range": None, "status": "unknown_not_guessed", "verified_in_training": False}
    return {
        "range": {"minimum": value.get("minimum"), "maximum": value.get("maximum"), "unit": value.get("unit")},
        "status": "verified_training_range",
        "verified_in_training": True,
        "evidence_reference": value.get("evidence_reference"),
    }


def _official_supply(cp: Mapping[str, Any]) -> dict[str, Any]:
    confirmed = _is_current_official_cp_fact(cp)
    value = cp.get("supplies")
    if not confirmed or value in (None, "", "unknown"):
        return {"value": None, "status": "not_yet_verified", "source_layer": "official_fact_required"}
    return {"value": value, "status": "verified_official_fact", "source_layer": "course_model_fact"}


def _rule_at_cp(cp: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = cp.get(key)
    if not _is_current_official_cp_fact(cp) or value is None:
        return {"allowed": None, "status": "not_yet_verified", "source_layer": "official_fact_required"}
    return {"allowed": bool(value), "status": "verified_official_fact", "source_layer": "course_model_fact"}


def _mandatory_equipment(course_model: Mapping[str, Any], support_inputs: Mapping[str, Any]) -> dict[str, Any]:
    supplied = support_inputs.get("mandatory_equipment")
    if isinstance(supplied, Mapping) and supplied.get("officially_confirmed") is True and supplied.get("source_kind") == "official":
        return deepcopy(dict(supplied))
    course_fact = course_model.get("event", {}).get("rules", {}).get("mandatory_equipment")
    if isinstance(course_fact, Mapping) and course_fact.get("officially_confirmed") is True and course_fact.get("source_kind") == "official":
        return deepcopy(dict(course_fact))
    return {"items": None, "status": "not_yet_verified", "source_layer": "official_fact_required"}


def build_race_support_plan(
    *,
    race_plan: Mapping[str, Any],
    course_model: Mapping[str, Any],
    support_inputs: Mapping[str, Any],
    weather_scenarios: Mapping[str, Any] | None = None,
    case_reference: str = "anonymous_internal_case",
) -> dict[str, Any]:
    errors = validate_inputs(race_plan=race_plan, course_model=course_model, support_inputs=support_inputs)
    if errors:
        raise SupportPlanValidationError("; ".join(errors))

    intake = support_inputs.get("intake_targets", {})
    intake_plan = {
        "carbohydrate_g_per_hour": _intake_item(intake.get("carbohydrate_g_per_hour")),
        "fluid_ml_per_hour": _intake_item(intake.get("fluid_ml_per_hour")),
        "electrolyte_mg_per_hour": _intake_item(intake.get("electrolyte_mg_per_hour")),
    }
    verified_foods = [item for item in support_inputs.get("verified_foods", []) if item.get("verified_in_training") is True]
    cp_points = course_model["event"]["course"]["cp_model"]["cp_points"]
    strategy_id = race_plan.get("recommended_strategy")
    strategy = race_plan.get("strategies", {}).get(strategy_id or "", {})
    strategy_cps = {item.get("sequence"): item for item in strategy.get("checkpoints", [])}
    checkpoints: list[dict[str, Any]] = []
    for cp in cp_points:
        schedule = strategy_cps.get(cp.get("sequence"), {})
        official = _official_supply(cp)
        private = _rule_at_cp(cp, "is_assistance")
        drop_bag = _rule_at_cp(cp, "is_drop_bag")
        checklist = [
            "Check carried reserve before leaving.",
            "Use only previously tolerated items.",
            "Confirm required equipment is present and functional.",
        ]
        if official["status"] != "verified_official_fact":
            checklist.append("Do not rely on unverified official supplies.")
        if private["allowed"] is not True:
            checklist.append("Use the self-contained fallback; do not rely on private support here.")
        checkpoints.append(
            {
                "sequence": cp.get("sequence"),
                "name": cp.get("name"),
                "role": cp.get("role"),
                "distance_km": cp.get("distance_km"),
                "planned_arrival": schedule.get("planned_arrival_clock_range"),
                "planned_stop_minutes": schedule.get("planned_stop_minutes"),
                "official_supply": official,
                "private_support": private,
                "drop_bag": drop_bag,
                "intake_quantity": None if not any(x["verified_in_training"] for x in intake_plan.values()) else intake_plan,
                "verified_food_options": deepcopy(verified_foods),
                "equipment_actions": [
                    "Carry and check only equipment already used successfully.",
                    "Official mandatory-equipment rules override this plan.",
                ],
                "behavior_checklist": checklist,
            }
        )

    segments: list[dict[str, Any]] = []
    for start_cp, end_cp in zip(checkpoints, checkpoints[1:]):
        start_schedule = strategy_cps.get(start_cp.get("sequence"), {})
        end_schedule = strategy_cps.get(end_cp.get("sequence"), {})
        start_mid = (start_schedule.get("arrival_elapsed_range_minutes") or {}).get("midpoint")
        end_mid = (end_schedule.get("arrival_elapsed_range_minutes") or {}).get("midpoint")
        segments.append(
            {
                "segment_id": f"{start_cp.get('sequence')}-{end_cp.get('sequence')}",
                "from_cp": start_cp.get("name"),
                "to_cp": end_cp.get("name"),
                "distance_km": round(float(end_cp.get("distance_km") or 0) - float(start_cp.get("distance_km") or 0), 3),
                "planned_elapsed_minutes": round(float(end_mid) - float(start_mid), 2) if start_mid is not None and end_mid is not None else None,
                "quantified_intake": intake_plan if any(item["verified_in_training"] for item in intake_plan.values()) else None,
                "carried_reserve_action": "Leave the prior CP with enough verified carried reserve for this segment; quantity remains unquantified when capacity or intake is unknown.",
                "failure_action": "Reduce effort and use the self-contained fallback when the next verified supply or private support is unavailable.",
            }
        )

    red_weather = bool(weather_scenarios and weather_scenarios.get("strategy_constraints", {}).get("stop_aggressive_targets"))
    plan_status = "stopped_red_flag" if race_plan.get("plan_status") == "stopped_red_flag" else "internal_research_support_plan_only"
    return {
        "schema_name": "race_support_plan",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "case_reference": case_reference,
        "privacy": {"identity_included": False, "local_internal_validation_only": True},
        "governance": {
            "phase8a_validation_decision": "retain_distance_only",
            "selected_model": "distance_only",
            "full_model_status": "rejected",
            "holdout_evaluation_run": False,
            "user_facing_prediction_allowed": False,
            "output_scope": "internal_research_support_validation_only",
        },
        "plan_status": plan_status,
        "strategy_binding": {
            "race_plan_schema_version": race_plan.get("schema_version"),
            "recommended_strategy": strategy_id,
            "weather_red_flag_active": red_weather,
            "aggressive_target_allowed": bool(race_plan.get("strategies", {}).get("aggressive", {}).get("available")) and not red_weather,
        },
        "intake_plan": intake_plan,
        "intake_policy": {
            "new_products_allowed": False,
            "specific_quantity_requires_training_verification": True,
            "unknown_values_imputed": False,
        },
        "carrying_capacity": support_inputs.get("carrying_capacity"),
        "mandatory_equipment": _mandatory_equipment(course_model, support_inputs),
        "temperature_tolerance": support_inputs.get("temperature_tolerance") or {"lowest_temperature_c": None, "status": "unknown_not_guessed"},
        "checkpoints": checkpoints,
        "segments": segments,
        "failure_playbook": deepcopy(FAILURE_PLAYBOOK),
        "unavailable_fields": [key for key, value in intake_plan.items() if value["status"] == "unknown_not_guessed"],
        "warnings": [
            "This is an internal research plan, not a validated personal prescription.",
            "Carbohydrate, fluid, electrolyte, and temperature tolerance are not guessed.",
            "Official aid, private support, drop bags, and mandatory equipment are facts only when explicitly verified.",
        ],
        "diagnostics": {
            "checkpoint_count": len(checkpoints),
            "segment_count": len(segments),
            "verified_food_count": len(verified_foods),
            "quantified_intake_available": any(item["verified_in_training"] for item in intake_plan.values()),
        },
    }


def replay_race_support_plan(*, race_plan_path: Path, course_model_path: Path, support_inputs_path: Path, weather_path: Path | None, case_reference: str) -> dict[str, Any]:
    return build_race_support_plan(
        race_plan=json.loads(race_plan_path.read_text(encoding="utf-8")),
        course_model=json.loads(course_model_path.read_text(encoding="utf-8")),
        support_inputs=json.loads(support_inputs_path.read_text(encoding="utf-8")),
        weather_scenarios=json.loads(weather_path.read_text(encoding="utf-8")) if weather_path else None,
        case_reference=case_reference,
    )


def write_race_support_plan(plan: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    artifact = apply_output_contract(plan, report_type="planning_preparation", workflow_stage="phase10", report_status=str(plan.get("plan_status")))
    (output_dir / "race_support_plan.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "race_support_plan.md").write_text(build_markdown_report(artifact), encoding="utf-8")
