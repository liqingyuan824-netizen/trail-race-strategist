"""Validation helpers for Phase 8A baseline backtest."""

from __future__ import annotations

from collections.abc import Mapping


class ValidationError(ValueError):
    """Raised when a backtest input cannot be processed."""


REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "race_results",
    "performance",
    "identity",
}


def validate_backtest_inputs(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in payload:
            errors.append(f"missing_top_level:{key}")

    schema_name = payload.get("schema_name")
    if schema_name is not None and schema_name != "runner_profile":
        errors.append("schema_name:not_runner_profile")
    if payload.get("schema_version") != "1.0.0":
        errors.append("schema_version:unsupported")

    race_results = payload.get("race_results")
    if not isinstance(race_results, list):
        errors.append("race_results:not_list")
    else:
        for index, row in enumerate(race_results):
            if not isinstance(row, Mapping):
                errors.append(f"race_results[{index}]:not_mapping")
                continue
            for key in ("date", "race", "distance_km", "elevation_gain_m"):
                if key not in row:
                    errors.append(f"race_results[{index}]:missing_{key}")

    return errors
