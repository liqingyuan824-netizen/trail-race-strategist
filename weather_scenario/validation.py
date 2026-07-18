"""Validation for Phase 11 weather evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .constants import LAYER_POLICY


class WeatherValidationError(ValueError):
    """Raised when weather evidence cannot be interpreted safely."""


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_inputs(*, event: Mapping[str, Any], observations: list[Mapping[str, Any]], as_of: str) -> list[str]:
    errors: list[str] = []
    event_time = parse_datetime(event.get("start_time"))
    as_of_time = parse_datetime(as_of)
    if event_time is None or event_time.tzinfo is None:
        errors.append("timezone_aware_event_start_required")
    if as_of_time is None or as_of_time.tzinfo is None:
        errors.append("timezone_aware_as_of_required")
    if not event.get("location"):
        errors.append("event_location_required")
    if not event.get("timezone"):
        errors.append("event_timezone_required")
    seen_layers: set[str] = set()
    for index, item in enumerate(observations):
        layer = item.get("layer")
        if layer not in LAYER_POLICY:
            errors.append(f"observation_{index}_invalid_layer")
        elif layer in seen_layers:
            errors.append(f"observation_{index}_duplicate_layer")
        else:
            seen_layers.add(str(layer))
        if item.get("source_status") not in {"available", "blocked", "not_found", "page_changed"}:
            errors.append(f"observation_{index}_invalid_source_status")
        if item.get("source_status") == "available":
            if parse_datetime(item.get("issued_at")) is None:
                errors.append(f"observation_{index}_issued_at_required")
            source = item.get("source")
            if not isinstance(source, Mapping) or not source.get("source_uri") or not source.get("source_kind"):
                errors.append(f"observation_{index}_source_required")
            elif not source.get("source_fingerprint"):
                errors.append(f"observation_{index}_source_fingerprint_required")
            if not item.get("cache_key"):
                errors.append(f"observation_{index}_cache_key_required")
    return errors
