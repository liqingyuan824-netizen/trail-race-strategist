"""Synthetic Phase 13 result and condition fixtures."""

from __future__ import annotations

from typing import Any


def actual_result(*, status: str = "finish", finish_minutes: float | None = 600, checkpoint_count: int = 6) -> dict[str, Any]:
    rows = [{"sequence": index + 1, "checkpoint_reference": f"CP-{index + 1}", "elapsed_minutes": round((finish_minutes or 600) * index / (checkpoint_count - 1), 2), "source_type": "official_timing"} for index in range(checkpoint_count)]
    return {"schema_name": "actual_race_result", "schema_version": "1.0.0", "result_status": status, "finish_time_minutes": finish_minutes if status == "finish" else None, "moving_time_minutes": 560 if status == "finish" else None, "stopped_time_minutes": 40 if status == "finish" else None, "checkpoints": rows if status != "dns" else [], "source": {"source_type": "synthetic", "source_reference": "synthetic://result"}}


def conditions() -> dict[str, Any]:
    return {"schema_name": "post_race_conditions", "schema_version": "1.0.0", "weather": {"status": "participant_report", "summary": "rain"}, "surface": {"status": "participant_report", "summary": "mud"}, "fueling": None, "equipment": None, "private_support": None}
