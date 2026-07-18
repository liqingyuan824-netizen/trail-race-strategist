"""Adapter that creates a Phase 9 input from the frozen distance-only ablation.

This does not modify or tune Phase 8A. It calls the already-frozen distance-only
implementation and strips runner identity from the downstream artifact.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from baseline_backtest.pipeline import _history_rows, _predict_with_variant


def build_internal_distance_only_baseline(
    *,
    runner_profile: Mapping[str, Any],
    target_date: str,
    target_distance_km: float,
    target_elevation_gain_m: float,
    source_reference: str,
) -> dict[str, Any]:
    target_dt = datetime.fromisoformat(target_date.replace("Z", "+00:00"))
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
    target = {
        "date": target_date[:10],
        "date_dt": target_dt,
        "race_name": "anonymous_future_target",
        "distance_km": float(target_distance_km),
        "elevation_gain_m": float(target_elevation_gain_m),
    }
    rows = [row for row in _history_rows(runner_profile) if row.get("race_time_minutes") is not None]
    prediction = _predict_with_variant(target=target, prior_rows=rows, variant="distance_only")
    if prediction.get("prediction_minutes") is None:
        raise ValueError("distance_only_baseline_unavailable")
    optimistic = prediction["intervals"]["optimistic"]
    conservative = prediction["intervals"]["conservative"]
    midpoint = float(prediction["prediction_minutes"])
    return {
        "schema_name": "internal_distance_only_baseline",
        "schema_version": "1.0.0",
        "model_id": "distance_only",
        "selection_decision": "retain_distance_only",
        "prediction_scope": "internal_research_only",
        "user_facing_prediction_allowed": False,
        "calibrated": False,
        "finish_range_minutes": {
            "lower_minutes": float(optimistic["lower_minutes"]),
            "midpoint_minutes": midpoint,
            "upper_minutes": float(conservative["upper_minutes"]),
        },
        "source_reference": source_reference,
        "formula_reference": "baseline_backtest.pipeline._predict_with_variant(variant=distance_only)",
        "source_history_count": len(rows),
        "identity_fields_included": False,
        "notes": [
            "Lower and upper bounds use the frozen optimistic-lower and conservative-upper distance-only intervals.",
            "This adapter does not use target actual time, validation error, or holdout data.",
        ],
    }

