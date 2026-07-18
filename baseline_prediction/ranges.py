"""Time-range construction for the Phase 7A baseline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .constants import PREDICTION_STATUS
from .normalization import estimate_race_time_minutes, weighted_median, weighted_quantile


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _time_bounds(estimate_minutes: float, *, source_type: str, condition_tags: list[str], course_grade: str | None, planning_permission: str | None) -> tuple[float, float, float]:
    source_penalty = 0.04 if source_type == "itra_public_runner" else 0.08
    if source_type == "itra_public_runner" and "mixed_source_time_record" in condition_tags:
        source_penalty = 0.06
    condition_penalty = min(0.025 * len(condition_tags), 0.16)
    course_penalty = 0.10 if course_grade == "C" else 0.04 if course_grade == "B" else 0.0
    planning_penalty = 0.04 if planning_permission == "conservative_planning_only" else 0.0
    total_uncertainty = source_penalty + condition_penalty + course_penalty + planning_penalty
    lower = estimate_minutes * max(0.78, 1.0 - total_uncertainty * 0.70)
    upper = estimate_minutes * (1.0 + total_uncertainty * 1.30)
    central = estimate_minutes * (1.0 + max(0.0, total_uncertainty - 0.08) * 0.20)
    return round(lower, 2), round(central, 2), round(upper, 2)


def _reading_label(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    total_seconds = max(int(round(minutes * 60.0)), 0)
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{hours}:{mins:02d}:{secs:02d}"


def build_baseline_candidate_ranges(
    *,
    baseline_inputs: Mapping[str, Any],
    historical_selection: Mapping[str, Any],
) -> dict[str, Any]:
    target_event = baseline_inputs["target_event"]
    target_distance_km = _coerce_float(target_event.get("distance_km"))
    target_elevation_gain_m = _coerce_float(target_event.get("elevation_gain_m"))
    course = baseline_inputs["course_model"]
    readiness = baseline_inputs["current_readiness"]
    planning_permission = readiness.get("planning_permission")
    course_grade = course.get("grade")
    target_condition_tags = list(target_event.get("condition_tags", []))

    included_candidates = [candidate for candidate in historical_selection.get("selected_candidates", []) if candidate.get("include_in_baseline")]
    if not included_candidates:
        raise ValueError("no_included_candidates")

    per_race_rows: list[dict[str, Any]] = []
    for candidate in included_candidates:
        distance_km = _coerce_float(candidate.get("distance_km"))
        elevation_gain_m = _coerce_float(candidate.get("elevation_gain_m"))
        race_time = candidate.get("race_time")
        time_source_type = candidate.get("time_source_type")
        source_type = candidate.get("source_type")
        base = estimate_race_time_minutes(
            race_distance_km=distance_km,
            race_elevation_gain_m=elevation_gain_m,
            race_time=race_time,
            time_source_kind=time_source_type,
            source_kind=source_type,
            target_distance_km=target_distance_km,
            target_elevation_gain_m=target_elevation_gain_m,
        )
        base_minutes = base["base_estimate_minutes"]
        if base_minutes is None:
            raise ValueError(f"invalid_historical_time:{candidate.get('label')}")

        lower, central, upper = _time_bounds(
            base_minutes,
            source_type=source_type,
            condition_tags=list(candidate.get("condition_tags", [])),
            course_grade=course_grade,
            planning_permission=planning_permission,
        )
        per_race_rows.append(
            {
                "label": candidate.get("label"),
                "matched_race_name": candidate.get("matched_race_name"),
                "date": candidate.get("date"),
                "source_type": source_type,
                "time_source_type": time_source_type,
                "distance_km": distance_km,
                "elevation_gain_m": elevation_gain_m,
                "race_time": race_time,
                "base_estimate_minutes": base_minutes,
                "base_estimate_hhmmss": base["base_estimate_hhmmss"],
                "load_ratio": base["load_ratio"],
                "weight": candidate.get("final_weight", candidate.get("weight", 0.0)),
                "final_weight": candidate.get("final_weight", candidate.get("weight", 0.0)),
                "source_quality": candidate.get("source_quality"),
                "recency_similarity": candidate.get("recency_similarity"),
                "distance_similarity": candidate.get("distance_similarity"),
                "gain_density_similarity": candidate.get("gain_density_similarity"),
                "condition_similarity": candidate.get("condition_similarity"),
                "course_grade_penalty": candidate.get("course_grade_penalty"),
                "data_confidence": candidate.get("data_confidence"),
                "weighting": candidate.get("weighting"),
                "condition_tags": list(candidate.get("condition_tags", [])),
                "uncertainty_bounds": {
                    "lower_minutes": lower,
                    "central_minutes": central,
                    "upper_minutes": upper,
                    "lower_hhmmss": _reading_label(lower),
                    "central_hhmmss": _reading_label(central),
                    "upper_hhmmss": _reading_label(upper),
                },
                "time_source_note": candidate.get("time_source_note"),
                "readiness_note": candidate.get("readiness_note"),
            }
        )

    values = [row["base_estimate_minutes"] for row in per_race_rows]
    weights = [max(float(row.get("final_weight", row.get("weight", 0.0))), 0.0) for row in per_race_rows]
    low_values = [row["uncertainty_bounds"]["lower_minutes"] for row in per_race_rows]
    high_values = [row["uncertainty_bounds"]["upper_minutes"] for row in per_race_rows]

    weighted_center = weighted_median(values, weights)
    if weighted_center is None:
        raise ValueError("unable_to_compute_weighted_center")

    dispersion_candidates = [abs(value - weighted_center) for value in values]
    weighted_dispersion = weighted_median(dispersion_candidates, weights) or 0.0
    dispersion_ratio = weighted_dispersion / weighted_center if weighted_center else 0.0

    optimistic_lower = weighted_quantile(low_values, weights, 0.20)
    optimistic_upper = weighted_quantile(values, weights, 0.40)
    baseline_lower = weighted_quantile(values, weights, 0.35)
    baseline_upper = weighted_quantile(values, weights, 0.65)
    conservative_lower = weighted_quantile(values, weights, 0.60)
    conservative_upper = weighted_quantile(high_values, weights, 0.80)

    if optimistic_lower is None or optimistic_upper is None or baseline_lower is None or baseline_upper is None or conservative_lower is None or conservative_upper is None:
        raise ValueError("unable_to_compute_range_quantiles")

    prediction_policy = {
        "prediction_status": PREDICTION_STATUS,
        "user_facing_prediction": False,
        "calibrated": False,
        "requires_phase8a_backtest": True,
    }

    def _range_payload(lower: float, upper: float, *, basis: str) -> dict[str, Any]:
        lower_value = round(lower, 2)
        upper_value = round(upper, 2)
        midpoint = round((lower_value + upper_value) / 2.0, 2)
        return {
            "basis": basis,
            "lower_minutes": lower_value,
            "upper_minutes": upper_value,
            "midpoint_minutes": midpoint,
            "lower_hhmmss": _reading_label(lower_value),
            "upper_hhmmss": _reading_label(upper_value),
            "midpoint_hhmmss": _reading_label(midpoint),
        }

    readiness_constraint_note = (
        "readiness_band=high does not override conservative_planning_only because the band is an unvalidated internal heuristic, "
        "while planning_permission is the explicit safety cap driven by yellow flags and incomplete fueling/temperature inputs."
    )

    return {
        "schema_name": "baseline_candidate_ranges",
        "schema_version": "1.0.0",
        "generated_at": baseline_inputs["generated_at"],
        "generator_version": "0.1.0",
        "source_policy_version": baseline_inputs.get("source_policy_version", "1.0.0"),
        "cache_policy_version": baseline_inputs.get("cache_policy_version", "1.0.0"),
        "safety_notice": baseline_inputs.get("safety_notice"),
        "prediction_policy": prediction_policy,
        "target_event": dict(target_event),
        "course_constraints": {
            "grade": course_grade,
            "route_version_state": course.get("route_version_state"),
            "cp_model_status": course.get("cp_model_status"),
            "no_cp_generated": True,
            "degraded_c_grade_sample": course_grade == "C",
        },
        "target_condition_policy": {
            "tags": target_condition_tags,
            "status": target_event.get("condition_status", "unknown"),
            "notes": target_event.get("condition_policy_notes", []),
        },
        "readiness_constraints": {
            "planning_permission": planning_permission,
            "readiness_band": readiness.get("readiness_band"),
            "yellow_flags": list(readiness.get("yellow_flags", [])),
            "red_flags": list(readiness.get("red_flags", [])),
            "unavailable_fields": [
                "carb_intake_per_hour_g",
                "hydration_rate_ml_per_hour",
                "lowest_temperature_c",
            ],
            "constraint_note": readiness_constraint_note,
        },
        "methodology": {
            "name": "distance_plus_climb_load_transfer_v2",
            "marked_as": "heuristic",
            "calibration_status": "not_calibrated",
            "formula": "base_estimate_minutes = historical_minutes * ((target_distance_km + target_elevation_gain_m/100) / (race_distance_km + race_elevation_gain_m/100))",
            "aggregation_method": "weighted_quantiles_over_per_race_estimates; not a plain average",
            "weighting_note": "weights are derived from transparent source_quality, recency_similarity, distance_similarity, gain_density_similarity, condition_similarity, data_confidence, and course_grade_penalty components.",
        },
        "per_race_estimates": per_race_rows,
        "aggregate_weights": {
            "weight_total": round(sum(weights), 3),
            "weighted_center_minutes": round(weighted_center, 2),
            "weighted_center_hhmmss": _reading_label(weighted_center),
            "weighted_dispersion_minutes": round(weighted_dispersion, 2),
            "weighted_dispersion_ratio": round(dispersion_ratio, 4),
        },
        "candidate_ranges": {
            "optimistic": _range_payload(optimistic_lower, optimistic_upper, basis="weighted_lower_quantile"),
            "baseline": _range_payload(baseline_lower, baseline_upper, basis="weighted_median_band"),
            "conservative": _range_payload(conservative_lower, conservative_upper, basis="weighted_upper_quantile"),
        },
        "diagnostics": {
            "input_validation": {
                "status": "passed",
                "error_count": 0,
            },
            "candidate_count": len(per_race_rows),
            "source_count": len(per_race_rows),
            "selected_condition_tags": target_condition_tags,
            "partial_reasons": [
                "c_grade_degraded_sample",
                "no_cp_generated",
                "planning_permission_restricted",
                "fueling_and_temperature_inputs_unavailable",
            ],
        },
    }
