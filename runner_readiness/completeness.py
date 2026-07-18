"""Completeness assessment for runner readiness inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .specs import FIELD_SPECS, FORMAL_FIELDS, FORMAL_RECOMMENDED_FIELDS, FORMAL_INPUT_FIELDS, QUICK_FIELDS


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def assess_completeness(
    mode: str,
    normalized_inputs: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    assessed_fields = QUICK_FIELDS if mode == "quick" else FORMAL_INPUT_FIELDS
    required_fields = QUICK_FIELDS if mode == "quick" else FORMAL_FIELDS
    recommended_fields = FORMAL_RECOMMENDED_FIELDS if mode == "formal" else []
    missing: list[dict[str, Any]] = []
    filled_count = 0

    history_races = profile.get("race_results", [])
    history_can_cover_representative_races = len(history_races) >= 2

    assessed_field_names = set(assessed_fields)
    required_field_names = set(required_fields)
    recommended_field_names = set(recommended_fields)

    for field_name in assessed_fields:
        record = normalized_inputs.get(field_name)
        if field_name == "representative_races" and history_can_cover_representative_races:
            filled_count += 1
            continue
        if field_name == "red_flag_symptoms" and record is not None and record.get("value") is not None:
            filled_count += 1
            continue
        if record is None or _is_empty(record.get("value")):
            spec = FIELD_SPECS[field_name]
            missing.append(
                {
                    "field": field_name,
                    "label": spec["label"],
                    "priority": spec["priority"],
                    "required": field_name in required_field_names,
                    "recommended": field_name in recommended_field_names,
                    "reason": "required_field_missing" if field_name in required_field_names else "recommended_field_missing",
                    "sensitive": bool(spec["sensitive"]),
                    "local_only": bool(spec["sensitive"]),
                    "question_prompt": spec["prompt_quick"] if mode == "quick" else spec["prompt_formal"],
                }
            )
        else:
            filled_count += 1

    priority_order = {"high": 0, "medium": 1, "low": 2}
    missing.sort(key=lambda item: (priority_order.get(item["priority"], 99), item["field"]))
    required_missing_count = sum(1 for item in missing if item["required"])
    recommended_missing_count = sum(1 for item in missing if item["recommended"])
    required_filled_count = len(required_fields) - required_missing_count

    if mode == "quick":
        status = "partial" if not missing else ("partial" if len(missing) <= 2 else "insufficient")
    else:
        status = "complete" if required_missing_count == 0 else ("partial" if len(missing) <= 5 else "insufficient")

    return {
        "mode": mode,
        "status": status,
        "filled_field_count": filled_count,
        "required_field_count": len(required_fields),
        "assessed_field_count": len(assessed_fields),
        "recommended_field_count": len(recommended_fields),
        "missing_count": len(missing),
        "required_missing_count": required_missing_count,
        "recommended_missing_count": recommended_missing_count,
        "required_filled_count": required_filled_count,
        "missing_fields": missing,
        "history_can_cover_representative_races": history_can_cover_representative_races,
        "completeness_ratio": round(filled_count / len(assessed_fields), 3) if assessed_fields else 1.0,
        "required_completeness_ratio": round(filled_count / len(required_fields), 3) if required_fields else 1.0,
    }
