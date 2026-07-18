"""Material grade classification for course modeling."""

from __future__ import annotations

from collections.abc import Mapping


def classify_material_grade(bundle: Mapping[str, object]) -> dict:
    """Classify source material as A, B, or C."""

    event = bundle["event"]  # validated by caller
    facts = event["facts"]
    field_sources = event.get("field_sources", {})

    cp = facts.get("cp") or []
    has_course_map = facts.get("course_map") is not None
    has_elevation_map = facts.get("elevation_map") is not None
    has_route_text = bool(facts.get("route_text"))
    has_distance = facts.get("total_distance_km") is not None
    has_gain = facts.get("total_elevation_gain_m") is not None
    has_loss = facts.get("total_elevation_loss_m") is not None
    has_cutoff = facts.get("cutoff_time") is not None
    cp_is_current_year_official = bool(cp) and all(
        row.get("evidence_tier") in {None, "current_year_official"}
        and bool(row.get("officially_confirmed", row.get("evidence_tier") is None))
        for row in cp
    )

    distance_source_kind = None
    if field_sources.get("total_distance_km"):
        distance_source_kind = field_sources["total_distance_km"][0].get("source_kind")
    course_map_source_kind = (field_sources.get("course_map") or [{}])[0].get("source_kind")
    elevation_map_source_kind = (field_sources.get("elevation_map") or [{}])[0].get("source_kind")

    complete_official_pack = all(
        [
            has_course_map,
            has_elevation_map,
            len(cp) > 0,
            cp_is_current_year_official,
            course_map_source_kind == "official",
            elevation_map_source_kind == "official",
            has_distance,
            has_gain,
            has_loss,
            has_cutoff,
            distance_source_kind == "official",
        ]
    )
    partial_map_or_cp = has_course_map or has_elevation_map or len(cp) > 0

    if complete_official_pack:
        grade = "A"
        reasons = [
            "official_course_map_present",
            "official_elevation_map_present",
            "official_cp_table_present",
            "official_distance_gain_cutoff_present",
        ]
    elif partial_map_or_cp:
        grade = "B"
        reasons = [
            "partial_course_artifacts_present",
            "course_map_or_cp_available",
        ]
    else:
        grade = "C"
        reasons = [
            "no_verified_cp_table",
            "no_verified_course_map",
            "route_text_or_aggregator_only",
        ]
        if has_route_text:
            reasons.append("route_text_available")
        if has_distance or has_gain or has_loss:
            reasons.append("aggregated_distance_or_elevation_available")

    explanation_map = {
        "A": "Official course map, elevation map, CP table, distance, climb, loss, and cutoff information are all present and officially confirmed.",
        "B": "Only partial CP or course map evidence is available, so the model must stay simplified.",
        "C": "Only route text and/or aggregate distance and elevation evidence are available, so CPs and splits cannot be invented.",
    }

    return {
        "grade": grade,
        "confidence": 1.0,
        "officially_confirmed": False,
        "source_kind": "derived",
        "reason_codes": reasons,
        "explanation": explanation_map[grade],
    }
