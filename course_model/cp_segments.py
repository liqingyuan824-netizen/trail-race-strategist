"""CP standardization and segment construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .constants import UNIFIED_CP_TYPES


def standardize_cp_type(raw_cp: Mapping[str, Any]) -> str:
    """Map a raw CP description into the unified CP type set."""

    if raw_cp.get("timing_mode") == "entry_exit" or (
        raw_cp.get("entry_timing") and raw_cp.get("exit_timing")
    ):
        return "entry_exit_timing"
    if raw_cp.get("timing_mode") == "single" or raw_cp.get("single_timing") or raw_cp.get("isChrono"):
        return "single_timing"
    if raw_cp.get("manual_observation") or raw_cp.get("observer_note") or raw_cp.get("isMeet"):
        return "manual_observation"
    if (
        raw_cp.get("aid_station")
        or raw_cp.get("station_only")
        or raw_cp.get("support_station")
        or raw_cp.get("isAssistance")
        or raw_cp.get("supplies") not in (None, "none")
    ):
        return "estimated_station"
    return "no_live_timing"


def build_cp_model(bundle: Mapping[str, Any], normalized: Mapping[str, Any]) -> dict[str, Any]:
    """Build a CP model without inventing checkpoints."""

    facts = bundle["event"]["facts"]
    raw_cp = facts.get("cp") or []
    cp_points: list[dict[str, Any]] = []

    for item in raw_cp:
        cp_type = standardize_cp_type(item)
        sequence = item.get("sequence")
        if sequence is None:
            sequence = len(cp_points) + 1
        distance_m = item.get("distance_m")
        if distance_m is None and item.get("distance_km") is not None:
            distance_m = round(float(item["distance_km"]) * 1000)
        cumulative_gain_m = item.get("cumulative_gain_m", item.get("gainElevation"))
        cumulative_loss_m = item.get("cumulative_loss_m", item.get("lossElevation"))
        segment_distance_m = item.get("segment_distance_m", item.get("distanceFromLastPoint"))
        if segment_distance_m is None and item.get("distanceFromLastPoint_km") is not None:
            segment_distance_m = round(float(item["distanceFromLastPoint_km"]) * 1000)
        segment_gain_m = item.get("segment_elevation_gain_m", item.get("gainElevationFromLastPoint"))
        segment_loss_m = item.get("segment_elevation_loss_m", item.get("lossElevationFromLastPoint"))
        cp_points.append(
            {
                "sequence": sequence,
                "name": item.get("name"),
                "type": cp_type,
                "short_name": item.get("short_name"),
                "role": item.get("role"),
                "distance_m": distance_m,
                "distance_km": (float(distance_m) / 1000) if distance_m is not None else item.get("distance_km"),
                "elevation_m": item.get("elevation_m"),
                "cumulative_gain_m": cumulative_gain_m,
                "cumulative_loss_m": cumulative_loss_m,
                "segment_distance_m": segment_distance_m,
                "segment_distance_km": (float(segment_distance_m) / 1000) if segment_distance_m is not None else item.get("segment_distance_km"),
                "segment_elevation_gain_m": segment_gain_m,
                "segment_elevation_loss_m": segment_loss_m,
                "is_chrono": bool(item.get("isChrono", False)),
                "is_meet": bool(item.get("isMeet", False)),
                "is_assistance": bool(item.get("isAssistance", False)),
                "supplies": item.get("supplies"),
                "source_kind": item.get("source_kind", "unknown"),
                "evidence_tier": item.get("evidence_tier", "current_year_official" if item.get("officially_confirmed") else "unverified"),
                "source_year": item.get("source_year"),
                "applicable_year": item.get("applicable_year"),
                "applicable_group": item.get("applicable_group"),
                "route_version": item.get("route_version"),
                "current_year_applicability": item.get("current_year_applicability", "confirmed" if item.get("officially_confirmed") else "unconfirmed"),
                "services": item.get("services", item.get("supplies")),
                "equipment_notes": item.get("equipment_notes"),
                "support_restrictions": item.get("support_restrictions"),
                "risk_notes": item.get("risk_notes", []),
                "terrain_notes": item.get("terrain_notes", []),
                "officially_confirmed": bool(item.get("officially_confirmed", False)),
                "confidence": item.get("confidence", 0.5),
                "evidence": item.get("evidence", []),
                "visual_transcription": item.get("visual_transcription"),
                "timing_window": {
                    "fastest": item.get("fastestDatetime"),
                    "slowest": item.get("slowestDatetime"),
                    "cutoff": item.get("cutoffDatetime"),
                },
            }
        )

    segments: list[dict[str, Any]] = []
    if len(cp_points) >= 2:
        for index, current in enumerate(cp_points[1:], start=1):
            prev = cp_points[index - 1]
            segment_distance_m = current.get("distance_m")
            prev_distance_m = prev.get("distance_m")
            if segment_distance_m is not None and prev_distance_m is not None:
                seg_distance = float(segment_distance_m) - float(prev_distance_m)
            else:
                seg_distance = current.get("segment_distance_m")
            if seg_distance is not None:
                seg_distance_km = float(seg_distance) / 1000
            else:
                seg_distance_km = None
            seg_gain = current.get("segment_elevation_gain_m")
            seg_loss = current.get("segment_elevation_loss_m")
            segments.append(
                {
                    "sequence": index,
                    "from_cp": prev.get("name"),
                    "to_cp": current.get("name"),
                    "segment_distance_m": seg_distance,
                    "segment_distance_km": seg_distance_km,
                    "cumulative_distance_m": current.get("distance_m"),
                    "cumulative_distance_km": current.get("distance_km"),
                    "segment_elevation_gain_m": seg_gain,
                    "segment_elevation_loss_m": seg_loss,
                    "cumulative_elevation_gain_m": current.get("cumulative_gain_m"),
                    "cumulative_elevation_loss_m": current.get("cumulative_loss_m"),
                    "source_kind": "derived",
                    "evidence_tier": current.get("evidence_tier"),
                    "source_year": current.get("source_year"),
                    "applicable_year": current.get("applicable_year"),
                    "applicable_group": current.get("applicable_group"),
                    "route_version": current.get("route_version"),
                    "current_year_applicability": current.get("current_year_applicability"),
                    "terrain_notes": current.get("terrain_notes", []),
                    "risk_notes": current.get("risk_notes", []),
                    "officially_confirmed": bool(prev.get("officially_confirmed") and current.get("officially_confirmed")),
                    "confidence": 0.98,
                    "note": "Derived from consecutive captured CP points; source tier is preserved.",
                }
            )

    model_status = "not_generated" if not cp_points else "partial"
    if cp_points and segments:
        model_status = "complete"

    return {
        "status": model_status,
        "unified_cp_types": list(UNIFIED_CP_TYPES),
        "cp_points": cp_points,
        "segments": segments,
        "cp_count": len(cp_points),
        "segment_count": len(segments),
    }
