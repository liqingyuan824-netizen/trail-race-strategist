"""Phase 8B multipath candidate with baseline-first degradation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
import math
import statistics
from typing import Any

from .constants import (
    CACHE_POLICY_VERSION,
    DISTANCE_BANDS,
    GENERATOR_VERSION,
    GOVERNANCE,
    MODEL_ID,
    PATH_BASE_WEIGHTS,
    SAFETY_NOTICE,
    SCHEMA_VERSION,
    SOURCE_POLICY_VERSION,
)
from .validation import ReferenceInputError, validate_baseline


class MultipathPredictionError(ReferenceInputError):
    """Raised when the graph cannot safely support a requested strict run."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _band(distance: float) -> tuple[str, float, float]:
    for upper, label, exponent, uncertainty in DISTANCE_BANDS:
        if distance <= upper:
            return label, exponent, uncertainty
    raise AssertionError("unreachable")


def _effort_distance(distance: float, gain: float) -> float:
    return distance + gain / 100.0


def _scaled_time(record: Mapping[str, Any], race: Mapping[str, Any], target: Mapping[str, Any]) -> float:
    target_distance = float(target["distance_km"])
    label, exponent, _ = _band(target_distance)
    source_effort = _effort_distance(float(race["distance_km"]), float(race["elevation_gain_m"]))
    target_effort = _effort_distance(target_distance, float(target["elevation_gain_m"]))
    ratio = target_effort / source_effort
    midpoint = float(record["finish_time_minutes"]) * math.pow(ratio, exponent)
    if label in {"100k", "100m"} and target_distance > float(race["distance_km"]):
        midpoint *= 1.0 + min(0.12, (target_distance / float(race["distance_km"]) - 1.0) * 0.04)
    return midpoint


def _path_range(midpoint: float, uncertainty: float) -> dict[str, float]:
    return {
        "lower_minutes": round(midpoint * (1.0 - uncertainty), 2),
        "midpoint_minutes": round(midpoint, 2),
        "upper_minutes": round(midpoint * (1.0 + uncertainty), 2),
    }


def _weighted_mean(items: list[tuple[float, float]]) -> float:
    total = sum(weight for _, weight in items)
    if total <= 0:
        raise MultipathPredictionError("non_positive_path_weight")
    return sum(value * weight for value, weight in items) / total


