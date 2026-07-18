"""Build an anonymous, time-valid runner/race/reference graph."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from .constants import CACHE_POLICY_VERSION, GENERATOR_VERSION, GOVERNANCE, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION
from .validation import ReferenceInputError, parse_time, validate_records, validate_target


class ReferenceGraphError(ReferenceInputError):
    """Graph construction failure caused by an unsafe or incomplete input."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _similarity(a: float, b: float) -> float:
    return round(max(0.0, 1.0 - abs(a - b) / max(a, b, 1.0)), 6)


def _course_similarity(record: Mapping[str, Any], target: Mapping[str, Any]) -> float:
    distance = _similarity(float(record["distance_km"]), float(target["distance_km"]))
    left_density = float(record["elevation_gain_m"]) / float(record["distance_km"])
    right_density = float(target["elevation_gain_m"]) / float(target["distance_km"])
    gain = _similarity(left_density, right_density)
    technical = 0.65
    if record.get("technical_score") is not None and target.get("technical_score") is not None:
        technical = _similarity(float(record["technical_score"]), float(target["technical_score"]))
    return round(0.5 * distance + 0.35 * gain + 0.15 * technical, 6)


def _recency(record: Mapping[str, Any], target: Mapping[str, Any]) -> float:
    days = max(0.0, (parse_time(target["prediction_as_of"]) - parse_time(record["race_date"])).total_seconds() / 86400.0)
    return round(math.exp(-days / 730.0), 6)


def _source_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    source = record["source"]
    return {
        "source_type": source["source_type"],
        "source_uri": source["source_uri"],
        "source_fingerprint": source["source_fingerprint"],
        "captured_at": source["captured_at"],
        "confidence": float(source["confidence"]),
        "immutable": bool(source.get("immutable", True)),
    }


