"""Synthetic Phase 12 events."""

from __future__ import annotations

from typing import Any


def event(*, event_id: str, event_type: str = "checkpoint", source_type: str = "official_timing", observed_at: str = "2026-09-12T10:00:00+08:00", received_at: str = "2026-09-12T10:03:00+08:00", confidence: float = 0.98, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"event_id": event_id, "event_type": event_type, "observed_at": observed_at, "received_at": received_at, "source": {"source_type": source_type, "source_reference": f"synthetic://{source_type}"}, "confidence": confidence, "payload": payload or {"checkpoint_sequence": 2, "elapsed_minutes": 240, "timing_kind": "entry"}}
