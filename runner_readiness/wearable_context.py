"""Fail-closed validation for W2's optional aggregate-only context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def validate_wearable_feature_summary(summary: Mapping[str, Any]) -> list[str]:
    """Validate the W2 boundary without importing FIT or private-data code."""
    errors: list[str] = []
    required = {"schema_name", "schema_version", "summary_id", "generated_at", "aggregation_window", "source_trace", "training_load", "quality", "uncertainty", "governance"}
    if set(summary) != required:
        errors.append("wearable_summary:unexpected_or_missing_top_level_fields")
    if summary.get("schema_name") != "wearable_feature_summary" or summary.get("schema_version") != "1.0.0":
        errors.append("wearable_summary:unsupported_schema")
    governance = summary.get("governance")
    if not isinstance(governance, Mapping) or governance.get("allow_model_research") is not False or governance.get("user_facing_prediction_allowed") is not False:
        errors.append("wearable_summary:governance_not_locked")
    trace = summary.get("source_trace")
    if not isinstance(trace, Mapping) or trace.get("trace_complete") is not True or not isinstance(trace.get("activities"), list):
        errors.append("wearable_summary:missing_source_trace")
    else:
        for item in trace["activities"]:
            if not isinstance(item, Mapping) or not isinstance(item.get("activity_id"), str) or not isinstance(item.get("import_request_id"), str):
                errors.append("wearable_summary:invalid_source_trace")
                break
    if not isinstance(summary.get("training_load"), Mapping) or not isinstance(summary.get("quality"), Mapping) or not isinstance(summary.get("uncertainty"), Mapping):
        errors.append("wearable_summary:invalid_structure")
    return errors
