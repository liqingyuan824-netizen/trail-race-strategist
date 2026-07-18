"""Synthetic-only split executor for Phase 8A frozen protocol checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .protocol_rules import build_metric_summary, can_execute_split
from .validation import ValidationError


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValidationError(f"{path.name}:expected_json_object")
    return dict(payload)


def _validate_synthetic_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    synthetic_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValidationError(f"synthetic_row_not_mapping:{index}")
        if row.get("synthetic") is not True:
            raise ValidationError("real_row_not_allowed_in_synthetic_executor")
        synthetic_rows.append(dict(row))
    return synthetic_rows


def execute_synthetic_split(
    *,
    protocol_status: Mapping[str, Any],
    split_name: str,
    rows: Sequence[Mapping[str, Any]],
    expected_fold_ids: Sequence[str],
    expected_fold_assignments: Mapping[str, Any] | None = None,
    current_protocol_sha256: str | None = None,
    frozen_protocol_sha256: str | None = None,
    current_pool_manifest_sha256: str | None = None,
    frozen_pool_manifest_sha256: str | None = None,
    current_registry_sha256: str | None = None,
    frozen_registry_sha256: str | None = None,
    current_eligibility_report_sha256: str | None = None,
    frozen_eligibility_report_sha256: str | None = None,
    current_model_source_sha256s: Sequence[str] | None = None,
    frozen_model_source_sha256s: Sequence[str] | None = None,
    current_protocol_rules_sha256: str | None = None,
    frozen_protocol_rules_sha256: str | None = None,
    current_evaluator_source_sha256: str | None = None,
    frozen_evaluator_source_sha256: str | None = None,
    current_real_executor_source_sha256: str | None = None,
    frozen_real_executor_source_sha256: str | None = None,
    current_cli_source_sha256: str | None = None,
    frozen_cli_source_sha256: str | None = None,
    current_fold_ids: Sequence[str] | None = None,
    frozen_fold_ids: Sequence[str] | None = None,
    previous_stage_ready: bool | None = None,
    development_unlock_approved: bool | None = None,
    development_completed: bool | None = None,
    development_decision_frozen: bool | None = None,
    validation_unlock_approved: bool | None = None,
    validation_executed_once: bool | None = None,
    validation_completed: bool | None = None,
    unique_candidate_frozen: bool | None = None,
    holdout_unlock_approved: bool | None = None,
    holdout_executed_once: bool | None = None,
    holdout_completed: bool | None = None,
) -> dict[str, Any]:
    synthetic_rows = _validate_synthetic_rows(rows)
    execution_allowed = can_execute_split(
        protocol_status=protocol_status,
        split_name=split_name,
        current_protocol_sha256=current_protocol_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
        current_pool_manifest_sha256=current_pool_manifest_sha256,
        frozen_pool_manifest_sha256=frozen_pool_manifest_sha256,
        current_registry_sha256=current_registry_sha256,
        frozen_registry_sha256=frozen_registry_sha256,
        current_eligibility_report_sha256=current_eligibility_report_sha256,
        frozen_eligibility_report_sha256=frozen_eligibility_report_sha256,
        current_model_source_sha256s=current_model_source_sha256s,
        frozen_model_source_sha256s=frozen_model_source_sha256s,
        current_protocol_rules_sha256=current_protocol_rules_sha256,
        frozen_protocol_rules_sha256=frozen_protocol_rules_sha256,
        current_evaluator_source_sha256=current_evaluator_source_sha256,
        frozen_evaluator_source_sha256=frozen_evaluator_source_sha256,
        current_real_executor_source_sha256=current_real_executor_source_sha256,
        frozen_real_executor_source_sha256=frozen_real_executor_source_sha256,
        current_cli_source_sha256=current_cli_source_sha256,
        frozen_cli_source_sha256=frozen_cli_source_sha256,
        current_fold_ids=current_fold_ids,
        frozen_fold_ids=frozen_fold_ids,
        previous_stage_ready=previous_stage_ready,
        development_unlock_approved=development_unlock_approved,
        development_completed=development_completed,
        development_decision_frozen=development_decision_frozen,
        validation_unlock_approved=validation_unlock_approved,
        validation_executed_once=validation_executed_once,
        validation_completed=validation_completed,
        unique_candidate_frozen=unique_candidate_frozen,
        holdout_unlock_approved=holdout_unlock_approved,
        holdout_executed_once=holdout_executed_once,
        holdout_completed=holdout_completed,
    )
    metrics = build_metric_summary(
        synthetic_rows,
        expected_fold_ids=expected_fold_ids,
        expected_fold_assignments=expected_fold_assignments,
    )
    metrics["leak_checks_passed"] = bool(all(row.get("leak_checks_passed", True) for row in synthetic_rows))
    return {
        "split_name": split_name,
        "synthetic_only": True,
        "execution_allowed": execution_allowed,
        "row_count": len(synthetic_rows),
        "fold_ids": list(expected_fold_ids),
        "metrics": metrics,
        "source_hashes": {
            "protocol": current_protocol_sha256,
            "frozen_protocol": frozen_protocol_sha256,
            "pool_manifest": current_pool_manifest_sha256,
            "registry": current_registry_sha256,
            "eligibility_report": current_eligibility_report_sha256,
            "protocol_rules": current_protocol_rules_sha256,
            "evaluator": current_evaluator_source_sha256,
        },
    }


def load_synthetic_split_input(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise ValidationError("synthetic_split_input:rows_not_list")
    payload["rows"] = [dict(row) for row in rows if isinstance(row, Mapping)]
    return payload


def build_synthetic_split_report(*, input_path: Path) -> dict[str, Any]:
    payload = load_synthetic_split_input(input_path)
    return execute_synthetic_split(
        protocol_status=payload["protocol_status"],
        split_name=str(payload["split_name"]),
        rows=payload["rows"],
        expected_fold_ids=payload["expected_fold_ids"],
        expected_fold_assignments=payload.get("expected_fold_assignments"),
        current_protocol_sha256=payload.get("current_protocol_sha256"),
        frozen_protocol_sha256=payload.get("frozen_protocol_sha256"),
        current_pool_manifest_sha256=payload.get("current_pool_manifest_sha256"),
        frozen_pool_manifest_sha256=payload.get("frozen_pool_manifest_sha256"),
        current_registry_sha256=payload.get("current_registry_sha256"),
        frozen_registry_sha256=payload.get("frozen_registry_sha256"),
        current_eligibility_report_sha256=payload.get("current_eligibility_report_sha256"),
        frozen_eligibility_report_sha256=payload.get("frozen_eligibility_report_sha256"),
        current_model_source_sha256s=payload.get("current_model_source_sha256s"),
        frozen_model_source_sha256s=payload.get("frozen_model_source_sha256s"),
        current_protocol_rules_sha256=payload.get("current_protocol_rules_sha256"),
        frozen_protocol_rules_sha256=payload.get("frozen_protocol_rules_sha256"),
        current_evaluator_source_sha256=payload.get("current_evaluator_source_sha256"),
        frozen_evaluator_source_sha256=payload.get("frozen_evaluator_source_sha256"),
        current_real_executor_source_sha256=payload.get("current_real_executor_source_sha256"),
        frozen_real_executor_source_sha256=payload.get("frozen_real_executor_source_sha256"),
        current_cli_source_sha256=payload.get("current_cli_source_sha256"),
        frozen_cli_source_sha256=payload.get("frozen_cli_source_sha256"),
        current_fold_ids=payload.get("current_fold_ids"),
        frozen_fold_ids=payload.get("frozen_fold_ids"),
        previous_stage_ready=payload.get("previous_stage_ready"),
        development_unlock_approved=payload.get("development_unlock_approved"),
        development_completed=payload.get("development_completed"),
        development_decision_frozen=payload.get("development_decision_frozen"),
        validation_unlock_approved=payload.get("validation_unlock_approved"),
        validation_executed_once=payload.get("validation_executed_once"),
        validation_completed=payload.get("validation_completed"),
        unique_candidate_frozen=payload.get("unique_candidate_frozen"),
        holdout_unlock_approved=payload.get("holdout_unlock_approved"),
        holdout_executed_once=payload.get("holdout_executed_once"),
        holdout_completed=payload.get("holdout_completed"),
    )
