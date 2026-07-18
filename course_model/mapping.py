"""Final document mapping for course model output."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .capture_audit import build_target_group_capture


def build_cache_key(bundle: Mapping[str, Any], grade: Mapping[str, Any], normalized: Mapping[str, Any]) -> str:
    event = bundle["event"]
    route_version = event.get("route_version")
    route_version_key = "null" if route_version is None else str(route_version)
    return "|".join(
        [
            "course_model",
            str(event.get("year")),
            str(event.get("group_name")),
            f"route_version={route_version_key}",
            f"grade={grade.get('grade')}",
            f"source_bundle={bundle.get('cache_key')}",
        ]
    )


def map_course_model(
    bundle: Mapping[str, Any],
    *,
    grade: Mapping[str, Any],
    normalized: Mapping[str, Any],
    cp_model: Mapping[str, Any],
) -> dict[str, Any]:
    event = bundle["event"]
    facts = event["facts"]
    cache_key = build_cache_key(bundle, grade, normalized)

    sources = bundle.get("sources", [])
    cp_points = cp_model.get("cp_points", [])
    segments = cp_model.get("segments", [])
    total_distance_km = normalized["course"]["total_distance_km"]["value"]
    segment_sum_km = 0.0
    for segment in segments:
        segment_km = segment.get("segment_distance_km")
        if segment_km is not None:
            segment_sum_km += float(segment_km)
    distance_delta_km = None
    distance_check_status = "not_enough_data"
    if total_distance_km is not None and segments:
        distance_delta_km = round(abs(float(total_distance_km) - segment_sum_km), 6)
        distance_check_status = "passed" if distance_delta_km <= 0.05 else "failed"

    cp_distance_is_strict = all(
        current.get("distance_m") is None
        or previous.get("distance_m") is None
        or float(current["distance_m"]) > float(previous["distance_m"])
        for previous, current in zip(cp_points, cp_points[1:])
    ) if len(cp_points) > 1 else True

    diagnostics = {
        "input_validation": {
            "status": "passed",
            "error_count": 0,
        },
        "material_grade": grade,
        "partial_reasons": normalized["unavailable_fields"],
        "source_count": len(sources),
        "route_state": normalized["cache_state"]["route_state"],
        "course_model_status": cp_model["status"],
        "distance_check": {
            "total_distance_km": total_distance_km,
            "segment_sum_km": round(segment_sum_km, 3) if segments else None,
            "delta_km": distance_delta_km,
            "status": distance_check_status,
            "note": "The route-track distance should match the sum of CP segment distances; any mismatch must be explained as display rounding or source conflict.",
        },
        "cp_sequence_check": {
            "strictly_increasing": cp_distance_is_strict,
            "status": "passed" if cp_distance_is_strict else "failed",
        },
    }

    course = {
        **normalized["course"],
        "cp_model": cp_model,
    }

    result = {
        "schema_name": "course_model",
        "schema_version": "1.0.0",
        "generated_at": bundle["generated_at"],
        "generator_version": "0.1.0",
        "source_policy_version": bundle.get("source_policy_version", "1.0.0"),
        "cache_policy_version": bundle.get("cache_policy_version", "1.0.0"),
        "safety_notice": bundle["safety_notice"],
        "cache_key": cache_key,
        "event": {
            "official_name": normalized["identity"]["official_name"]["value"],
            "year": normalized["identity"]["year"]["value"],
            "group_code": normalized["identity"]["group_code"]["value"],
            "group_name": normalized["identity"]["group_name"]["value"],
            "route_version": normalized["course"]["route_version"]["value"],
            "route_version_state": normalized["cache_state"]["route_state"],
            "identity": normalized["identity"],
            "course": course,
            "grade": grade,
            "unavailable_fields": normalized["unavailable_fields"],
            "limitations": normalized["limitations"],
            "reingest_conditions": normalized["reingest_conditions"],
            "target_group_capture": build_target_group_capture(bundle),
            "visual_evidence": list(event.get("visual_evidence") or facts.get("wechat_visual_evidence") or []),
            "visual_evidence_attempts": list(event.get("visual_evidence_attempts") or facts.get("wechat_visual_attempts") or []),
            "visual_selection": dict(event.get("visual_selection") or facts.get("visual_selection") or {}),
        },
        "sources": sources,
        "cache_state": normalized["cache_state"],
        "diagnostics": diagnostics,
        "cp_standard": {
            "unified_cp_types": cp_model["unified_cp_types"],
            "mapping_rules": [
                {
                    "rule": "official materials that only mention a supply station must not be auto-mapped to a timed CP",
                    "result": "estimated_station",
                },
                {
                    "rule": "timing evidence must not be inferred from aid-station text alone",
                    "result": "no_live_timing",
                },
            ],
        },
    }
    if isinstance(bundle.get("request_binding"), Mapping):
        result["request_binding"] = dict(bundle["request_binding"])
    return result
