"""Normalization helpers for course model fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


CONFIDENCE_BY_SOURCE_KIND = {
    "official": 0.96,
    "third_party_aggregator": 0.76,
    "blocked_official": 0.1,
    "derived": 1.0,
    "unavailable": 0.0,
}


def _source_kind_phrase(source_kind: str | None) -> str:
    if source_kind == "official":
        return "official evidence"
    if source_kind == "third_party_aggregator":
        return "aggregator evidence"
    if source_kind == "blocked_official":
        return "blocked official evidence"
    if source_kind == "derived":
        return "derived evidence"
    return "unclassified evidence"


def _source_lookup(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sources = bundle.get("sources") or []
    return {source["source_id"]: source for source in sources if "source_id" in source}


def _field_source_id(field_sources: Mapping[str, Any], field_name: str, fallback: str | None = None) -> str:
    entries = field_sources.get(field_name) or []
    if entries:
        return entries[0]["source_id"]
    if fallback is not None:
        return fallback
    raise KeyError(field_name)


def _source_ref(bundle: Mapping[str, Any], source_id: str, field_name: str) -> dict[str, Any]:
    source = _source_lookup(bundle)[source_id]
    evidence_path = source.get("evidence_paths", {}).get("html")
    return {
        "source_id": source_id,
        "source_kind": source.get("source_kind"),
        "source_uri": source.get("final_url") or source.get("source_url"),
        "retrieved_at": source.get("retrieved_at"),
        "source_fingerprint": source.get("sha256"),
        "evidence_path": evidence_path,
        "capture_status": source.get("capture_status"),
        "field_name": field_name,
    }


def _is_official_source(source_lookup: Mapping[str, Mapping[str, Any]], source_id: str) -> bool:
    """Return true only for evidence explicitly classified as official."""

    return source_lookup.get(source_id, {}).get("source_kind") == "official"


def build_field_record(
    bundle: Mapping[str, Any],
    *,
    field_name: str,
    value: Any,
    source_id: str,
    source_kind: str | None = None,
    confidence: float | None = None,
    officially_confirmed: bool = False,
    unit: str | None = None,
    note: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    source = _source_lookup(bundle)[source_id]
    record_source_kind = source_kind or source.get("source_kind") or "unknown"
    return {
        "value": value,
        "unit": unit,
        "status": status,
        "source_kind": record_source_kind,
        "confidence": confidence if confidence is not None else CONFIDENCE_BY_SOURCE_KIND.get(record_source_kind, 0.5),
        "officially_confirmed": officially_confirmed,
        "evidence": [_source_ref(bundle, source_id, field_name)],
        "note": note,
    }


def normalize_course_fields(bundle: Mapping[str, Any], grade: dict[str, Any]) -> dict[str, Any]:
    event = bundle["event"]
    facts = event["facts"]
    field_sources = event["field_sources"]
    source_lookup = _source_lookup(bundle)
    official_source_id = next((sid for sid, src in source_lookup.items() if src.get("source_kind") == "official"), None)

    identity_source_ids = {
        field_name: _field_source_id(field_sources, field_name, official_source_id)
        for field_name in ("official_name", "year", "group_name", "group_code")
    }
    identity = {
        "official_name": build_field_record(
            bundle,
            field_name="official_name",
            value=event["official_name"],
            source_id=identity_source_ids["official_name"],
            officially_confirmed=_is_official_source(source_lookup, identity_source_ids["official_name"]),
            note="Event identity retained at the source evidence tier.",
        ),
        "year": build_field_record(
            bundle,
            field_name="year",
            value=event["year"],
            source_id=identity_source_ids["year"],
            officially_confirmed=_is_official_source(source_lookup, identity_source_ids["year"]),
            note="Event year retained at the source evidence tier.",
        ),
        "group_name": build_field_record(
            bundle,
            field_name="group_name",
            value=event["group_name"],
            source_id=identity_source_ids["group_name"],
            officially_confirmed=_is_official_source(source_lookup, identity_source_ids["group_name"]),
            note="Race group label retained at the source evidence tier.",
        ),
        "group_code": build_field_record(
            bundle,
            field_name="group_code",
            value=event["group_code"],
            source_id=identity_source_ids["group_code"],
            officially_confirmed=_is_official_source(source_lookup, identity_source_ids["group_code"]),
            note="Race group code retained at the source evidence tier.",
        ),
    }

    route_is_final = event.get("route_version") is not None
    route_text_source_id = field_sources["route_text"][0]["source_id"]
    route_text_source_kind = source_lookup[route_text_source_id]["source_kind"]
    route_source_id = _field_source_id(field_sources, "route_version", route_text_source_id)
    route_source_kind = source_lookup[route_source_id].get("source_kind", "unknown")
    distance_source_kind = field_sources["total_distance_km"][0]["source_kind"]
    gain_source_kind = field_sources["total_elevation_gain_m"][0]["source_kind"]
    loss_source_kind = field_sources["total_elevation_loss_m"][0]["source_kind"]
    start_source_kind = field_sources["start_time"][0]["source_kind"]
    cutoff_source_kind = field_sources["cutoff_time"][0]["source_kind"]
    cutoff_hours_source_kind = field_sources["cutoff_hours"][0]["source_kind"]

    course = {
        "route_version": build_field_record(
            bundle,
            field_name="route_version",
            value=event.get("route_version"),
            source_id=route_source_id,
            source_kind=route_source_kind,
            officially_confirmed=route_is_final and _is_official_source(source_lookup, route_source_id),
            status="unknown" if not route_is_final else "versioned",
            note=(
                "Route version is unknown and is not promoted to official provenance."
                if not route_is_final
                else "Route version retained at the source evidence tier."
            ),
        ),
        "route_text": build_field_record(
            bundle,
            field_name="route_text",
            value=facts.get("route_text"),
            source_id=route_text_source_id,
            source_kind=route_text_source_kind,
            officially_confirmed=route_is_final and route_text_source_kind == "official",
            confidence=0.82 if not route_is_final else 0.96,
            note="Official route description; still provisional because the route version is not final.",
        ),
        "course_map": build_field_record(
            bundle,
            field_name="course_map",
            value=facts.get("course_map"),
            source_id=_field_source_id(field_sources, "course_map", official_source_id),
            source_kind="official",
            officially_confirmed=facts.get("course_map") is not None and route_is_final,
            confidence=0.96 if facts.get("course_map") is not None else 0.0,
            note="Course map is only populated when a verified official map exists.",
        ) if facts.get("course_map") is not None else None,
        "elevation_map": build_field_record(
            bundle,
            field_name="elevation_map",
            value=facts.get("elevation_map"),
            source_id=_field_source_id(field_sources, "elevation_map", official_source_id),
            source_kind="official",
            officially_confirmed=facts.get("elevation_map") is not None and route_is_final,
            confidence=0.96 if facts.get("elevation_map") is not None else 0.0,
            note="Elevation map is only populated when a verified official map exists.",
        ) if facts.get("elevation_map") is not None else None,
        "total_distance_km": build_field_record(
            bundle,
            field_name="total_distance_km",
            value=facts.get("total_distance_km"),
            source_id=field_sources["total_distance_km"][0]["source_id"],
            source_kind=field_sources["total_distance_km"][0]["source_kind"],
            officially_confirmed=field_sources["total_distance_km"][0]["source_kind"] == "official",
            confidence=0.76,
            unit="km",
            note=f"Distance is sourced from {_source_kind_phrase(distance_source_kind)} and is not promoted beyond its source kind.",
        ),
        "track_distance_km_display": build_field_record(
            bundle,
            field_name="track_distance_km_display",
            value=facts.get("track_distance_km_display"),
            source_id=field_sources["track_distance_km_display"][0]["source_id"],
            source_kind=field_sources["track_distance_km_display"][0]["source_kind"],
            officially_confirmed=True,
            confidence=0.96,
            unit="km",
            note="Public hero-card distance shown on the race page; retained as a display value only.",
        ) if facts.get("track_distance_km_display") is not None else None,
        "total_elevation_gain_m": build_field_record(
            bundle,
            field_name="total_elevation_gain_m",
            value=facts.get("total_elevation_gain_m"),
            source_id=field_sources["total_elevation_gain_m"][0]["source_id"],
            source_kind=field_sources["total_elevation_gain_m"][0]["source_kind"],
            officially_confirmed=field_sources["total_elevation_gain_m"][0]["source_kind"] == "official",
            confidence=0.76,
            unit="m",
            note=f"Elevation gain is sourced from {_source_kind_phrase(gain_source_kind)} and is not promoted beyond its source kind.",
        ),
        "total_elevation_gain_m_display": build_field_record(
            bundle,
            field_name="total_elevation_gain_m_display",
            value=facts.get("total_elevation_gain_m_display"),
            source_id=field_sources["total_elevation_gain_m_display"][0]["source_id"],
            source_kind=field_sources["total_elevation_gain_m_display"][0]["source_kind"],
            officially_confirmed=True,
            confidence=0.96,
            unit="m",
            note="Public hero-card elevation gain shown on the race page; retained as a display value only.",
        ) if facts.get("total_elevation_gain_m_display") is not None else None,
        "total_elevation_loss_m": build_field_record(
            bundle,
            field_name="total_elevation_loss_m",
            value=facts.get("total_elevation_loss_m"),
            source_id=field_sources["total_elevation_loss_m"][0]["source_id"],
            source_kind=field_sources["total_elevation_loss_m"][0]["source_kind"],
            officially_confirmed=field_sources["total_elevation_loss_m"][0]["source_kind"] == "official",
            confidence=0.76,
            unit="m",
            note=f"Elevation loss is sourced from {_source_kind_phrase(loss_source_kind)} and is not promoted beyond its source kind.",
        ),
        "start_time": build_field_record(
            bundle,
            field_name="start_time",
            value=facts.get("start_time"),
            source_id=field_sources["start_time"][0]["source_id"],
            source_kind=field_sources["start_time"][0]["source_kind"],
            officially_confirmed=field_sources["start_time"][0]["source_kind"] == "official",
            confidence=0.76,
            note=f"Start time is sourced from {_source_kind_phrase(start_source_kind)} and is not promoted beyond its source kind.",
        ),
        "cutoff_time": build_field_record(
            bundle,
            field_name="cutoff_time",
            value=facts.get("cutoff_time"),
            source_id=field_sources["cutoff_time"][0]["source_id"],
            source_kind=field_sources["cutoff_time"][0]["source_kind"],
            officially_confirmed=field_sources["cutoff_time"][0]["source_kind"] == "official",
            confidence=0.76,
            note=f"Cutoff time is sourced from {_source_kind_phrase(cutoff_source_kind)} and is not promoted beyond its source kind.",
        ),
        "cutoff_hours": build_field_record(
            bundle,
            field_name="cutoff_hours",
            value=facts.get("cutoff_hours"),
            source_id=field_sources["cutoff_hours"][0]["source_id"],
            source_kind=field_sources["cutoff_hours"][0]["source_kind"],
            officially_confirmed=field_sources["cutoff_hours"][0]["source_kind"] == "official",
            confidence=0.76,
            unit="hour",
            note=f"Cutoff duration is sourced from {_source_kind_phrase(cutoff_hours_source_kind)} and is not promoted beyond its source kind.",
        ),
    }

    unavailable_fields = list(dict.fromkeys(event.get("unavailable_fields", []) + [
        name for name, value in {
            "course_map": facts.get("course_map"),
            "elevation_map": facts.get("elevation_map"),
            "cp": facts.get("cp"),
            "official_aid_station_list": facts.get("official_aid_station_list"),
        }.items() if value in (None, [], "")
    ]))

    limitations = []
    if not facts.get("cp"):
        limitations.append("No CP table or track was confirmed from first-party evidence.")
    if not facts.get("course_map") or not facts.get("elevation_map"):
        limitations.append("No complete official course/elevation map pair was confirmed from first-party evidence.")
    if not facts.get("cp"):
        limitations.append("Do not infer CP distances, elevation per split, or aid stations from route text alone.")
    if facts.get("cp") and all(row.get("evidence_tier") == "official_historical_reference" for row in facts.get("cp", [])):
        limitations.append("CP rows are an official historical reference and are not target-year official facts.")
    if grade["grade"] == "C":
        limitations.append("This is a C-grade degraded sample and must not be promoted to a formal segment model.")

    reingest_conditions = [
        "official_route_version_published",
        "official_course_map_published",
        "official_cp_table_published",
        "official_track_or_gpx_published",
    ]

    cache_state = {
        "route_state": "unknown" if not route_is_final else "versioned",
        "stale_on": reingest_conditions,
        "current_route_version": event.get("route_version"),
    }

    return {
        "identity": identity,
        "course": course,
        "unavailable_fields": unavailable_fields,
        "limitations": limitations,
        "reingest_conditions": reingest_conditions,
        "cache_state": cache_state,
    }
