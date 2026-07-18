"""Build four-layer weather evidence and scenario controls without inventing forecasts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import CACHE_POLICY_VERSION, GENERATOR_VERSION, LAYER_POLICY, SAFETY_NOTICE, SCENARIO_LIBRARY, SCHEMA_VERSION, SOURCE_POLICY_VERSION
from .report import build_markdown_report
from .validation import WeatherValidationError, parse_datetime, validate_inputs
from reporting_contract import apply_output_contract


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowed_layer(layer: str, hours_before_event: float) -> bool:
    max_hours = LAYER_POLICY[layer]["max_hours_before_event"]
    return max_hours is None or 0 <= hours_before_event <= max_hours


def _phase(hours_before_event: float) -> str:
    if hours_before_event > 24 * 14:
        return "far_future_climate_scenarios_only"
    if hours_before_event > 72:
        return "trend_window"
    if hours_before_event > 24:
        return "within_72_hours"
    return "race_day"


def _layer_result(layer: str, item: Mapping[str, Any] | None, *, as_of_time: datetime, hours_before_event: float, event: Mapping[str, Any]) -> dict[str, Any]:
    allowed = _allowed_layer(layer, hours_before_event)
    if not allowed:
        return {
            "status": "not_allowed_at_current_horizon",
            "freshness_status": "not_applicable",
            "values": None,
            "source": None,
            "cache_valid": False,
            "reason": "forecast_horizon_not_reached",
        }
    if item is None:
        return {
            "status": "not_yet_available",
            "freshness_status": "unknown",
            "values": None,
            "source": None,
            "cache_valid": False,
            "reason": "no_verified_source_capture",
        }
    if item.get("source_status") != "available":
        return {
            "status": f"source_{item.get('source_status')}",
            "freshness_status": "unavailable",
            "values": None,
            "source": item.get("source"),
            "cache_valid": False,
            "reason": item.get("access_boundary_note") or "source_not_available",
        }
    issued_at = parse_datetime(item.get("issued_at"))
    age_hours = (as_of_time - issued_at).total_seconds() / 3600.0 if issued_at else None
    fresh = age_hours is not None and 0 <= age_hours <= LAYER_POLICY[layer]["freshness_hours"]
    route_version = event.get("route_version")
    route_matches = item.get("route_version") in (None, route_version) or route_version is None
    query_matches = item.get("location") == event.get("location") and item.get("timezone") == event.get("timezone")
    valid = fresh and route_matches and query_matches
    return {
        "status": "usable" if valid else "stale_or_invalidated",
        "freshness_status": "fresh" if fresh else "stale",
        "issued_at": item.get("issued_at"),
        "valid_window": item.get("valid_window"),
        "location": item.get("location"),
        "timezone": item.get("timezone"),
        "values": deepcopy(item.get("values")) if valid else None,
        "alerts": deepcopy(item.get("alerts", [])) if valid else [],
        "source": deepcopy(item.get("source")),
        "route_version": item.get("route_version"),
        "cache_key": item.get("cache_key"),
        "cache_valid": valid,
        "invalidation_reasons": (["stale"] if not fresh else []) + (["route_version_changed"] if not route_matches else []) + (["query_identity_changed"] if not query_matches else []),
    }


def build_weather_scenarios(
    *,
    event: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    as_of: str,
    case_reference: str = "anonymous_internal_case",
) -> dict[str, Any]:
    errors = validate_inputs(event=event, observations=observations, as_of=as_of)
    if errors:
        raise WeatherValidationError("; ".join(errors))
    event_time = parse_datetime(event["start_time"])
    as_of_time = parse_datetime(as_of)
    assert event_time is not None and as_of_time is not None
    hours_before = (event_time - as_of_time).total_seconds() / 3600.0
    if hours_before < 0:
        raise WeatherValidationError("as_of_after_event_start_not_supported_in_phase11")
    by_layer: dict[str, Mapping[str, Any]] = {}
    for item in observations:
        by_layer[item["layer"]] = item
    layers = {
        name: _layer_result(name, by_layer.get(name), as_of_time=as_of_time, hours_before_event=hours_before, event=event)
        for name in LAYER_POLICY
    }
    usable = [name for name, value in layers.items() if value["status"] == "usable"]
    active_layer = usable[-1] if usable else None
    alerts = [alert for value in layers.values() for alert in value.get("alerts", [])]
    red_alerts = [item for item in alerts if item.get("severity") == "red"]
    scenario_rows = []
    for scenario_id, template in SCENARIO_LIBRARY.items():
        row = {"scenario_id": scenario_id, **deepcopy(template)}
        row["is_forecast"] = False
        row["applicability"] = "contingency_only" if active_layer is None else "compare_with_active_verified_layer"
        scenario_rows.append(row)
    return {
        "schema_name": "weather_scenarios",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "case_reference": case_reference,
        "privacy": {"identity_included": False, "local_internal_validation_only": True},
        "governance": {
            "phase8a_validation_decision": "retain_distance_only",
            "selected_model": "distance_only",
            "full_model_status": "rejected",
            "holdout_evaluation_run": False,
            "user_facing_prediction_allowed": False,
            "output_scope": "internal_research_weather_validation_only",
        },
        "event": {
            "event_reference": event.get("event_reference"),
            "start_time": event["start_time"],
            "location": event["location"],
            "timezone": event["timezone"],
            "route_version": event.get("route_version"),
        },
        "as_of": as_of,
        "hours_before_event": round(hours_before, 3),
        "forecast_phase": _phase(hours_before),
        "active_layer": active_layer,
        "layers": layers,
        "scenarios": scenario_rows,
        "strategy_constraints": {
            "stop_aggressive_targets": bool(red_alerts),
            "stop_all_performance_targets": bool(red_alerts),
            "red_alerts": red_alerts,
            "official_safety_instructions_take_priority": True,
        },
        "cache_policy": {
            "reuse_requires_source_fingerprint_query_identity_route_and_schema_match": True,
            "route_change_invalidates_cache": True,
            "stale_values_excluded": True,
        },
        "warnings": [
            "Climate baselines and contingency scenarios are not race-day forecasts.",
            "A 72-hour forecast is absent until that horizon is reached and a fresh verified source is captured.",
            "Blocked, stale, or route-mismatched sources never contribute values.",
        ],
        "diagnostics": {
            "observation_count": len(observations),
            "usable_layer_count": len(usable),
            "red_alert_count": len(red_alerts),
        },
    }


def replay_weather_scenarios(*, event_path: Path, observations_path: Path, as_of: str, case_reference: str) -> dict[str, Any]:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    return build_weather_scenarios(event=event, observations=observations, as_of=as_of, case_reference=case_reference)


def write_weather_scenarios(bundle: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    artifact = apply_output_contract(bundle, report_type="planning_preparation", workflow_stage="phase11", report_status=str(bundle.get("forecast_phase")))
    (output_dir / "weather_scenarios.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "weather_scenarios.md").write_text(build_markdown_report(artifact), encoding="utf-8")
