"""Synthetic fixtures only; never derived from validation or holdout."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any


def target_fixture(*, distance_km: float = 52.0, gain_m: float = 2600.0) -> dict[str, Any]:
    return {
        "target_runner_id": "synthetic_target_runner",
        "target_race_id": f"synthetic_target_{int(distance_km)}k_2027",
        "event_series_id": f"synthetic_series_{int(distance_km)}k",
        "prediction_as_of": "2026-07-14T00:00:00+00:00",
        "race_date": "2027-05-01T00:00:00+00:00",
        "distance_km": distance_km,
        "elevation_gain_m": gain_m,
        "technical_score": 0.65,
        "route_version": "v1",
    }


def baseline_fixture(midpoint: float) -> dict[str, Any]:
    return {
        "schema_name": "internal_distance_only_baseline",
        "schema_version": "1.0.0",
        "model_id": "distance_only",
        "selection_decision": "retain_distance_only",
        "user_facing_prediction_allowed": False,
        "calibrated": False,
        "finish_range_minutes": {"lower_minutes": midpoint * 0.88, "midpoint_minutes": midpoint, "upper_minutes": midpoint * 1.18},
        "formula_reference": "synthetic_distance_only_fixture",
    }


def _source(record_id: str) -> dict[str, Any]:
    return {
        "source_type": "synthetic_fixture",
        "source_uri": f"local://synthetic/{record_id}",
        "source_fingerprint": hashlib.sha256(record_id.encode()).hexdigest(),
        "captured_at": "2026-07-13T00:00:00+00:00",
        "confidence": 0.92,
        "immutable": True,
    }


def _record(record_id: str, runner_id: str, race_id: str, series: str, date: str, distance: float, gain: float, minutes: float, role: str = "peer") -> dict[str, Any]:
    return {
        "record_id": record_id,
        "runner_id": runner_id,
        "runner_role": role,
        "race_id": race_id,
        "event_series_id": series,
        "race_date": date,
        "group_id": "open",
        "available_at": date,
        "distance_km": distance,
        "elevation_gain_m": gain,
        "technical_score": 0.62,
        "finish_time_minutes": minutes,
        "result_status": "finish",
        "route_version": "v1",
        "split": "synthetic",
        "authorized_for_internal_research": True,
        "source": _source(record_id),
    }


def records_fixture(*, conflict: bool = False, include_references: bool = True) -> list[dict[str, Any]]:
    target = "synthetic_target_runner"
    rows = [
        _record("syn_self_same", target, "syn_target_old", "synthetic_series_52k", "2025-05-01", 51, 2500, 600 if not conflict else 980),
        _record("syn_self_other", target, "syn_bridge_race", "synthetic_bridge_series", "2026-03-01", 32, 1400, 315),
    ]
    if not include_references:
        return []
    rows.extend([
        _record("syn_peer_bridge", "synthetic_peer_runner", "syn_bridge_race", "synthetic_bridge_series", "2026-03-01", 32, 1400, 300),
        _record("syn_peer_projection", "synthetic_peer_runner", "syn_peer_50k", "synthetic_peer_series", "2025-10-01", 50, 2400, 550),
        _record("syn_elite", "synthetic_elite_runner", "syn_elite_55k", "synthetic_elite_series", "2025-11-01", 55, 2700, 320, "elite_anchor"),
    ])
    return deepcopy(rows)
