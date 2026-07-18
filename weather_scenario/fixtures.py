"""Fixed synthetic Phase 11 event and weather evidence."""

from __future__ import annotations

from typing import Any


def synthetic_event(*, start_time: str = "2026-11-07T09:00:00+08:00", route_version: str | None = "route-v1") -> dict[str, Any]:
    return {
        "event_reference": "synthetic-event",
        "start_time": start_time,
        "location": "Synthetic Mountain, CN",
        "timezone": "Asia/Shanghai",
        "route_version": route_version,
    }


def observation(
    *,
    layer: str,
    issued_at: str,
    values: dict[str, Any] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    route_version: str | None = "route-v1",
    source_status: str = "available",
) -> dict[str, Any]:
    return {
        "layer": layer,
        "issued_at": issued_at,
        "valid_window": None,
        "location": "Synthetic Mountain, CN",
        "timezone": "Asia/Shanghai",
        "route_version": route_version,
        "source_status": source_status,
        "source": {
            "source_kind": "official_synthetic_fixture",
            "source_uri": f"synthetic://weather/{layer}",
            "retrieved_at": issued_at,
            "source_fingerprint": f"fixture-{layer}",
        },
        "cache_key": f"weather:{layer}:synthetic-event:{route_version}",
        "values": values or {"temperature_c": 18, "precipitation_mm": 0, "wind_kph": 8},
        "alerts": alerts or [],
    }
