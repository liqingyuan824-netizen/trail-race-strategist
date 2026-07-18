"""Human-readable audit report for the Phase 7A baseline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    return str(value)


def build_audit_report(
    *,
    baseline_inputs: Mapping[str, Any],
    historical_selection: Mapping[str, Any],
    candidate_ranges: Mapping[str, Any],
    c_grade_source_path: str,
    a_grade_source_path: str,
) -> str:
    target = baseline_inputs["target_event"]
    readiness = baseline_inputs["current_readiness"]
    selection_rows = historical_selection["candidates"]
    selected_rows = historical_selection.get("selected_candidates", [])
    ranges = candidate_ranges["candidate_ranges"]
    per_race = candidate_ranges["per_race_estimates"]
    target_condition_policy = candidate_ranges.get("target_condition_policy", {})

    lines: list[str] = []
    lines.append("# Phase 7A Baseline Prediction Audit")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- Target event: `{target.get('event_name')}`")
    lines.append(f"- Group: `{target.get('group_name')}` / `{target.get('group_code')}`")
    lines.append(f"- Course grade: `{target.get('grade')}`")
    lines.append(f"- Route state: `{target.get('route_version_state')}`")
    lines.append(f"- Distance: `{_fmt(target.get('distance_km'))} km`")
    lines.append(f"- Elevation gain: `{_fmt(target.get('elevation_gain_m'))} m`")
    lines.append("- Scope lock: Phase 6A is frozen; this run only implements Phase 7A simplified baseline.")
    lines.append("- Explicitly excluded: Phase 6B, full reference graph, formal prediction, CP arrival times, aid-station plan, and race strategy.")
    lines.append("")
    lines.append("## Governance")
    lines.append(f"- Schema: `{baseline_inputs['schema_name']}` -> `{candidate_ranges['schema_name']}`")
    lines.append(f"- Governance envelope: `{historical_selection.get('governance_envelope', {}).get('schema_version')}`")
    lines.append(f"- Prediction status: `{candidate_ranges['prediction_policy']['prediction_status']}`")
    lines.append(f"- User-facing prediction: `{candidate_ranges['prediction_policy']['user_facing_prediction']}`")
    lines.append(f"- Calibrated: `{candidate_ranges['prediction_policy']['calibrated']}`")
    lines.append(f"- Requires Phase 8A backtest: `{candidate_ranges['prediction_policy']['requires_phase8a_backtest']}`")
    safety_notice = candidate_ranges.get("safety_notice") or baseline_inputs.get("safety_notice") or {}
    lines.append(f"- Safety note: `{safety_notice.get('message')}`")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- Planning permission: `{readiness['planning_permission']}`")
    readiness_band = readiness.get("readiness_band") or {}
    lines.append(f"- Readiness band: `{readiness_band.get('label')}`")
    lines.append(f"- Readiness score: `{readiness['readiness_score']}`")
    lines.append(f"- Yellow flags: `{', '.join(readiness.get('yellow_flags', [])) or 'none'}`")
    lines.append(f"- Red flags: `{', '.join(readiness.get('red_flags', [])) or 'none'}`")
    lines.append(f"- Missing fueling / temperature inputs preserved: `carb_intake_per_hour_g`, `hydration_rate_ml_per_hour`, `lowest_temperature_c`")
    lines.append(f"- Readiness note: {candidate_ranges['readiness_constraints']['constraint_note']}")
    lines.append("")
    lines.append("## Target Conditions")
    lines.append(f"- Target condition status: `{target_condition_policy.get('status', 'unknown')}`")
    lines.append(f"- Target condition tags: `{', '.join(target_condition_policy.get('tags', [])) or 'unknown'}`")
    for note in target_condition_policy.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Historical Selection")
    lines.append("| Race | Source | Date | Distance km | Gain m | Time | Include | Rank | Weight | Reason |")
    lines.append("| --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- |")
    for row in selection_rows:
        source_label = row["source_type"]
        time_source = row["time_source_type"]
        weight = row.get("final_weight", row.get("weight", 0.0))
        lines.append(
            f"| {row['label']} | {source_label} / {time_source} | {_fmt(row['date'])} | {_fmt(row['distance_km'])} | {_fmt(row['elevation_gain_m'])} | {_fmt(row['race_time'])} | "
            f"{str(row['include_in_baseline']).lower()} | {_fmt(row.get('selection_rank'))} | {_fmt(weight)} | {row['selection_reason']} |"
        )
    lines.append("")
    lines.append("## Formula")
    lines.append("- Heuristic name: `distance_plus_climb_load_transfer_v2`")
    lines.append("- Formula: `base_estimate_minutes = historical_minutes * ((target_distance_km + target_elevation_gain_m/100) / (race_distance_km + race_elevation_gain_m/100))`")
    lines.append("- This is explicitly marked as heuristic and not calibrated.")
    lines.append("- Per-race estimates are kept independent; aggregation uses weighted quantiles, not a plain average.")
    lines.append("- Weight components are explicit and all participate in the final score: source_quality, recency_similarity, distance_similarity, gain_density_similarity, condition_similarity, data_confidence, and course_grade_penalty.")
    lines.append("")
    lines.append("## Per-Race Anchors")
    for row in per_race:
        bounds = row["uncertainty_bounds"]
        lines.append(
            f"- {row['label']}: base `{row['base_estimate_hhmmss']}` from `{row['matched_race_name']}` with final weight `{row['final_weight']}`; "
            f"source quality `{row['source_quality']}`; geometry `{row['distance_similarity']}` / `{row['gain_density_similarity']}`; "
            f"condition `{row['condition_similarity']}`; course penalty `{row['course_grade_penalty']}`; "
            f"interval `{bounds['lower_hhmmss']}` to `{bounds['upper_hhmmss']}`."
        )
        lines.append(f"  - Calculation source notes: {', '.join(row.get('calculation_source_notes', []))}")
        lines.append(f"  - Condition tags: `{', '.join(row.get('condition_tags', [])) or 'none'}`")
    lines.append("")
    lines.append("## Aggregated Ranges")
    for name, block in ranges.items():
        lines.append(
            f"- {name}: `{block['lower_hhmmss']}` to `{block['upper_hhmmss']}` "
            f"(midpoint `{block['midpoint_hhmmss']}`)"
        )
    lines.append("")
    lines.append("## Degradation Notes")
    lines.append(f"- C-grade degraded source used: `{c_grade_source_path}`")
    lines.append(f"- A-grade structural sample used only for shape validation: `{a_grade_source_path}`")
    lines.append("- The C-grade sample cannot generate CPs; if CP generation appears in this lane, the build must fail.")
    lines.append("- readiness_band: high does not override conservative_planning_only.")
    lines.append("- Current low-confidence items remain unknown: carb intake per hour, hydration rate per hour, and lowest temperature.")
    lines.append("- Source conflicts are preserved instead of being silently overwritten; the calculation field is listed explicitly in each candidate.")
    lines.append(f"- Selected history anchors: {len(selected_rows)} of {len(selection_rows)} total merged candidates.")
    lines.append("")
    lines.append("## Backtest Boundary")
    lines.append("- These candidate ranges are not user-facing and must stay internal until Phase 8A backtest completes.")
    lines.append("- Until then, they are research candidates only.")
    lines.append("")
    return "\n".join(lines)
