"""Fixed synthetic Phase 10 inputs."""

from __future__ import annotations

from typing import Any


def unknown_support_inputs() -> dict[str, Any]:
    return {
        "schema_name": "race_support_inputs",
        "schema_version": "1.0.0",
        "intake_targets": {
            "carbohydrate_g_per_hour": None,
            "fluid_ml_per_hour": None,
            "electrolyte_mg_per_hour": None,
        },
        "verified_foods": [],
        "carrying_capacity": None,
        "mandatory_equipment": None,
        "temperature_tolerance": {"lowest_temperature_c": None, "status": "unknown_not_guessed"},
        "runner_confirmation": "unknown_fields_intentionally_not_requested",
    }


def verified_support_inputs() -> dict[str, Any]:
    result = unknown_support_inputs()
    result["intake_targets"] = {
        "carbohydrate_g_per_hour": {
            "minimum": 45,
            "maximum": 60,
            "unit": "g/hour",
            "verified_in_training": True,
            "evidence_reference": "synthetic://training-log",
        },
        "fluid_ml_per_hour": {
            "minimum": 350,
            "maximum": 550,
            "unit": "ml/hour",
            "verified_in_training": True,
            "evidence_reference": "synthetic://training-log",
        },
        "electrolyte_mg_per_hour": None,
    }
    result["verified_foods"] = [
        {"label": "synthetic tolerated item", "verified_in_training": True, "evidence_reference": "synthetic://training-log"},
        {"label": "unverified item", "verified_in_training": False},
    ]
    result["carrying_capacity"] = {"fluid_ml": 1000, "status": "synthetic_verified_fixture"}
    return result
