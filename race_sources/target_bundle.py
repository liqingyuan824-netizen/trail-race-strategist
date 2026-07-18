"""Build a generic target-year/group race bundle from captured evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping, Sequence

from .constants import CACHE_POLICY_VERSION, SAFETY_NOTICE, SOURCE_POLICY_VERSION


SCALAR_FIELDS = (
    "route_text", "total_distance_km", "total_elevation_gain_m", "total_elevation_loss_m",
    "start_time", "cutoff_time", "cutoff_hours",
)


def _source_kind(row: Mapping[str, Any]) -> str:
    tier = row.get("source_tier")
    if tier in {"current_year_official", "official_current_year"}:
        return "official"
    if tier == "official_historical_reference":
        return "official_historical_reference"
    return str(row.get("source_kind") or "third_party_aggregator")


def _normalize_source(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_path = row.get("raw_path")
    return {
        "source_id": row.get("source_id"),
        "source_kind": _source_kind(row),
        "source_url": row.get("url", row.get("source_url")),
        "final_url": row.get("final_url"),
        "retrieved_at": row.get("retrieved_at"),
        "evidence_paths": {"raw": raw_path, "html": raw_path},
        "sha256": row.get("sha256"),
        "capture_status": "ok" if row.get("capture_status") == "acquired" else row.get("capture_status"),
        "error_code": row.get("error_code"),
        "content_type": row.get("content_type"),
        "applicable_year": row.get("applicable_year"),
        "applicable_group": row.get("applicable_group"),
        "parse_status": row.get("parse_status"),
        "visual_evidence": list(row.get("visual_evidence") or []),
        "visual_attempts": list(row.get("visual_attempts") or []),
        "visual_selection": dict(row.get("visual_selection") or {}),
    }


def build_target_race_bundle(
    *,
    request_binding: Mapping[str, Any],
    event: Mapping[str, Any],
    receipt: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    facts: Mapping[str, Any],
    cp_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build v2 evidence while preserving current-year vs historical semantics."""

    request_id = request_binding.get("request_id")
    if not request_id or receipt.get("request_id") != request_id:
        raise ValueError("REQUEST_ID_MISMATCH_RACE_RECEIPT")
    binding = receipt.get("identity_binding", {})
    for field in ("official_name", "year", "group_code", "group_name"):
        if binding.get(field) != event.get(field):
            raise ValueError("TARGET_GROUP_RECEIPT_BINDING_MISMATCH")
    normalized_sources = [_normalize_source(row) for row in sources]
    if not normalized_sources:
        raise ValueError("AT_LEAST_ONE_CAPTURED_SOURCE_REQUIRED")
    source_lookup = {row["source_id"]: row for row in normalized_sources}
    identity_source = next((row for row in normalized_sources if row["source_kind"] == "official" and row["capture_status"] == "ok"), None)
    if identity_source is None:
        raise ValueError("CURRENT_YEAR_OFFICIAL_IDENTITY_SOURCE_REQUIRED")
    identity_id = identity_source["source_id"]

    normalized_cp: list[dict[str, Any]] = []
    for row in cp_rows:
        item = dict(row)
        tier = item.get("evidence_tier")
        source_year = item.get("source_year")
        if tier == "current_year_official" and source_year != event.get("year"):
            raise ValueError("CURRENT_YEAR_CP_SOURCE_YEAR_MISMATCH")
        if tier == "official_historical_reference" and source_year == event.get("year"):
            raise ValueError("HISTORICAL_CP_CANNOT_USE_TARGET_YEAR")
        if item.get("applicable_group") not in {event.get("group_code"), event.get("group_name")}:
            raise ValueError("CP_GROUP_BINDING_MISMATCH")
        if item.get("source_kind") in {"official_visual_transcription", "official_roadbook_visual_transcription"}:
            transcription = item.get("visual_transcription")
            required = ("source_url", "retrieved_at", "raw_sha256", "applicable_year", "applicable_group", "parser_method")
            if not isinstance(transcription, Mapping) or not all(transcription.get(key) for key in required):
                raise ValueError("VISUAL_CP_TRANSCRIPTION_PROVENANCE_REQUIRED")
            if transcription.get("applicable_year") != event.get("year") or transcription.get("applicable_group") not in {event.get("group_code"), event.get("group_name")}:
                raise ValueError("VISUAL_CP_TRANSCRIPTION_BINDING_MISMATCH")
        item["applicable_year"] = event.get("year")
        item["current_year_applicability"] = "confirmed" if tier == "current_year_official" else "reference_only_unconfirmed"
        item["officially_confirmed"] = tier == "current_year_official"
        normalized_cp.append(item)

    merged_facts = {
        "official_name": event.get("official_name"), "year": event.get("year"),
        "group_code": event.get("group_code"), "group_name": event.get("group_name"),
        "route_version": event.get("route_version"), "route_text": facts.get("route_text"),
        "course_map": facts.get("course_map"), "elevation_map": facts.get("elevation_map"),
        "cp": normalized_cp, "total_distance_km": facts.get("total_distance_km"),
        "total_elevation_gain_m": facts.get("total_elevation_gain_m"),
        "total_elevation_loss_m": facts.get("total_elevation_loss_m"),
        "start_time": facts.get("start_time"), "cutoff_time": facts.get("cutoff_time"),
        "cutoff_hours": facts.get("cutoff_hours"),
        "support_rules": facts.get("support_rules"),
        "mandatory_equipment": facts.get("mandatory_equipment"),
        "free_supply": facts.get("free_supply"),
        "private_supply_rule": facts.get("private_supply_rule"),
    }
    field_source_ids = dict(facts.get("field_source_ids") or {})
    field_sources: dict[str, list[dict[str, Any]]] = {}
    for field in ("official_name", "year", "group_code", "group_name"):
        field_sources[field] = [{"source_id": identity_id, "source_kind": "official"}]
    for field in ("route_version", *SCALAR_FIELDS, "course_map", "elevation_map", "cp"):
        source_id = field_source_ids.get(field, identity_id)
        if source_id not in source_lookup:
            raise ValueError(f"UNKNOWN_FIELD_SOURCE:{field}:{source_id}")
        field_sources[field] = [{"source_id": source_id, "source_kind": source_lookup[source_id]["source_kind"]}]

    unavailable = [name for name in ("course_map", "elevation_map", "cp") if merged_facts.get(name) in (None, [], "")]
    generated_at = datetime.now(timezone.utc).isoformat()
    cache_material = "|".join(str(row.get("sha256") or row.get("error_code")) for row in normalized_sources)
    return {
        "schema_name": "race_source_bundle", "schema_version": "2.0.0", "generated_at": generated_at,
        "generator_version": "0.2.0", "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION, "safety_notice": SAFETY_NOTICE,
        "request_binding": dict(request_binding),
        "cache_key": f"race_source_bundle|{event.get('year')}|{event.get('group_code')}|{sha256(cache_material.encode()).hexdigest()}",
        "event": {
            **{key: event.get(key) for key in ("official_name", "year", "group_code", "group_name", "route_version")},
            "route_version_note": event.get("route_version_note"), "facts": merged_facts,
            "field_sources": field_sources, "unavailable_fields": unavailable,
            "warnings": list(facts.get("warnings") or []), "target_group_capture": dict(receipt),
            "visual_evidence": list(facts.get("visual_evidence") or facts.get("wechat_visual_evidence") or []),
            "visual_evidence_attempts": list(facts.get("visual_evidence_attempts") or facts.get("wechat_visual_attempts") or []),
            "visual_selection": dict(facts.get("visual_selection") or {}),
        },
        "sources": normalized_sources,
        "diagnostics": {"source_count": len(normalized_sources), "cp_row_count": len(normalized_cp), "partial_reasons": unavailable},
    }