def _graph_indexes(graph: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    races = {str(node["node_id"]): node for node in graph.get("nodes", []) if node.get("node_type") == "race"}
    performances = {str(node["node_id"]): node for node in graph.get("nodes", []) if node.get("node_type") == "performance"}
    return races, performances


def _validate_graph(graph: Mapping[str, Any]) -> None:
    if graph.get("schema_name") != "reference_graph":
        raise MultipathPredictionError("reference_graph_required")
    governance = graph.get("governance", {})
    for key in ("validation_data_used", "holdout_data_used", "holdout_evaluation_run"):
        if governance.get(key) is not False:
            raise MultipathPredictionError(f"unsafe_graph_governance:{key}")
    diagnostics = graph.get("diagnostics", {})
    for key in ("future_records_used", "validation_records_used", "holdout_records_used", "target_race_results_used"):
        if diagnostics.get(key) != 0:
            raise MultipathPredictionError(f"unsafe_graph_diagnostic:{key}")


def _candidate_from_edges(
    *,
    path_id: str,
    edge_type: str,
    graph: Mapping[str, Any],
    races: Mapping[str, Mapping[str, Any]],
    performances: Mapping[str, Mapping[str, Any]],
    uncertainty: float,
    dependency_group: str,
) -> dict[str, Any] | None:
    target = graph["target"]
    candidates: list[tuple[float, float, Mapping[str, Any]]] = []
    for edge in graph.get("edges", []):
        if edge.get("edge_type") != edge_type:
            continue
        performance = performances.get(str(edge["from"]))
        if performance is None:
            continue
        race = races.get(str(performance["race_id"]))
        if race is None:
            continue
        quality = float(edge.get("course_similarity", 0.0)) * float(edge.get("recency", 0.0)) * float(edge.get("confidence", 0.0))
        if quality <= 0:
            continue
        candidates.append((_scaled_time(performance, race, target), quality, edge))
    if not candidates:
        return None
    midpoint = _weighted_mean([(value, weight) for value, weight, _ in candidates])
    quality = min(1.0, sum(weight for _, weight, _ in candidates) / len(candidates))
    return {
        "path_id": path_id,
        "available": True,
        "directional_only": False,
        "dependency_group": dependency_group,
        "prediction": _path_range(midpoint, uncertainty + (1.0 - quality) * 0.08),
        "raw_dynamic_weight": round(PATH_BASE_WEIGHTS[path_id] * quality, 6),
        "weight_components": {
            "base_priority": PATH_BASE_WEIGHTS[path_id],
            "mean_quality": round(quality, 6),
            "source_count": len(candidates),
        },
        "source_record_ids": sorted({str(edge["from"]) for _, _, edge in candidates}),
        "calculation": "effort_distance_power_scaling_then_quality_weighted_mean",
        "limitations": ["Research formula is not calibrated on validation or holdout data."],
    }


def _peer_path(
    graph: Mapping[str, Any],
    races: Mapping[str, Mapping[str, Any]],
    performances: Mapping[str, Mapping[str, Any]],
    uncertainty: float,
) -> dict[str, Any] | None:
    target = graph["target"]
    by_runner: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for performance in performances.values():
        by_runner[str(performance["runner_id"])].append(performance)
    estimates: list[tuple[float, float, str, list[str]]] = []
    for bridge in graph.get("edges", []):
        if bridge.get("edge_type") != "same_race_peer_bridge":
            continue
        peer_id = str(bridge["to"])
        bridge_ids = {str(value) for value in bridge.get("bridge_record_ids", [])}
        for performance in by_runner.get(peer_id, []):
            if str(performance["node_id"]) in bridge_ids:
                continue
            race = races.get(str(performance["race_id"]))
            if race is None:
                continue
            distance_similarity = 1.0 - abs(float(race["distance_km"]) - float(target["distance_km"])) / max(float(race["distance_km"]), float(target["distance_km"]))
            if distance_similarity < 0.35:
                continue
            source_confidence = float(performance.get("source", {}).get("confidence", 0.0))
            quality = max(0.0, distance_similarity) * float(bridge.get("confidence", 0.0)) * source_confidence
            projected = _scaled_time(performance, race, target) * float(bridge["performance_ratio_target_to_peer"])
            estimates.append((projected, quality, peer_id, sorted(bridge_ids | {str(performance["node_id"])})))
    if not estimates:
        return None
    # One contribution per peer prevents a prolific runner from dominating.
    best_by_peer: dict[str, tuple[float, float, str, list[str]]] = {}
    for item in estimates:
        if item[2] not in best_by_peer or item[1] > best_by_peer[item[2]][1]:
            best_by_peer[item[2]] = item
    selected = list(best_by_peer.values())
    midpoint = _weighted_mean([(item[0], item[1]) for item in selected])
    quality = min(1.0, sum(item[1] for item in selected) / len(selected))
    return {
        "path_id": "similar_runner_cross_event",
        "available": True,
        "directional_only": False,
        "dependency_group": "independent_peer_bridges",
        "prediction": _path_range(midpoint, uncertainty + 0.06 + (1.0 - quality) * 0.10),
        "raw_dynamic_weight": round(PATH_BASE_WEIGHTS["similar_runner_cross_event"] * quality, 6),
        "weight_components": {"base_priority": PATH_BASE_WEIGHTS["similar_runner_cross_event"], "mean_quality": round(quality, 6), "peer_count": len(selected)},
        "source_record_ids": sorted({record_id for item in selected for record_id in item[3]}),
        "calculation": "same_race_target_peer_ratio_times_distinct_peer_cross_event_projection",
        "cycle_controls": ["bridge_records_cannot_be_projection_records", "one_contribution_per_peer", "target_runner_cannot_be_peer"],
        "limitations": ["Peer mapping is an internal unvalidated research candidate."],
    }


def _elite_direction(graph: Mapping[str, Any], races: Mapping[str, Mapping[str, Any]], performances: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    paces: list[float] = []
    source_ids: list[str] = []
    for edge in graph.get("edges", []):
        if edge.get("edge_type") != "elite_directional_anchor":
            continue
        performance = performances.get(str(edge["from"]))
        race = races.get(str(performance.get("race_id"))) if performance else None
        if performance and race:
            paces.append(float(performance["finish_time_minutes"]) / _effort_distance(float(race["distance_km"]), float(race["elevation_gain_m"])))
            source_ids.append(str(performance["node_id"]))
    return {
        "path_id": "elite_directional_anchor",
        "available": bool(paces),
        "directional_only": True,
        "direct_prediction_weight": 0.0,
        "prediction": None,
        "direction": "faster_capability_anchor_only" if paces else None,
        "source_record_ids": sorted(source_ids),
        "explanation": "Elite anchors are retained for directional context and never directly set the target runner time.",
    }


def build_multipath_prediction(
    *,
    reference_graph: Mapping[str, Any],
    distance_only_baseline: Mapping[str, Any],
    verified_modifiers: Mapping[str, Any] | None = None,
    require_two_independent_reference_paths: bool = False,
) -> dict[str, Any]:
    """Build a baseline-bounded candidate; never evaluates validation/holdout."""

    _validate_graph(reference_graph)
    validate_baseline(distance_only_baseline)
    races, performances = _graph_indexes(reference_graph)
    target = reference_graph["target"]
    label, _, base_uncertainty = _band(float(target["distance_km"]))
    baseline_range = {key: float(value) for key, value in distance_only_baseline["finish_range_minutes"].items()}
    paths: list[dict[str, Any]] = [{
        "path_id": "distance_only",
        "available": True,
        "directional_only": False,
        "dependency_group": "retained_baseline",
        "prediction": baseline_range,
        "raw_dynamic_weight": PATH_BASE_WEIGHTS["distance_only"],
        "weight_components": {"base_priority": 1.0, "retained_after_phase8a": True},
        "source_record_ids": [],
        "calculation": distance_only_baseline.get("formula_reference"),
    }]
    same_event = _candidate_from_edges(path_id="same_runner_same_event", edge_type="same_runner_same_event_reference", graph=reference_graph, races=races, performances=performances, uncertainty=base_uncertainty, dependency_group="target_runner_history")
    self_history = _candidate_from_edges(path_id="self_history_similar_course", edge_type="self_history_similar_course_reference", graph=reference_graph, races=races, performances=performances, uncertainty=base_uncertainty + 0.03, dependency_group="target_runner_history")
    peer = _peer_path(reference_graph, races, performances, base_uncertainty)
    for path in (same_event, self_history, peer):
        if path:
            paths.append(path)
    paths.append(_elite_direction(reference_graph, races, performances))

    numeric_refs = [path for path in paths if path.get("available") and not path.get("directional_only") and path["path_id"] != "distance_only"]
    independent_groups = {path["dependency_group"] for path in numeric_refs}
    if require_two_independent_reference_paths and len(independent_groups) < 2:
        raise MultipathPredictionError("insufficient_independent_reference_paths")

    # Cap shared target-runner history, peer mappings, then preserve a baseline floor.
    grouped_raw: dict[str, float] = defaultdict(float)
    for path in numeric_refs:
        grouped_raw[path["dependency_group"]] += float(path["raw_dynamic_weight"])
    caps = {"target_runner_history": 0.25, "independent_peer_bridges": 0.30}
    adjusted: dict[str, float] = {"distance_only": 1.0}
    for path in numeric_refs:
        group = path["dependency_group"]
        group_total = grouped_raw[group]
        group_cap = caps.get(group, 0.20)
        adjusted[path["path_id"]] = min(float(path["raw_dynamic_weight"]), group_cap * float(path["raw_dynamic_weight"]) / max(group_total, 1e-9))
    total = sum(adjusted.values())
    normalized = {key: value / total for key, value in adjusted.items()}
    if normalized["distance_only"] < 0.55:
        reference_total = sum(value for key, value in normalized.items() if key != "distance_only")
        normalized = {key: (0.55 if key == "distance_only" else value / reference_total * 0.45) for key, value in normalized.items()}
    for path in paths:
        path["final_dynamic_weight"] = round(normalized.get(path["path_id"], 0.0), 6)

    if numeric_refs:
        aggregate_mid = sum(path["prediction"]["midpoint_minutes"] * normalized[path["path_id"]] for path in paths if path.get("prediction"))
        midpoints = [baseline_range["midpoint_minutes"]] + [path["prediction"]["midpoint_minutes"] for path in numeric_refs]
        spread = (max(midpoints) - min(midpoints)) / max(statistics.median(midpoints), 1.0)
        conflict = spread >= 0.18
        widen = min(0.25, max(0.0, spread - 0.08)) if conflict else 0.0
        lower = min(path["prediction"]["lower_minutes"] for path in paths if path.get("prediction"))
        upper = max(path["prediction"]["upper_minutes"] for path in paths if path.get("prediction"))
        lower = min(lower, aggregate_mid * (1.0 - base_uncertainty - widen))
        upper = max(upper, aggregate_mid * (1.0 + base_uncertainty + widen))
        status = "internal_unvalidated_research_candidate"
    else:
        aggregate_mid = baseline_range["midpoint_minutes"]
        lower = baseline_range["lower_minutes"]
        upper = baseline_range["upper_minutes"]
        spread = 0.0
        widen = 0.0
        conflict = False
        status = "distance_only_fallback_no_usable_reference"

    modifier_factor = 1.0
    applied_modifiers: list[dict[str, Any]] = []
    rejected_modifiers: list[dict[str, Any]] = []
    for name, modifier in (verified_modifiers or {}).items():
        if not isinstance(modifier, Mapping) or modifier.get("status") != "verified_pre_race" or modifier.get("factor") is None:
            rejected_modifiers.append({"name": name, "reason": "not_verified_pre_race"})
            continue
        factor = float(modifier["factor"])
        if not 0.85 <= factor <= 1.30 or not modifier.get("source_reference"):
            rejected_modifiers.append({"name": name, "reason": "factor_or_source_invalid"})
            continue
        modifier_factor *= factor
        applied_modifiers.append({"name": name, "factor": factor, "source_reference": modifier["source_reference"]})
    aggregate_mid *= modifier_factor
    lower *= modifier_factor
    upper *= modifier_factor

    confidence = "low"
    if len(independent_groups) >= 2 and not conflict:
        confidence = "medium_low"
    missing = []
    if not same_event:
        missing.append("same_runner_prior_same_event_result")
    if not peer:
        missing.append("authorized_same_race_peer_bridge_plus_distinct_peer_projection")
    if not _elite_direction(reference_graph, races, performances)["available"]:
        missing.append("authorized_elite_directional_anchor")
    return {
        "schema_name": "multipath_prediction",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "model_id": MODEL_ID,
        "status": status,
        "governance": dict(GOVERNANCE),
        "target": dict(target),
        "distance_band": label,
        "retained_baseline": {"model_id": "distance_only", "selection_decision": "retain_distance_only", "finish_range_minutes": baseline_range},
        "paths": paths,
        "aggregate_candidate": {
            "optimistic": {"lower_minutes": round(lower, 2), "upper_minutes": round(aggregate_mid, 2)},
            "baseline": {"lower_minutes": round(lower, 2), "midpoint_minutes": round(aggregate_mid, 2), "upper_minutes": round(upper, 2)},
            "conservative": {"lower_minutes": round(aggregate_mid, 2), "upper_minutes": round(upper, 2)},
            "user_facing": False,
            "calibrated": False,
        },
        "dynamic_weighting": {
            "weights": {key: round(value, 6) for key, value in normalized.items()},
            "baseline_floor": 0.55,
            "dependency_caps": caps,
            "same_source_rows_deduplicated": True,
        },
        "conflict_analysis": {
            "conflict": conflict,
            "midpoint_relative_spread": round(spread, 6),
            "interval_widening_fraction": round(widen, 6),
            "resolution": "widen_interval_do_not_force_average" if conflict else "no_material_conflict",
        },
        "modifiers": {"applied": applied_modifiers, "rejected": rejected_modifiers, "combined_factor": round(modifier_factor, 6)},
        "confidence": confidence,
        "faster_factors": [item["name"] for item in applied_modifiers if item["factor"] < 1.0],
        "slower_factors": [item["name"] for item in applied_modifiers if item["factor"] > 1.0],
        "most_valuable_missing_data": missing,
        "diagnostics": {
            "numeric_reference_path_count": len(numeric_refs),
            "independent_reference_group_count": len(independent_groups),
            "fallback_to_distance_only": not numeric_refs,
            "validation_or_holdout_evaluation_performed": False,
            "phase10_entered": False,
        },
        "warnings": [
            "This complex model is an internal unvalidated research candidate.",
            "It is not approved for user-facing prediction and is not claimed to outperform distance_only.",
            "No validation or holdout record, prediction, or error was used.",
        ],
    }
