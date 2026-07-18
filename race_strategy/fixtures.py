"""Fixed synthetic inputs used for Phase 9 forward and failure tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .constants import CACHE_POLICY_VERSION, GENERATOR_VERSION, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION


def synthetic_course(*, label: str, distance_km: float, gain_m: float, cp_count: int, cutoff_hours: float, grade: str = "A") -> dict[str, Any]:
    start = datetime.fromisoformat("2026-09-12T06:00:00+08:00")
    cp_points = []
    for index in range(cp_count):
        fraction = index / (cp_count - 1)
        cp_points.append(
            {
                "sequence": index + 1,
                "name": "Start" if index == 0 else ("Finish" if index == cp_count - 1 else f"CP{index}"),
                "role": "start" if index == 0 else ("finish" if index == cp_count - 1 else "checkpoint"),
                "distance_km": round(distance_km * fraction, 3),
                "cumulative_gain_m": round(gain_m * fraction),
                "timing_window": {"fastest": None, "slowest": None, "cutoff": None},
                "officially_confirmed": True,
                "evidence_tier": "current_year_official",
                "source_year": 2026,
                "applicable_group": label,
                "source_kind": "official_cp_table",
            }
        )
    return {
        "schema_name": "course_model",
        "schema_version": "1.0.0",
        "generated_at": start.isoformat(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "event": {
            "official_name": f"Synthetic {label}",
            "year": 2026,
            "group_code": label,
            "group_name": label,
            "grade": {"grade": grade},
            "target_group_capture": {
                "schema_version": "1.0.0",
                "capture_attempt_status": "completed",
                "captured_at": start.isoformat(),
                "identity_binding": {
                    "status": "verified", "official_name": f"Synthetic {label}", "year": 2026,
                    "group_code": label, "group_name": label, "route_version": None,
                },
                "official_source_count": 1,
                "successful_official_source_count": 1,
                "detail_checks": {
                    "course_map": {"status": "verified", "value_present": True},
                    "elevation_map": {"status": "verified", "value_present": True},
                    "cp": {"status": "verified", "value_present": True},
                    "start_time": {"status": "verified", "value_present": True},
                    "cutoff_time": {"status": "verified", "value_present": True},
                },
                "publication_conclusion": "not_asserted",
                "next_action": "capture_complete_for_current_fields",
            },
            "course": {
                "total_distance_km": {"value": distance_km},
                "total_elevation_gain_m": {"value": gain_m},
                "start_time": {"value": start.isoformat()},
                "cutoff_time": {"value": (start + timedelta(hours=cutoff_hours)).isoformat()},
                "cp_model": {
                    "status": "complete" if grade in {"A", "B"} else "not_generated",
                    "cp_points": cp_points if grade in {"A", "B"} else [],
                    "cp_count": len(cp_points) if grade in {"A", "B"} else 0,
                },
            },
        },
    }


def synthetic_readiness(*, risk_level: str = "green", permission: str = "normal_planning_allowed") -> dict[str, Any]:
    return {
        "schema_name": "current_readiness",
        "schema_version": "1.0.0",
        "generated_at": "2026-09-01T00:00:00+08:00",
        "generator_version": GENERATOR_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "subject": {"runner_reference": "SYNTHETIC", "synthetic_fixture": True},
        "assessment": {
            "risk_level": risk_level,
            "planning_permission": permission,
            "red_flags": ["synthetic_red_flag"] if risk_level == "red" else [],
            "yellow_flags": ["synthetic_yellow_flag"] if risk_level == "yellow" else [],
        },
        "unavailable_fields": ["carb_intake_per_hour_g", "hydration_rate_ml_per_hour", "lowest_temperature_c"],
        "privacy_mode": "private_alias",
    }


def synthetic_baseline(*, midpoint_minutes: float) -> dict[str, Any]:
    return {
        "schema_name": "internal_distance_only_baseline",
        "schema_version": SCHEMA_VERSION,
        "model_id": "distance_only",
        "selection_decision": "retain_distance_only",
        "prediction_scope": "synthetic_internal_test",
        "user_facing_prediction_allowed": False,
        "calibrated": False,
        "finish_range_minutes": {
            "lower_minutes": round(midpoint_minutes * 0.88, 2),
            "midpoint_minutes": midpoint_minutes,
            "upper_minutes": round(midpoint_minutes * 1.18, 2),
        },
        "source_reference": "synthetic://distance-only-baseline",
        "formula_reference": "fixed_synthetic_fixture",
    }
