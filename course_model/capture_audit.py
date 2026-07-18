"""Carry an auditable target-group capture receipt into a course model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DETAIL_FIELDS = ("course_map", "elevation_map", "cp", "start_time", "cutoff_time")


def build_target_group_capture(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Summarise what was actually captured for the selected race group.

    This receipt deliberately distinguishes a completed capture from a claim
    that the organiser has not published a detail.  An absent field is only
    "checked_not_confirmed" until a separately captured official publication
    notice supports a stronger conclusion.
    """

    event = bundle["event"]
    supplied = event.get("target_group_capture")
    if isinstance(supplied, Mapping) and supplied.get("schema_version") == "2.0.0":
        # A v2 receipt is authoritative because it records every required
        # search lane, attachment state, and request binding. Preserve it.
        return dict(supplied)
    facts = event.get("facts", {})
    field_sources = event.get("field_sources", {})
    sources = list(bundle.get("sources", []))
    official_sources = [source for source in sources if source.get("source_kind") == "official"]
    official_ok = [source for source in official_sources if source.get("capture_status") == "ok"]
    retrieved_at = [source.get("retrieved_at") for source in official_ok if source.get("retrieved_at")]

    def official_field_present(field: str) -> bool:
        if facts.get(field) in (None, [], ""):
            return False
        # Maps and CP rows are parsed directly from the official capture in
        # this source-bundle schema; scalar timing fields need their explicit
        # provenance checked because they may originate from an aggregator.
        if field in {"course_map", "elevation_map", "cp"}:
            return bool(official_ok)
        return any(source.get("source_kind") == "official" for source in field_sources.get(field, []))

    detail_checks = {
        field: {
            "status": "verified" if official_field_present(field) else "checked_not_confirmed",
            "value_present": facts.get(field) not in (None, [], ""),
            "officially_confirmed": official_field_present(field),
        }
        for field in DETAIL_FIELDS
    }
    identity_verified = bool(
        official_ok and event.get("official_name") and event.get("year")
        and event.get("group_code") and event.get("group_name")
    )
    return {
        "schema_version": "1.0.0",
        "capture_attempt_status": "completed" if official_ok else "not_completed",
        "captured_at": max(retrieved_at) if retrieved_at else None,
        "identity_binding": {
            "status": "verified" if identity_verified else "not_verified",
            "official_name": event.get("official_name"),
            "year": event.get("year"),
            "group_code": event.get("group_code"),
            "group_name": event.get("group_name"),
            "route_version": event.get("route_version"),
        },
        "official_source_count": len(official_sources),
        "successful_official_source_count": len(official_ok),
        "detail_checks": detail_checks,
        "publication_conclusion": "not_asserted",
        "publication_conclusion_rule": (
            "Do not call a missing detail unpublished. That conclusion requires a separately captured "
            "official publication notice bound to this event year and group."
        ),
        "next_action": (
            "capture_more_official_group_material" if not official_ok or any(
                check["status"] != "verified" for check in detail_checks.values()
            ) else "capture_complete_for_current_fields"
        ),
    }
