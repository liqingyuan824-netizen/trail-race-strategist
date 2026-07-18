"""Normalization helpers for runner readiness inputs and history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .specs import FIELD_SPECS, GENERATOR_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_source(raw_source: Mapping[str, Any] | None, default_source: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(default_source)
    if raw_source:
        source.update(raw_source)
    source.setdefault("source_uri", None)
    source.setdefault("source_type", "unknown")
    source.setdefault("captured_at", _utc_now())
    source.setdefault("is_user_self_report", False)
    source.setdefault("confidence", 0.5)
    return source


def normalize_record(
    field_name: str,
    raw_value: Any,
    *,
    default_source: Mapping[str, Any],
    sensitive: bool = False,
    note: str | None = None,
) -> dict[str, Any]:
    if isinstance(raw_value, Mapping) and ("value" in raw_value or "source" in raw_value):
        value = raw_value.get("value")
        source = _normalize_source(raw_value.get("source"), default_source)
        note = raw_value.get("note", note)
        raw_range = raw_value.get("raw_range")
    else:
        value = raw_value
        source = _normalize_source(None, default_source)
        raw_range = None
    return {
        "field": field_name,
        "value": value,
        "raw_range": raw_range,
        "source": source,
        "sensitive": sensitive,
        "confidence": float(source.get("confidence", 0.5)),
        "captured_at": source.get("captured_at"),
        "is_user_self_report": bool(source.get("is_user_self_report", False)),
        "source_type": source.get("source_type"),
        "source_uri": source.get("source_uri"),
        "note": note,
        "local_only": sensitive,
    }


def normalize_answers(answers: Mapping[str, Any]) -> dict[str, Any]:
    default_source = answers["default_source"]
    inputs = answers["inputs"]
    normalized_inputs: dict[str, dict[str, Any]] = {}
    for field_name, raw_value in inputs.items():
        spec = FIELD_SPECS.get(field_name)
        if spec is None:
            continue
        normalized_inputs[field_name] = normalize_record(
            field_name,
            raw_value,
            default_source=default_source,
            sensitive=bool(spec["sensitive"]),
        )
    return {
        "schema_name": "runner_readiness_input",
        "schema_version": answers["schema_version"],
        "generated_at": answers["generated_at"],
        "generator_version": answers["generator_version"],
        "mode": answers["mode"],
        "subject": dict(answers["subject"]),
        "default_source": dict(default_source),
        "inputs": normalized_inputs,
        "source_policy_version": answers.get("source_policy_version", "1.0.0"),
        "cache_policy_version": answers.get("cache_policy_version", "1.0.0"),
        "question_schema": answers.get("question_schema"),
        "raw_input_fingerprint": fingerprint(answers),
    }


def _recent_races(profile: Mapping[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    recent = []
    for item in profile.get("race_results", [])[:limit]:
        recent.append(
            {
                "date": item.get("date"),
                "race": item.get("race"),
                "distance_km": item.get("distance_km"),
                "elevation_gain_m": item.get("elevation_gain_m"),
                "race_time": item.get("race_time"),
                "race_score_access": item.get("race_score_access"),
                "race_score_raw_display": item.get("race_score_raw_display"),
                "source_url": item.get("race_url"),
            }
        )
    return recent


def normalize_runner_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    history_races = _recent_races(profile, limit=5)
    distances = [float(item["distance_km"]) for item in profile.get("race_results", []) if item.get("distance_km") is not None]
    elevations = [float(item["elevation_gain_m"]) for item in profile.get("race_results", []) if item.get("elevation_gain_m") is not None]
    latest_race_date = profile.get("race_results", [{}])[0].get("date") if profile.get("race_results") else None
    profile_source = profile.get("evidence", [None])[0]
    source_meta = {
        "source_type": "itra_public_runner",
        "source_uri": profile_source,
        "captured_at": profile.get("retrieved_at") or profile.get("generated_at"),
        "is_user_self_report": False,
        "confidence": 0.96,
    }
    historical_summary = {
        "general_pi": {
            "value": profile.get("performance", {}).get("general_pi"),
            "source": source_meta,
            "note": "Historical ITRA performance index. It must not be used as a substitute for current training state.",
        },
        "finished_races": {
            "value": profile.get("performance", {}).get("finished_races"),
            "source": source_meta,
        },
        "visible_race_count": {
            "value": len(profile.get("race_results", [])),
            "source": source_meta,
        },
        "latest_race_date": {
            "value": latest_race_date,
            "source": source_meta,
        },
        "visible_distance_range_km": {
            "value": {
                "min": min(distances) if distances else None,
                "max": max(distances) if distances else None,
            },
            "source": source_meta,
        },
        "visible_elevation_range_m": {
            "value": {
                "min": min(elevations) if elevations else None,
                "max": max(elevations) if elevations else None,
            },
            "source": source_meta,
        },
    }
    return {
        "schema_name": "runner_profile",
        "schema_version": profile["schema_version"],
        "generated_at": profile["generated_at"],
        "generator_version": profile["generator_version"],
        "source_policy_version": profile.get("source_policy_version", "1.0.0"),
        "cache_policy_version": profile.get("cache_policy_version", "1.0.0"),
        "safety_notice": profile["safety_notice"],
        "query": dict(profile["query"]),
        "identity": dict(profile["identity"]),
        "performance": dict(profile["performance"]),
        "race_results": list(profile.get("race_results", [])),
        "unavailable_fields": list(profile.get("unavailable_fields", [])),
        "warnings": list(profile.get("warnings", [])),
        "evidence": list(profile.get("evidence", [])),
        "diagnostics": dict(profile.get("diagnostics", {})),
        "historical_summary": historical_summary,
        "historical_races": history_races,
        "source_profile_fingerprint": fingerprint(profile),
        "notes": [
            "This artifact captures historical ability and stable experience only.",
            "General PI is retained as history and is not a current readiness proxy.",
        ],
    }