def build_reference_graph(
    *,
    target: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    manual_exclusions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build Phase 7B graph without evaluation rows or post-cutoff facts."""

    validate_target(target)
    validate_records(records, target)
    exclusions = {str(item.get("runner_id")): str(item.get("reason") or "manual_exclusion") for item in (manual_exclusions or [])}
    usable = [dict(record) for record in records if str(record["runner_id"]) not in exclusions]
    target_runner = str(target["target_runner_id"])
    target_series = str(target.get("event_series_id") or target["target_race_id"])
    target_race_id = str(target["target_race_id"])
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    runner_ids = sorted({str(record["runner_id"]) for record in usable} | {target_runner})
    for runner_id in runner_ids:
        roles = sorted({str(record.get("runner_role") or "peer") for record in usable if record["runner_id"] == runner_id})
        runner_sources = [_source_projection(record) for record in usable if record["runner_id"] == runner_id]
        nodes.append({
            "node_id": runner_id,
            "node_type": "runner",
            "anonymous": True,
            "roles": roles or (["target"] if runner_id == target_runner else ["peer"]),
            "valid_from": min((str(record["race_date"]) for record in usable if record["runner_id"] == runner_id), default=target["prediction_as_of"]),
            "valid_until": target["prediction_as_of"],
            "source": {"source_type": "pseudonymous_authorized_record_set", "record_sources": runner_sources},
            "confidence": min((item["confidence"] for item in runner_sources), default=0.5),
            "version": "1.0.0",
        })
    nodes.append({
        "node_id": target_race_id,
        "node_type": "race",
        "event_series_id": target_series,
        "race_date": target["race_date"],
        "distance_km": float(target["distance_km"]),
        "elevation_gain_m": float(target["elevation_gain_m"]),
        "route_version": target.get("route_version"),
        "group_id": target.get("group_id"),
        "is_prediction_target": True,
        "valid_from": target["prediction_as_of"],
        "valid_until": target["race_date"],
        "source": target.get("source") or {"source_type": "caller_supplied_target", "source_uri": None, "source_fingerprint": None},
        "confidence": float(target.get("source_confidence", 0.5)),
        "version": "1.0.0",
    })

    race_seen = {target_race_id}
    for record in usable:
        record_id = str(record["record_id"])
        race_id = str(record["race_id"])
        series = str(record.get("event_series_id") or race_id)
        if race_id not in race_seen:
            race_seen.add(race_id)
            nodes.append({
                "node_id": race_id,
                "node_type": "race",
                "event_series_id": series,
                "race_date": record["race_date"],
                "distance_km": float(record["distance_km"]),
                "elevation_gain_m": float(record["elevation_gain_m"]),
                "route_version": record.get("route_version"),
                "group_id": record.get("group_id"),
                "is_prediction_target": False,
                "valid_from": record["race_date"],
                "valid_until": target["prediction_as_of"],
                "source": _source_projection(record),
                "confidence": float(record["source"]["confidence"]),
                "version": "1.0.0",
            })
        nodes.append({
            "node_id": record_id,
            "node_type": "performance",
            "runner_id": record["runner_id"],
            "race_id": race_id,
            "finish_time_minutes": float(record["finish_time_minutes"]),
            "split": record["split"],
            "valid_at_prediction_time": True,
            "source": _source_projection(record),
            "confidence": float(record["source"]["confidence"]),
            "valid_from": record["race_date"],
            "valid_until": target["prediction_as_of"],
            "version": "1.0.0",
        })
        common = {
            "edge_version": "1.0.0",
            "valid_from": record["race_date"],
            "valid_until": target["prediction_as_of"],
            "observed_by": record.get("available_at") or record["race_date"],
            "source": _source_projection(record),
            "confidence": float(record["source"]["confidence"]),
        }
        edges.extend([
            {"edge_id": _stable_id("edge", record_id, "runner"), "edge_type": "performance_by_runner", "from": record_id, "to": record["runner_id"], **common},
            {"edge_id": _stable_id("edge", record_id, "race"), "edge_type": "performance_at_race", "from": record_id, "to": race_id, **common},
        ])
        similarity = _course_similarity(record, target)
        if record["runner_id"] == target_runner:
            edge_type = "same_runner_same_event_reference" if series == target_series else "self_history_similar_course_reference"
            edges.append({
                "edge_id": _stable_id("edge", record_id, target_race_id, edge_type),
                "edge_type": edge_type,
                "from": record_id,
                "to": target_race_id,
                "course_similarity": similarity,
                "recency": _recency(record, target),
                "directional_only": False,
                "dependency_group": "target_runner_history",
                **common,
            })
        elif record.get("runner_role") == "elite_anchor":
            edges.append({
                "edge_id": _stable_id("edge", record_id, target_race_id, "elite"),
                "edge_type": "elite_directional_anchor",
                "from": record_id,
                "to": target_race_id,
                "course_similarity": similarity,
                "recency": _recency(record, target),
                "directional_only": True,
                "direct_prediction_weight": 0.0,
                "dependency_group": f"elite:{record['runner_id']}",
                **common,
            })

    by_occurrence: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in usable:
        occurrence = (
            str(record.get("event_series_id") or record["race_id"]),
            str(record["race_date"])[:10],
            str(record.get("group_id") or ""),
        )
        by_occurrence[occurrence].append(record)
    for occurrence, group in by_occurrence.items():
        target_rows = [row for row in group if row["runner_id"] == target_runner]
        peer_rows = [row for row in group if row["runner_id"] != target_runner and row.get("runner_role") != "elite_anchor"]
        for target_row in target_rows:
            for peer_row in peer_rows:
                ratio = float(target_row["finish_time_minutes"]) / float(peer_row["finish_time_minutes"])
                confidence = min(float(target_row["source"]["confidence"]), float(peer_row["source"]["confidence"]))
                edges.append({
                    "edge_id": _stable_id("edge", target_row["record_id"], peer_row["record_id"], "bridge"),
                    "edge_type": "same_race_peer_bridge",
                    "from": target_row["runner_id"],
                    "to": peer_row["runner_id"],
                    "bridge_record_ids": [target_row["record_id"], peer_row["record_id"]],
                    "event_series_id": occurrence[0],
                    "group_id": occurrence[2] or None,
                    "performance_ratio_target_to_peer": round(ratio, 6),
                    "confidence": confidence,
                    "directional_only": False,
                    "dependency_group": f"peer:{peer_row['runner_id']}",
                    "edge_version": "1.0.0",
                    "valid_from": target_row["race_date"],
                    "valid_until": target["prediction_as_of"],
                    "observed_by": max(str(target_row.get("available_at") or target_row["race_date"]), str(peer_row.get("available_at") or peer_row["race_date"])),
                    "source": {"source_type": "derived_from_two_authorized_records", "source_record_ids": [target_row["record_id"], peer_row["record_id"]], "confidence": confidence},
                })

    bridge_count = sum(edge["edge_type"] == "same_race_peer_bridge" for edge in edges)
    graph = {
        "schema_name": "reference_graph",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "governance": dict(GOVERNANCE),
        "target": {
            "target_runner_id": target_runner,
            "target_race_id": target_race_id,
            "event_series_id": target_series,
            "prediction_as_of": target["prediction_as_of"],
            "race_date": target["race_date"],
            "distance_km": float(target["distance_km"]),
            "elevation_gain_m": float(target["elevation_gain_m"]),
            "route_version": target.get("route_version"),
            "technical_score": target.get("technical_score"),
        },
        "nodes": nodes,
        "edges": edges,
        "manual_exclusions": [{"runner_id": key, "reason": value} for key, value in sorted(exclusions.items())],
        "diagnostics": {
            "input_record_count": len(records),
            "usable_record_count": len(usable),
            "excluded_runner_count": len(exclusions),
            "runner_node_count": len(runner_ids),
            "race_node_count": len(race_seen),
            "performance_node_count": len(usable),
            "peer_bridge_count": bridge_count,
            "future_records_used": 0,
            "validation_records_used": 0,
            "holdout_records_used": 0,
            "target_race_results_used": 0,
        },
        "integrity": {
            "anonymous_only": True,
            "acyclic_prediction_paths_required": True,
            "same_source_deduplication_required": True,
            "same_runner_same_event_dependency_capped": True,
            "fingerprint": None,
        },
    }
    canonical = json.dumps({**graph, "generated_at": None, "integrity": {**graph["integrity"], "fingerprint": None}}, sort_keys=True, ensure_ascii=False)
    graph["integrity"]["fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return graph
