"""Input validation for course model source bundles."""

from __future__ import annotations

from collections.abc import Mapping


class ValidationError(ValueError):
    """Raised when a race source bundle cannot be used for course modeling."""


REQUIRED_TOP_LEVEL_KEYS = {
    "schema_name",
    "schema_version",
    "generated_at",
    "generator_version",
    "safety_notice",
    "cache_key",
    "event",
    "sources",
    "diagnostics",
}

REQUIRED_EVENT_KEYS = {
    "official_name",
    "year",
    "group_code",
    "group_name",
    "route_version",
    "facts",
    "field_sources",
    "unavailable_fields",
    "warnings",
}

REQUIRED_FACT_KEYS = {
    "route_text",
    "course_map",
    "elevation_map",
    "cp",
    "support_rules",
    "mandatory_equipment",
    "free_supply",
    "private_supply_rule",
    "total_distance_km",
    "total_elevation_gain_m",
    "total_elevation_loss_m",
    "start_time",
    "cutoff_time",
    "cutoff_hours",
}


def validate_race_source_bundle(bundle: Mapping[str, object]) -> list[str]:
    """Return machine-readable validation errors for a race source bundle."""

    errors: list[str] = []
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in bundle:
            errors.append(f"missing_top_level:{key}")

    if bundle.get("schema_name") != "race_source_bundle":
        errors.append("schema_name:not_race_source_bundle")
    if bundle.get("schema_version") not in {"1.0.0", "2.0.0"}:
        errors.append("schema_version:unsupported")

    event = bundle.get("event")
    if not isinstance(event, Mapping):
        errors.append("event:not_mapping")
        return errors

    for key in REQUIRED_EVENT_KEYS:
        if key not in event:
            errors.append(f"missing_event:{key}")

    facts = event.get("facts")
    if not isinstance(facts, Mapping):
        errors.append("facts:not_mapping")
        return errors

    for key in REQUIRED_FACT_KEYS:
        if key not in facts:
            errors.append(f"missing_fact:{key}")

    sources = bundle.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources:empty_or_not_list")

    return errors


def validate_course_cp_sequence(bundle: Mapping[str, object]) -> list[str]:
    """Validate CP ordering before segmentation."""

    errors: list[str] = []
    event = bundle.get("event")
    if not isinstance(event, Mapping):
        return ["event:not_mapping"]
    facts = event.get("facts")
    if not isinstance(facts, Mapping):
        return ["facts:not_mapping"]

    cp = facts.get("cp") or []
    prev_distance_m: float | int | None = None
    prev_sequence: int | None = None

    for index, item in enumerate(cp):
        if not isinstance(item, Mapping):
            errors.append(f"cp:{index}:not_mapping")
            continue
        sequence = item.get("sequence")
        if sequence is not None:
            try:
                sequence = int(sequence)
            except (TypeError, ValueError):
                errors.append(f"cp:{index}:bad_sequence")
                sequence = None
        distance_m = item.get("distance_m")
        if distance_m is None and item.get("distance_km") is not None:
            try:
                distance_m = float(item["distance_km"]) * 1000
            except (TypeError, ValueError):
                distance_m = None
        if distance_m is None:
            errors.append(f"cp:{index}:missing_distance")
            continue

        if prev_distance_m is not None and float(distance_m) <= float(prev_distance_m):
            errors.append(f"cp:{index}:distance_not_strictly_increasing")
        if sequence is not None and prev_sequence is not None and sequence <= prev_sequence:
            errors.append(f"cp:{index}:sequence_not_strictly_increasing")

        prev_distance_m = float(distance_m)
        if sequence is not None:
            prev_sequence = sequence

    return errors
