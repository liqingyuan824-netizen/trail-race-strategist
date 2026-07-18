"""Real frozen split executor for Phase 8A development-style prediction runs."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from baseline_backtest.pipeline import _predict_with_variant

from .privacy_export import scan_artifact
from .protocol_rules import build_metric_summary, can_execute_split, standard_median
from .validation import ValidationError, parse_date


FINISH_STATUSES = {"finish", "finished", "complete", "completed", "ok"}
NON_SCORING_STATUSES = {"restricted", "dnf", "did_not_finish", "dns", "dsq", "disqualified"}
AUTHORIZATION_SCHEMA_VERSION = "1.0.0"
AUTHORIZATION_RULE_VERSION = "phase8a_development_authorization_v2"
PRIVACY_SCAN_RULE_VERSION = "phase8a_internal_evaluation_privacy_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValidationError(f"{path.name}:expected_json_object")
    return dict(payload)


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _history_date(row: Mapping[str, Any]) -> datetime | None:
    return parse_date(row.get("date") or row.get("history_date") or row.get("target_date"))


def _normalize_history_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValidationError("history_row_not_mapping")
    if "prediction_minutes" in row:
        raise ValidationError("precomputed_prediction_not_allowed")
    history_id = str(row.get("history_id") or row.get("fold_id") or "").strip()
    if not history_id:
        raise ValidationError("missing_history_id")
    parsed_date = _history_date(row)
    if parsed_date is None:
        raise ValidationError(f"invalid_history_date:{history_id}")
    distance_km = _coerce_float(row.get("distance_km") or row.get("target_distance_km"))
    elevation_gain_m = _coerce_float(row.get("elevation_gain_m") or row.get("target_elevation_gain_m"))
    race_time_minutes = _coerce_float(row.get("race_time_minutes") or row.get("actual_minutes"))
    if distance_km is None or elevation_gain_m is None:
        raise ValidationError(f"missing_history_course:{history_id}")
    return {
        "history_id": history_id,
        "date": parsed_date.isoformat(),
        "date_dt": parsed_date,
        "race_name": str(row.get("race_name") or row.get("event_name") or history_id),
        "distance_km": distance_km,
        "elevation_gain_m": elevation_gain_m,
        "race_time_minutes": race_time_minutes,
        "source_type": str(row.get("source_type") or "official"),
        "source_confidence": _coerce_float(row.get("source_confidence")) or 1.0,
        "provenance_score": _coerce_float(row.get("provenance_score")) or 1.0,
    }


def _normalize_target_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValidationError("target_row_not_mapping")
    forbidden_fields = {"prediction_minutes", "prediction_interval", "prediction_hhmmss"}
    if any(field in row for field in forbidden_fields):
        raise ValidationError("precomputed_prediction_not_allowed")
    fold_id = str(row.get("fold_id") or "").strip()
    participant_reference = str(row.get("participant_reference") or "").strip()
    split = str(row.get("split") or "").strip()
    if not fold_id or not participant_reference or not split:
        raise ValidationError("missing_target_identity")
    parsed_date = parse_date(row.get("target_date") or row.get("date"))
    if parsed_date is None:
        raise ValidationError(f"invalid_target_date:{fold_id}")
    actual_minutes = _coerce_float(row.get("actual_minutes"))
    status = str(row.get("result_status") or row.get("record_status") or "").strip().lower()
    if status in NON_SCORING_STATUSES or status not in FINISH_STATUSES:
        actual_minutes = None
    history_rows = row.get("history_rows") or row.get("prior_history_rows") or []
    if not isinstance(history_rows, Sequence):
        raise ValidationError(f"history_rows_not_list:{fold_id}")
    normalized_history = [_normalize_history_row(history_row) for history_row in history_rows if isinstance(history_row, Mapping)]
    prior_history_fold_ids = [history_row["history_id"] for history_row in normalized_history if history_row["date_dt"] < parsed_date]
    prior_history_rows = [history_row for history_row in normalized_history if history_row["date_dt"] < parsed_date]
    prior_history_rows.sort(key=lambda item: item["date_dt"])
    leak_ok = len(prior_history_rows) == len(prior_history_fold_ids) and all(history_row["date_dt"] < parsed_date for history_row in prior_history_rows)
    return {
        "fold_id": fold_id,
        "participant_reference": participant_reference,
        "split": split,
        "target_date": parsed_date.isoformat(),
        "date_dt": parsed_date,
        "race_name": str(row.get("race_name") or row.get("event_name") or fold_id),
        "distance_km": _coerce_float(row.get("target_distance_km") or row.get("distance_km")),
        "elevation_gain_m": _coerce_float(row.get("target_elevation_gain_m") or row.get("elevation_gain_m")),
        "actual_minutes": actual_minutes,
        "target_status": status or None,
        "prior_history_rows": prior_history_rows,
        "prior_history_fold_ids": prior_history_fold_ids,
        "history_rows_total": len(normalized_history),
        "leak_checks_passed": leak_ok,
    }


def _model_row_from_prediction(
    *,
    target: Mapping[str, Any],
    prediction: Mapping[str, Any],
    variant: str,
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    intervals = prediction.get("intervals") or {}
    return {
        "fold_id": target["fold_id"],
        "participant_reference": target["participant_reference"],
        "split": target["split"],
        "model_variant": variant,
        "actual_minutes": target["actual_minutes"],
        "prediction_minutes": prediction.get("prediction_minutes"),
        "prediction_interval": intervals,
        "intervals": intervals,
        "prior_history_fold_ids": list(target["prior_history_fold_ids"]),
        "leak_check_snapshot": {
            "prior_history_count": len(target["prior_history_fold_ids"]),
            "history_rows_total": target["history_rows_total"],
            "history_before_target_only": target["leak_checks_passed"],
            "future_history_leak_detected": not target["leak_checks_passed"],
            "target_date": target["target_date"],
        },
        "frozen_source_hashes": dict(source_hashes),
    }


def _build_variant_rows(
    *,
    targets: Sequence[Mapping[str, Any]],
    variant: str,
    source_hashes: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in targets:
        prior_rows = [dict(history_row) for history_row in target["prior_history_rows"]]
        prediction = _predict_with_variant(target=target, prior_rows=prior_rows, variant=variant)
        rows.append(
            _model_row_from_prediction(
                target=target,
                prediction=prediction,
                variant=variant,
                source_hashes=source_hashes,
            )
        )
    return rows


def _leak_checks_passed(rows: Sequence[Mapping[str, Any]]) -> bool:
    return all(bool(row.get("leak_checks_passed", True)) for row in rows)


def _validation_gate_payload(
    *,
    full_rows: Sequence[Mapping[str, Any]],
    distance_only_rows: Sequence[Mapping[str, Any]],
    frozen_fold_ids: Sequence[str],
) -> dict[str, Any]:
    full_metrics = build_metric_summary(full_rows, expected_fold_ids=frozen_fold_ids)
    distance_metrics = build_metric_summary(distance_only_rows, expected_fold_ids=frozen_fold_ids)
    full_metrics["leak_checks_passed"] = _leak_checks_passed(full_rows)
    distance_metrics["leak_checks_passed"] = _leak_checks_passed(distance_only_rows)
    return {
        "full_metrics": full_metrics,
        "distance_only_metrics": distance_metrics,
        "gate": None,
    }


def _holdout_gate_payload(
    *,
    rows: Sequence[Mapping[str, Any]],
    frozen_fold_ids: Sequence[str],
) -> dict[str, Any]:
    metrics = build_metric_summary(rows, expected_fold_ids=frozen_fold_ids)
    metrics["leak_checks_passed"] = _leak_checks_passed(rows)
    valid_actual_minutes = [float(row["actual_minutes"]) for row in rows if row.get("actual_minutes") not in (None, "")]
    finish_time_median = standard_median(valid_actual_minutes) if valid_actual_minutes else None
    gate = None
    if finish_time_median is not None:
        gate = {
            "holdout_finish_time_median_minutes": finish_time_median,
        }
    return {"metrics": metrics, "gate": gate}


def execute_real_split(
    *,
    protocol_status: Mapping[str, Any],
    split_name: str,
    targets: Sequence[Mapping[str, Any]],
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
    allowed = can_execute_split(
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
    if not allowed:
        return {
            "schema_name": "real_split_execution",
            "schema_version": "1.0.0",
            "generated_at": _utc_now(),
            "split_name": split_name,
            "execution_allowed": False,
            "prediction_invocations": 0,
            "blocked_reason": "locked_or_hash_mismatch",
            "prediction_rows": [],
            "metrics": None,
            "source_hashes": {
                "protocol": current_protocol_sha256,
                "frozen_protocol": frozen_protocol_sha256,
                "pool_manifest": current_pool_manifest_sha256,
                "registry": current_registry_sha256,
                "eligibility_report": current_eligibility_report_sha256,
                "protocol_rules": current_protocol_rules_sha256,
                "evaluator": current_evaluator_source_sha256,
                "real_executor": current_real_executor_source_sha256,
                "cli": current_cli_source_sha256,
            },
        }

    normalized_targets = [_normalize_target_row(target) for target in targets]
    expected_fold_ids = [target["fold_id"] for target in normalized_targets]
    if current_fold_ids is not None and list(current_fold_ids) != expected_fold_ids:
        raise ValidationError("real_split:current_fold_ids_mismatch")
    if frozen_fold_ids is not None and list(frozen_fold_ids) != expected_fold_ids:
        raise ValidationError("real_split:frozen_fold_ids_mismatch")

    source_hashes = {
        "protocol": current_protocol_sha256,
        "frozen_protocol": frozen_protocol_sha256,
        "pool_manifest": current_pool_manifest_sha256,
        "registry": current_registry_sha256,
        "eligibility_report": current_eligibility_report_sha256,
        "protocol_rules": current_protocol_rules_sha256,
        "evaluator": current_evaluator_source_sha256,
        "real_executor": current_real_executor_source_sha256,
        "cli": current_cli_source_sha256,
    }
    source_hashes = {key: value for key, value in source_hashes.items() if value is not None}

    full_rows = _build_variant_rows(targets=normalized_targets, variant="full", source_hashes=source_hashes)
    distance_only_rows = _build_variant_rows(targets=normalized_targets, variant="distance_only", source_hashes=source_hashes)

    full_metrics = build_metric_summary(full_rows, expected_fold_ids=expected_fold_ids)
    distance_metrics = build_metric_summary(distance_only_rows, expected_fold_ids=expected_fold_ids)
    full_metrics["leak_checks_passed"] = _leak_checks_passed(full_rows)
    distance_metrics["leak_checks_passed"] = _leak_checks_passed(distance_only_rows)

    if split_name == "development":
        gate_payload = _validation_gate_payload(
            full_rows=full_rows,
            distance_only_rows=distance_only_rows,
            frozen_fold_ids=expected_fold_ids,
        )
        gate = {
            "stage": "development",
            "passed": True,
            "decision": "execute_development_split",
            "checks": [
                {"check": "full_prediction_calls_model", "passed": True},
                {"check": "distance_only_prediction_calls_model", "passed": True},
                {"check": "rolling_origin_without_future_leak", "passed": all(row["leak_check_snapshot"]["history_before_target_only"] for row in full_rows + distance_only_rows)},
                {"check": "shared_fold_set", "passed": [row["fold_id"] for row in full_rows] == [row["fold_id"] for row in distance_only_rows]},
            ],
            "full_metrics": gate_payload["full_metrics"],
            "distance_only_metrics": gate_payload["distance_only_metrics"],
        }
    elif split_name == "holdout":
        gate_payload = _holdout_gate_payload(rows=full_rows, frozen_fold_ids=expected_fold_ids)
        gate = {
            "stage": "holdout",
            "passed": False,
            "decision": "not_executed_in_frozen_contract",
            "metrics": gate_payload["metrics"],
            "gate": gate_payload["gate"],
        }
    else:
        gate = {
            "stage": split_name,
            "passed": True,
            "decision": "unknown_stage",
        }

    combined_rows = full_rows + distance_only_rows
    return {
        "schema_name": "real_split_execution",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "split_name": split_name,
        "execution_allowed": True,
        "prediction_invocations": len(combined_rows),
        "prediction_rows": combined_rows,
        "metrics": {
            "full": full_metrics,
            "distance_only": distance_metrics,
        },
        "gate": gate,
        "source_hashes": source_hashes,
    }


def validate_real_development_readiness(
    *,
    protocol_status: Mapping[str, Any],
    split_name: str,
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
    allowed = can_execute_split(
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
    return {
        "schema_name": "real_development_readiness",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "split_name": split_name,
        "execution_allowed": allowed,
        "prediction_invocations": 0,
        "source_hashes": {
            "protocol": current_protocol_sha256,
            "frozen_protocol": frozen_protocol_sha256,
            "pool_manifest": current_pool_manifest_sha256,
            "registry": current_registry_sha256,
            "eligibility_report": current_eligibility_report_sha256,
            "protocol_rules": current_protocol_rules_sha256,
            "evaluator": current_evaluator_source_sha256,
            "real_executor": current_real_executor_source_sha256,
            "cli": current_cli_source_sha256,
        },
    }


def load_real_split_input(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    targets = payload.get("targets", [])
    if not isinstance(targets, list):
        raise ValidationError("real_split_input:targets_not_list")
    payload["targets"] = targets
    return payload


def build_real_split_report(*, input_path: Path) -> dict[str, Any]:
    payload = load_real_split_input(input_path)
    return execute_real_split(
        protocol_status=payload["protocol_status"],
        split_name=str(payload["split_name"]),
        targets=payload["targets"],
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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _load_mapping(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return dict(payload)


def _bundle_files(bundle_dir: Path) -> dict[str, Path]:
    return {
        "protocol_freeze_manifest": bundle_dir / "protocol_freeze_manifest.json",
        "dataset_freeze_manifest": bundle_dir / "dataset_freeze_manifest.json",
        "evaluation_readiness": bundle_dir / "evaluation_readiness.json",
        "initial_execution_state": bundle_dir / "initial_execution_state.json",
        "frozen_protocol": bundle_dir / "phase8a_evaluation_protocol.frozen.json",
        "frozen_protocol_md": bundle_dir / "phase8a_evaluation_protocol.frozen.md",
        "protocol_validation_report": bundle_dir / "protocol_validation_report.json",
        "protocol_validation_report_md": bundle_dir / "protocol_validation_report.md",
    }


def _current_source_hashes() -> dict[str, str]:
    files = {
        "baseline_backtest_pipeline_sha256": Path("baseline_backtest") / "pipeline.py",
        "baseline_backtest_constants_sha256": Path("baseline_backtest") / "constants.py",
        "baseline_prediction_normalization_sha256": Path("baseline_prediction") / "normalization.py",
        "backtest_dataset_protocol_py_sha256": Path("backtest_dataset") / "protocol.py",
        "backtest_dataset_protocol_rules_py_sha256": Path("backtest_dataset") / "protocol_rules.py",
        "backtest_dataset_split_evaluator_py_sha256": Path("backtest_dataset") / "split_evaluator.py",
        "backtest_dataset_real_split_executor_py_sha256": Path("backtest_dataset") / "real_split_executor.py",
        "backtest_dataset_cli_py_sha256": Path("backtest_dataset") / "cli.py",
        "backtest_dataset_evaluation_cli_py_sha256": Path("backtest_dataset") / "evaluation_cli.py",
    }
    return {name: _sha256_file(path) for name, path in files.items()}


def _load_bundle_context(*, frozen_bundle_dir: Path) -> dict[str, Any]:
    frozen_bundle_dir = frozen_bundle_dir.resolve()
    files = _bundle_files(frozen_bundle_dir)
    for label, path in files.items():
        if not path.exists():
            raise ValidationError(f"missing_frozen_bundle_file:{label}")

    manifest = _load_mapping(files["protocol_freeze_manifest"])
    dataset_manifest = _load_mapping(files["dataset_freeze_manifest"])
    readiness = _load_mapping(files["evaluation_readiness"])
    initial_state = _load_mapping(files["initial_execution_state"])
    frozen_protocol = _load_mapping(files["frozen_protocol"])

    actual_hashes = {
        "frozen_protocol_sha256": _sha256_file(files["frozen_protocol"]),
        "dataset_freeze_manifest_sha256": _sha256_file(files["dataset_freeze_manifest"]),
        "evaluation_readiness_sha256": _sha256_file(files["evaluation_readiness"]),
        "initial_execution_state_sha256": _sha256_file(files["initial_execution_state"]),
    }
    if manifest.get("frozen_protocol_sha256") != actual_hashes["frozen_protocol_sha256"]:
        raise ValidationError("frozen_protocol_sha256_mismatch")
    if manifest.get("dataset_freeze_manifest_sha256") != actual_hashes["dataset_freeze_manifest_sha256"]:
        raise ValidationError("dataset_freeze_manifest_sha256_mismatch")
    if manifest.get("evaluation_readiness_sha256") != actual_hashes["evaluation_readiness_sha256"]:
        raise ValidationError("evaluation_readiness_sha256_mismatch")
    if manifest.get("initial_execution_state_sha256") != actual_hashes["initial_execution_state_sha256"]:
        raise ValidationError("initial_execution_state_sha256_mismatch")

    bundle_source_hashes = dict(manifest.get("frozen_source_hashes") or {})
    current_source_hashes = _current_source_hashes()
    for key, value in current_source_hashes.items():
        expected = bundle_source_hashes.get(key) or dataset_manifest.get(key) or frozen_protocol.get("frozen_source_hashes", {}).get(key)
        if expected is None and key.endswith("_sha256"):
            alt_key = key.replace("_sha256", "_py_sha256")
            expected = bundle_source_hashes.get(alt_key) or dataset_manifest.get(alt_key) or frozen_protocol.get("frozen_source_hashes", {}).get(alt_key)
        if expected is None:
            raise ValidationError(f"missing_bundle_source_hash:{key}")
        if value != expected:
            raise ValidationError(f"source_hash_mismatch:{key}")

    if frozen_protocol.get("freeze_version") != "v9":
        raise ValidationError("unsupported_frozen_bundle_version")
    if readiness.get("stage_d", {}).get("approval") is not False:
        raise ValidationError("stage_d_approval_not_false")
    if readiness.get("stage_v", {}).get("approval") is not False:
        raise ValidationError("stage_v_approval_not_false")
    if readiness.get("stage_h", {}).get("approval") is not False:
        raise ValidationError("stage_h_approval_not_false")

    manifest_folds = _normalize_unique_fold_ids(manifest.get("development_fold_ids"), "manifest")
    lock_folds = _normalize_unique_fold_ids(
        frozen_protocol.get("execution_locks", {}).get("development", {}).get("frozen_fold_ids"),
        "protocol_execution_lock",
    )
    boundary_folds = _normalize_unique_fold_ids(
        frozen_protocol.get("stage_boundaries", {}).get("stage_d", {}).get("fold_ids"),
        "protocol_stage_boundary",
    )
    if manifest_folds != lock_folds or manifest_folds != boundary_folds:
        raise ValidationError("frozen_development_fold_sources_mismatch")

    return {
        "bundle_dir": frozen_bundle_dir,
        "manifest": manifest,
        "dataset_manifest": dataset_manifest,
        "readiness": readiness,
        "initial_state": initial_state,
        "frozen_protocol": frozen_protocol,
        "bundle_source_hashes": bundle_source_hashes,
        "current_source_hashes": current_source_hashes,
        "frozen_development_fold_ids": manifest_folds,
    }


def _normalize_unique_fold_ids(value: Any, source: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{source}:fold_ids_not_list")
    fold_ids = [str(item).strip() for item in value]
    if not fold_ids or any(not item for item in fold_ids):
        raise ValidationError(f"{source}:fold_ids_missing")
    if len(fold_ids) != len(set(fold_ids)):
        raise ValidationError(f"{source}:fold_ids_duplicate")
    return fold_ids


def _load_participant_pool_metadata(*, participant_pool_dir: Path) -> dict[str, Any]:
    participant_pool_dir = participant_pool_dir.resolve()
    pool_manifest_path = participant_pool_dir / "participant_pool_manifest.json"
    pool_status_path = participant_pool_dir / "participant_pool_status.json"
    eligibility_report_path = participant_pool_dir / "eligibility_report.json"
    pool_split_index_path = participant_pool_dir / "participant_pool_split_index.json"
    for path in (pool_manifest_path, pool_status_path, eligibility_report_path, pool_split_index_path):
        if not path.exists():
            raise ValidationError(f"missing_participant_pool_file:{path.name}")

    pool_manifest = _load_mapping(pool_manifest_path)
    pool_status = _load_mapping(pool_status_path)
    eligibility_report = _load_mapping(eligibility_report_path)
    pool_split_index = _load_mapping(pool_split_index_path)
    source_inventory = pool_manifest.get("source_inventory", [])
    if not isinstance(source_inventory, list):
        raise ValidationError("participant_pool_manifest:source_inventory_not_list")
    source_by_participant: dict[str, dict[str, Any]] = {}
    source_by_runner: dict[str, dict[str, Any]] = {}
    for source in source_inventory:
        if not isinstance(source, Mapping):
            raise ValidationError("participant_pool_manifest:source_inventory_entry_not_mapping")
        participant_reference = str(source.get("participant_reference") or "").strip()
        pseudonymous_runner_id = str(source.get("pseudonymous_runner_id") or "").strip()
        if not participant_reference or not pseudonymous_runner_id:
            raise ValidationError("participant_pool_manifest:source_inventory_entry_missing_identity")
        source_by_participant[participant_reference] = dict(source)
        source_by_runner[pseudonymous_runner_id] = dict(source)

    split_index = pool_manifest.get("split_index", [])
    if not isinstance(split_index, list):
        raise ValidationError("participant_pool_manifest:split_index_not_list")
    development_participants = sorted(
        entry["participant_reference"]
        for entry in split_index
        if isinstance(entry, Mapping) and str(entry.get("assigned_split") or "") == "development"
    )
    if development_participants != ["P-0001", "P-0003", "P-0005", "P-0007"]:
        raise ValidationError("development_participant_set_mismatch")

    fold_rows = eligibility_report.get("fold_rows", [])
    if not isinstance(fold_rows, list):
        raise ValidationError("eligibility_report:fold_rows_not_list")
    development_fold_rows: list[dict[str, Any]] = []
    for row in fold_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("fold_cohort") != "real" or row.get("fold_status") != "usable":
            continue
        pseudonymous_runner_id = str(row.get("pseudonymous_runner_id") or "").strip()
        source = source_by_runner.get(pseudonymous_runner_id)
        if not source:
            continue
        if str(source.get("assigned_split") or "") != "development":
            continue
        development_fold_rows.append(dict(row))

    if len(development_fold_rows) != 17:
        raise ValidationError("development_fold_count_mismatch")

    return {
        "participant_pool_dir": participant_pool_dir,
        "pool_manifest": pool_manifest,
        "pool_status": pool_status,
        "eligibility_report": eligibility_report,
        "pool_split_index": pool_split_index,
        "source_by_participant": source_by_participant,
        "source_by_runner": source_by_runner,
        "development_fold_rows": development_fold_rows,
        "metadata_paths": {
            "participant_pool_manifest": pool_manifest_path,
            "participant_pool_status": pool_status_path,
            "eligibility_report": eligibility_report_path,
            "participant_pool_split_index": pool_split_index_path,
        },
    }


def _validate_pool_metadata_hashes(*, bundle_context: Mapping[str, Any], pool_metadata: Mapping[str, Any]) -> None:
    manifest = bundle_context["manifest"]
    paths = pool_metadata["metadata_paths"]
    checks = {
        "participant_pool_manifest_sha256": paths["participant_pool_manifest"],
        "participant_pool_status_sha256": paths["participant_pool_status"],
        "eligibility_report_sha256": paths["eligibility_report"],
        "participant_pool_split_index_sha256": paths["participant_pool_split_index"],
    }
    for key, path in checks.items():
        expected = str(manifest.get(key) or "")
        if not expected:
            raise ValidationError(f"missing_frozen_hash:{key}")
        if _sha256_file(path) != expected:
            raise ValidationError(f"pool_metadata_hash_mismatch:{key}")
    registry_path = Path(str(bundle_context["frozen_protocol"]["pool_binding"]["cohort_registry_path"]))
    if _sha256_file(registry_path) != str(manifest.get("registry_sha256") or ""):
        raise ValidationError("pool_metadata_hash_mismatch:registry_sha256")


def _load_participant_records(*, participant_pool_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    records_path = participant_pool_dir.resolve() / "participant_pool_records.anonymized.json"
    if not records_path.exists():
        raise ValidationError(f"missing_participant_pool_file:{records_path.name}")
    records_payload = _load_mapping(records_path)
    record_rows = records_payload.get("records", [])
    if not isinstance(record_rows, list):
        raise ValidationError("participant_pool_records:records_not_list")
    records_by_participant: dict[str, dict[str, dict[str, Any]]] = {}
    for row in record_rows:
        if not isinstance(row, Mapping):
            raise ValidationError("participant_pool_records:record_not_mapping")
        participant_reference = str(row.get("participant_reference") or "").strip()
        record_id = str(row.get("record_id") or "").strip()
        if not participant_reference or not record_id:
            raise ValidationError("participant_pool_records:missing_identity")
        records_by_participant.setdefault(participant_reference, {})[record_id] = dict(row)
    return records_by_participant


def _load_participant_pool_context(*, participant_pool_dir: Path) -> dict[str, Any]:
    metadata = _load_participant_pool_metadata(participant_pool_dir=participant_pool_dir)
    records_by_participant = _load_participant_records(participant_pool_dir=participant_pool_dir)
    metadata["records_by_participant"] = records_by_participant
    return metadata


def _parse_time_minutes(value: Any) -> float | None:
    try:
        return _coerce_float(value)
    except Exception:  # pragma: no cover - defensive
        return None


def _seconds_to_minutes(value: Any) -> float | None:
    seconds = _coerce_float(value)
    if seconds is None:
        return None
    return round(seconds / 60.0, 2)


def _build_development_targets_from_pool(*, bundle_context: Mapping[str, Any], pool_context: Mapping[str, Any]) -> list[dict[str, Any]]:
    development_targets: list[dict[str, Any]] = []
    source_by_runner = pool_context["source_by_runner"]
    records_by_participant = pool_context["records_by_participant"]
    fold_rows = pool_context["development_fold_rows"]
    participant_to_records = {participant: dict(records) for participant, records in records_by_participant.items()}
    for fold_row in fold_rows:
        pseudonymous_runner_id = str(fold_row.get("pseudonymous_runner_id") or "").strip()
        source = source_by_runner.get(pseudonymous_runner_id)
        if not source:
            raise ValidationError(f"missing_source_inventory:{pseudonymous_runner_id}")
        participant_reference = str(source.get("participant_reference") or "").strip()
        records = participant_to_records.get(participant_reference)
        if not records:
            raise ValidationError(f"missing_participant_records:{participant_reference}")
        target_record_id = str(fold_row.get("target_record_id") or "").strip()
        if target_record_id not in records:
            raise ValidationError(f"missing_target_record:{target_record_id}")
        target_record = dict(records[target_record_id])
        target_date = parse_date(target_record.get("race_date"))
        if target_date is None:
            raise ValidationError(f"invalid_target_race_date:{target_record_id}")
        target_result_status = str(target_record.get("result_status") or "").strip().lower()
        target_finish = _seconds_to_minutes(target_record.get("finish_time_seconds"))
        actual_minutes = target_finish if target_result_status in FINISH_STATUSES and target_finish is not None else None
        prior_history_rows: list[dict[str, Any]] = []
        excluded_future_record_ids: list[str] = []
        for record_id, record in sorted(records.items(), key=lambda item: str(item[1].get("race_date") or "")):
            if record_id == target_record_id:
                continue
            record_date = parse_date(record.get("race_date"))
            if record_date is None:
                raise ValidationError(f"invalid_history_race_date:{record_id}")
            if record_date >= target_date:
                excluded_future_record_ids.append(record_id)
                continue
            record_status = str(record.get("result_status") or "").strip().lower()
            finish_minutes = _seconds_to_minutes(record.get("finish_time_seconds"))
            if record_status not in FINISH_STATUSES or finish_minutes is None:
                continue
            prior_history_rows.append(
                {
                    "history_id": record_id,
                    "date": record_date.isoformat(),
                    "date_dt": record_date,
                    "race_name": str(record.get("event_name") or record_id),
                    "distance_km": float(record.get("distance_km")),
                    "elevation_gain_m": float(record.get("elevation_gain_m")),
                    "race_time_minutes": float(finish_minutes),
                    "source_type": "official",
                    "source_confidence": float(record.get("data_confidence") or 0.95),
                    "provenance_score": 0.97,
                }
            )
        if any(history_row["date_dt"] >= target_date for history_row in prior_history_rows):
            raise ValidationError(f"future_history_leak:{target_record_id}")
        development_targets.append(
            {
                "fold_id": str(fold_row.get("fold_id") or "").strip(),
                "participant_reference": participant_reference,
                "split": "development",
                "target_date": target_date.isoformat(),
                "date_dt": target_date,
                "race_name": str(target_record.get("event_name") or target_record_id),
                "distance_km": float(target_record.get("distance_km")),
                "elevation_gain_m": float(target_record.get("elevation_gain_m")),
                "target_distance_km": float(target_record.get("distance_km")),
                "target_elevation_gain_m": float(target_record.get("elevation_gain_m")),
                "actual_minutes": actual_minutes,
                "result_status": target_result_status,
                "prior_history_rows": prior_history_rows,
                "prior_history_fold_ids": [row["history_id"] for row in prior_history_rows],
                "included_prior_history_ids": [row["history_id"] for row in prior_history_rows],
                "excluded_future_record_ids": excluded_future_record_ids,
                "history_rows_total": len(prior_history_rows),
                "leak_checks_passed": True,
                "history_before_target_only": True,
                "cross_runner_history_detected": False,
            }
        )
    fold_ids = [target["fold_id"] for target in development_targets]
    expected_fold_ids = [str(row.get("fold_id") or "").strip() for row in fold_rows]
    if fold_ids != expected_fold_ids:
        raise ValidationError("development_fold_id_mismatch")
    return development_targets


def build_development_authorization_template(
    *,
    frozen_bundle_dir: Path,
    participant_pool_dir: Path,
    output_root: Path,
) -> dict[str, Any]:
    bundle_context = _load_bundle_context(frozen_bundle_dir=frozen_bundle_dir)
    pool_context = _load_participant_pool_metadata(participant_pool_dir=participant_pool_dir)
    _validate_pool_metadata_hashes(bundle_context=bundle_context, pool_metadata=pool_context)
    run_id = str(uuid.uuid4())
    current_fold_ids = _normalize_unique_fold_ids(
        [row["fold_id"] for row in pool_context["development_fold_rows"]], "current_eligibility"
    )
    fold_ids = list(bundle_context["frozen_development_fold_ids"])
    if current_fold_ids != fold_ids:
        raise ValidationError("authorization_template_current_frozen_fold_mismatch")
    template = {
        "schema_name": "development_execution_authorization",
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "split": "development",
        "run_id": run_id,
        "approved": False,
        "single_use": True,
        "authorized_at": None,
        "authorized_by": "user_explicit_approval",
        "frozen_bundle_sha256": str(bundle_context["manifest"]["frozen_protocol_sha256"]),
        "dataset_freeze_manifest_sha256": str(bundle_context["manifest"]["dataset_freeze_manifest_sha256"]),
        "participant_pool_manifest_sha256": _sha256_file(participant_pool_dir / "participant_pool_manifest.json"),
        "development_fold_ids_sha256": _sha256_json(fold_ids),
        "development_fold_ids": fold_ids,
        "authorization_sha256": None,
        "notes": "template only; approval must be explicit before execution",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    template_path = output_root / "development_execution_authorization.template.json"
    _write_json(template_path, template)
    return {"authorization_template": template, "template_path": template_path}


def _load_authorization(path: Path) -> dict[str, Any]:
    payload = _load_mapping(path)
    if str(payload.get("schema_name") or "") != "development_execution_authorization":
        raise ValidationError("authorization_schema_mismatch")
    if str(payload.get("split") or "") != "development":
        raise ValidationError("authorization_split_mismatch")
    payload["authorization_sha256"] = _sha256_file(path)
    return payload


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _validate_authorization(
    *,
    auth: Mapping[str, Any],
    bundle_context: Mapping[str, Any],
    participant_pool_dir: Path,
    frozen_development_fold_ids: Sequence[str],
    current_development_fold_ids: Sequence[str],
    require_approved: bool = True,
) -> dict[str, Any]:
    authorized_at = _parse_iso_datetime(auth.get("authorized_at"))
    approved = bool(auth.get("approved"))
    if require_approved and approved is not True:
        raise ValidationError("authorization_not_approved")
    if bool(auth.get("single_use")) is not True:
        raise ValidationError("authorization_not_single_use")
    run_id = str(auth.get("run_id") or "").strip()
    try:
        parsed_run_id = uuid.UUID(run_id)
    except (ValueError, AttributeError):
        raise ValidationError("authorization_run_id_invalid") from None
    if not run_id or str(parsed_run_id) != run_id:
        raise ValidationError("authorization_run_id_invalid")
    if authorized_at is None:
        raise ValidationError("authorization_authorized_at_missing")
    if authorized_at.tzinfo is None:
        raise ValidationError("authorization_authorized_at_timezone_missing")
    if authorized_at > datetime.now(timezone.utc):
        raise ValidationError("authorization_authorized_at_in_future")
    if str(auth.get("authorized_by") or "") != "user_explicit_approval":
        raise ValidationError("authorization_authorized_by_mismatch")
    if str(auth.get("schema_version") or "") != AUTHORIZATION_SCHEMA_VERSION:
        raise ValidationError("authorization_schema_version_mismatch")
    if str(auth.get("frozen_bundle_sha256") or "") != str(bundle_context["manifest"]["frozen_protocol_sha256"]):
        raise ValidationError("authorization_bundle_hash_mismatch")
    if str(auth.get("dataset_freeze_manifest_sha256") or "") != str(bundle_context["manifest"]["dataset_freeze_manifest_sha256"]):
        raise ValidationError("authorization_dataset_manifest_hash_mismatch")
    if str(auth.get("participant_pool_manifest_sha256") or "") != _sha256_file(participant_pool_dir / "participant_pool_manifest.json"):
        raise ValidationError("authorization_pool_manifest_hash_mismatch")
    auth_fold_ids = _normalize_unique_fold_ids(auth.get("development_fold_ids"), "authorization")
    if list(current_development_fold_ids) != list(frozen_development_fold_ids):
        raise ValidationError("current_frozen_fold_ids_mismatch")
    if auth_fold_ids != list(frozen_development_fold_ids):
        raise ValidationError("authorization_fold_ids_mismatch")
    if _sha256_json(auth_fold_ids) != str(auth.get("development_fold_ids_sha256") or ""):
        raise ValidationError("authorization_fold_digest_mismatch")
    return {
        "schema_name": "authorization_verification",
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "authorization_sha256": auth.get("authorization_sha256"),
        "run_id": run_id,
        "authorized_at": authorized_at.isoformat(),
        "approved": approved,
        "single_use": True,
        "authorized_by": "user_explicit_approval",
        "bundle_sha256": bundle_context["manifest"]["frozen_protocol_sha256"],
        "dataset_freeze_manifest_sha256": bundle_context["manifest"]["dataset_freeze_manifest_sha256"],
        "participant_pool_manifest_sha256": _sha256_file(participant_pool_dir / "participant_pool_manifest.json"),
        "development_fold_ids_sha256": _sha256_json(list(frozen_development_fold_ids)),
        "development_fold_ids": list(frozen_development_fold_ids),
        "verified": True,
    }


def _execution_state_after_path(output_root: Path) -> Path:
    return output_root / "execution_state_after.json"


def _development_ledger_path(output_root: Path) -> Path:
    return output_root / "development_execution_ledger.json"


def _development_lock_dir(output_root: Path) -> Path:
    return output_root / ".development-run-locks"


def _load_development_ledger(output_root: Path) -> dict[str, Any]:
    ledger_path = _development_ledger_path(output_root)
    if not ledger_path.exists():
        return {
            "schema_name": "development_execution_ledger",
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "run_ids": [],
            "entries": [],
        }
    payload = _load_mapping(ledger_path)
    if str(payload.get("schema_name") or "") != "development_execution_ledger":
        raise ValidationError("development_ledger_schema_mismatch")
    return payload


def _write_development_ledger(output_root: Path, ledger: Mapping[str, Any]) -> Path:
    ledger_path = _development_ledger_path(output_root)
    _write_json(ledger_path, ledger)
    return ledger_path


def _reserve_run_id(
    *,
    output_root: Path,
    run_id: str,
    authorization_sha256: str,
) -> Path:
    lock_dir = _development_lock_dir(output_root)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{run_id}.lock"
    if lock_path.exists():
        raise ValidationError("run_id_already_reserved")
    lock_payload = {
        "schema_name": "development_run_lock",
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "run_id": run_id,
        "status": "reserved",
        "authorization_sha256": authorization_sha256,
    }
    with lock_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(lock_payload, ensure_ascii=False, indent=2))
    return lock_path


def _update_run_lock(lock_path: Path, *, status: str, extra: Mapping[str, Any] | None = None) -> None:
    payload = _load_mapping(lock_path)
    payload["status"] = status
    payload["updated_at"] = _utc_now()
    if extra:
        payload.update(dict(extra))
    _write_json(lock_path, payload)


def _scan_privacy_artifacts(output_dir: Path, *, identity_denylist: Sequence[str] = ()) -> dict[str, Any]:
    """Scan internal research artifacts without applying public-export restrictions.

    Pseudonymous IDs, row-level folds and local-only metadata are expected here. Direct
    identifiers and private identity material remain fail-closed.
    """
    file_scans: list[dict[str, Any]] = []
    blocked = False
    matched_count = 0
    denylist = [str(token).casefold() for token in identity_denylist if str(token).strip()]
    forbidden_keys = ("provided_name", "provided_itra_id", "itra_id", "participant_identity_map")
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        scan = scan_artifact(path)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        folded = text.casefold()
        denylist_hits = sum(1 for token in denylist if token in folded)
        private_key_hits = [key for key in forbidden_keys if key in folded]
        public_scan_direct_hits = list(scan["direct_identifier_hits"])
        direct_hit_count = len(public_scan_direct_hits) + denylist_hits
        file_blocked = direct_hit_count > 0 or bool(private_key_hits)
        file_scans.append(
            {
                "file": path.name,
                "path": str(path),
                "safe_digest": _sha256_file(path),
                "direct_identifier_hit_count": direct_hit_count,
                "private_identity_hits": private_key_hits,
                "forbidden_key_hits": private_key_hits,
                "contains_pseudonymous_rows": bool(scan["pseudonymous_identifier_hits"]),
                "local_only_metadata": bool(scan["local_only_hits"]) or bool(scan["contains_absolute_local_path"]),
                "contains_row_level_race_history": bool(scan["contains_row_level_race_history"]),
                "blocked": file_blocked,
            }
        )
        matched_count += direct_hit_count + len(private_key_hits)
        blocked = blocked or file_blocked
    return {
        "schema_name": "privacy_scan",
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "rule_version": PRIVACY_SCAN_RULE_VERSION,
        "classification": "internal_research_only",
        "public_export_allowed": False,
        "contains_pseudonymous_rows": any(item["contains_pseudonymous_rows"] for item in file_scans),
        "direct_identifier_hits": sum(item["direct_identifier_hit_count"] for item in file_scans),
        "private_identity_hits": sum(len(item["private_identity_hits"]) for item in file_scans),
        "forbidden_key_hits": sum(len(item["forbidden_key_hits"]) for item in file_scans),
        "scanned_files": [item["file"] for item in file_scans],
        "file_scans": file_scans,
        "hit_count": matched_count,
        "contains_forbidden_tokens": blocked,
        "passed": not blocked,
    }


def _load_local_identity_denylist(
    private_map_dir: Path = Path("private") / "participant_identity_maps",
) -> list[str]:
    """Load direct identifiers for local comparison only.

    Callers must never serialize the returned values or the private source paths.
    """
    if not private_map_dir.is_dir():
        raise ValidationError("identity_denylist_unavailable")
    tokens: list[str] = []
    map_paths = sorted(private_map_dir.glob("*.identity.local.json"))
    if not map_paths:
        raise ValidationError("identity_denylist_unavailable")
    for path in map_paths:
        payload = _load_mapping(path)
        if (
            payload.get("schema_name") != "participant_identity_map_local_only"
            or payload.get("sensitive") is not True
            or payload.get("local_only") is not True
        ):
            raise ValidationError("identity_denylist_invalid_map")
        for key in ("provided_name", "provided_itra_id"):
            token = str(payload.get(key) or "").strip()
            if not token:
                raise ValidationError("identity_denylist_empty_identifier")
            tokens.append(token)
    unique_tokens = list(dict.fromkeys(tokens))
    if not unique_tokens:
        raise ValidationError("identity_denylist_empty")
    return unique_tokens


def _blocked_development_report(*, bundle_context: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema_name": "real_split_execution",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "split_name": "development",
        "execution_allowed": False,
        "prediction_invocations": 0,
        "blocked_reason": reason,
        "prediction_rows": [],
        "metrics": None,
        "bundle_sha256": bundle_context["manifest"]["frozen_protocol_sha256"],
    }


def validate_bundle_first_development_readiness(
    *,
    frozen_bundle_dir: Path,
    participant_pool_dir: Path,
    authorization_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    bundle_context = _load_bundle_context(frozen_bundle_dir=frozen_bundle_dir)
    pool_metadata = _load_participant_pool_metadata(participant_pool_dir=participant_pool_dir)
    _validate_pool_metadata_hashes(bundle_context=bundle_context, pool_metadata=pool_metadata)
    auth = _load_authorization(authorization_path)
    current_fold_ids = _normalize_unique_fold_ids(
        [target["fold_id"] for target in pool_metadata["development_fold_rows"]], "current_eligibility"
    )
    frozen_fold_ids = bundle_context["frozen_development_fold_ids"]
    try:
        auth_verification = _validate_authorization(
            auth=auth,
            bundle_context=bundle_context,
            participant_pool_dir=participant_pool_dir,
            frozen_development_fold_ids=frozen_fold_ids,
            current_development_fold_ids=current_fold_ids,
            require_approved=False,
        )
    except ValidationError as exc:
        return {
            "schema_name": "real_development_readiness",
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "split_name": "development",
            "execution_allowed": False,
            "prediction_invocations": 0,
            "authorization_approved": bool(auth.get("approved")),
            "blocked_reason": str(exc),
            "frozen_fold_ids": list(frozen_fold_ids),
        }
    bundle_allowed = can_execute_split(
        protocol_status=bundle_context["frozen_protocol"],
        split_name="development",
        current_protocol_sha256=bundle_context["current_source_hashes"]["backtest_dataset_protocol_py_sha256"],
        frozen_protocol_sha256=bundle_context["manifest"]["protocol_py_sha256"],
        current_pool_manifest_sha256=_sha256_file(participant_pool_dir / "participant_pool_manifest.json"),
        frozen_pool_manifest_sha256=bundle_context["manifest"]["participant_pool_manifest_sha256"],
        current_registry_sha256=_sha256_file(Path(bundle_context["frozen_protocol"]["pool_binding"]["cohort_registry_path"])),
        frozen_registry_sha256=bundle_context["manifest"]["registry_sha256"],
        current_eligibility_report_sha256=_sha256_file(participant_pool_dir / "eligibility_report.json"),
        frozen_eligibility_report_sha256=bundle_context["manifest"]["eligibility_report_sha256"],
        current_model_source_sha256s=[
            bundle_context["current_source_hashes"]["baseline_backtest_pipeline_sha256"],
            bundle_context["current_source_hashes"]["baseline_backtest_constants_sha256"],
            bundle_context["current_source_hashes"]["baseline_prediction_normalization_sha256"],
        ],
        frozen_model_source_sha256s=bundle_context["frozen_protocol"]["execution_locks"]["development"]["frozen_model_source_sha256s"],
        current_protocol_rules_sha256=bundle_context["current_source_hashes"]["backtest_dataset_protocol_rules_py_sha256"],
        frozen_protocol_rules_sha256=bundle_context["manifest"]["protocol_rules_sha256"],
        current_evaluator_source_sha256=bundle_context["current_source_hashes"]["backtest_dataset_split_evaluator_py_sha256"],
        frozen_evaluator_source_sha256=bundle_context["manifest"]["split_evaluator_sha256"],
        current_real_executor_source_sha256=bundle_context["current_source_hashes"]["backtest_dataset_real_split_executor_py_sha256"],
        frozen_real_executor_source_sha256=bundle_context["manifest"]["real_split_executor_sha256"],
        current_cli_source_sha256=bundle_context["current_source_hashes"]["backtest_dataset_cli_py_sha256"],
        frozen_cli_source_sha256=bundle_context["manifest"]["cli_sha256"],
        current_fold_ids=list(current_fold_ids),
        frozen_fold_ids=list(frozen_fold_ids),
        development_unlock_approved=bool(auth.get("approved")),
    )
    execution_allowed = bool(bundle_allowed) and bool(auth.get("approved")) and bool(auth_verification.get("verified"))
    if not execution_allowed:
        return {
            "schema_name": "real_development_readiness",
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "split_name": "development",
            "execution_allowed": False,
            "prediction_invocations": 0,
            "authorization_approved": bool(auth.get("approved")),
            "authorization_verification": auth_verification,
            "frozen_fold_ids": list(frozen_fold_ids),
        }
    return {
        "schema_name": "real_development_readiness",
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "split_name": "development",
        "execution_allowed": True,
        "prediction_invocations": 0,
        "authorization_approved": True,
        "authorization_verification": auth_verification,
        "frozen_fold_ids": list(frozen_fold_ids),
    }


def run_bundle_first_development(
    *,
    frozen_bundle_dir: Path,
    participant_pool_dir: Path,
    authorization_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    bundle_context = _load_bundle_context(frozen_bundle_dir=frozen_bundle_dir)
    pool_metadata = _load_participant_pool_metadata(participant_pool_dir=participant_pool_dir)
    _validate_pool_metadata_hashes(bundle_context=bundle_context, pool_metadata=pool_metadata)
    auth = _load_authorization(authorization_path)
    current_fold_ids = _normalize_unique_fold_ids(
        [target["fold_id"] for target in pool_metadata["development_fold_rows"]], "current_eligibility"
    )
    frozen_fold_ids = bundle_context["frozen_development_fold_ids"]
    try:
        auth_verification = _validate_authorization(
            auth=auth,
            bundle_context=bundle_context,
            participant_pool_dir=participant_pool_dir,
            frozen_development_fold_ids=frozen_fold_ids,
            current_development_fold_ids=current_fold_ids,
            require_approved=True,
        )
    except ValidationError as exc:
        return _blocked_development_report(bundle_context=bundle_context, reason=str(exc))

    current_real_executor_sha = bundle_context["current_source_hashes"]["backtest_dataset_real_split_executor_py_sha256"]
    current_cli_sha = bundle_context["current_source_hashes"]["backtest_dataset_cli_py_sha256"]
    current_registry_sha = _sha256_file(Path(bundle_context["frozen_protocol"]["pool_binding"]["cohort_registry_path"]))
    execution_allowed = can_execute_split(
        protocol_status=bundle_context["frozen_protocol"],
        split_name="development",
        current_protocol_sha256=bundle_context["current_source_hashes"]["backtest_dataset_protocol_py_sha256"],
        frozen_protocol_sha256=bundle_context["manifest"]["protocol_py_sha256"],
        current_pool_manifest_sha256=_sha256_file(participant_pool_dir / "participant_pool_manifest.json"),
        frozen_pool_manifest_sha256=bundle_context["manifest"]["participant_pool_manifest_sha256"],
        current_registry_sha256=current_registry_sha,
        frozen_registry_sha256=bundle_context["manifest"]["registry_sha256"],
        current_eligibility_report_sha256=_sha256_file(participant_pool_dir / "eligibility_report.json"),
        frozen_eligibility_report_sha256=bundle_context["manifest"]["eligibility_report_sha256"],
        current_model_source_sha256s=[
            bundle_context["current_source_hashes"]["baseline_backtest_pipeline_sha256"],
            bundle_context["current_source_hashes"]["baseline_backtest_constants_sha256"],
            bundle_context["current_source_hashes"]["baseline_prediction_normalization_sha256"],
        ],
        frozen_model_source_sha256s=bundle_context["frozen_protocol"]["execution_locks"]["development"]["frozen_model_source_sha256s"],
        current_protocol_rules_sha256=bundle_context["current_source_hashes"]["backtest_dataset_protocol_rules_py_sha256"],
        frozen_protocol_rules_sha256=bundle_context["manifest"]["protocol_rules_sha256"],
        current_evaluator_source_sha256=bundle_context["current_source_hashes"]["backtest_dataset_split_evaluator_py_sha256"],
        frozen_evaluator_source_sha256=bundle_context["manifest"]["split_evaluator_sha256"],
        current_real_executor_source_sha256=current_real_executor_sha,
        frozen_real_executor_source_sha256=bundle_context["manifest"]["real_split_executor_sha256"],
        current_cli_source_sha256=current_cli_sha,
        frozen_cli_source_sha256=bundle_context["manifest"]["cli_sha256"],
        current_fold_ids=list(current_fold_ids),
        frozen_fold_ids=list(frozen_fold_ids),
        development_unlock_approved=True,
    )
    if not execution_allowed:
        return _blocked_development_report(bundle_context=bundle_context, reason="bundle_or_authorization_mismatch")

    output_root.mkdir(parents=True, exist_ok=True)
    ledger = _load_development_ledger(output_root)
    existing_run_ids = {str(entry.get("run_id") or "") for entry in ledger.get("entries", [])}
    run_id = str(auth.get("run_id") or "")
    if run_id in existing_run_ids:
        return _blocked_development_report(bundle_context=bundle_context, reason="run_id_already_consumed")

    lock_path = _reserve_run_id(
        output_root=output_root,
        run_id=run_id,
        authorization_sha256=str(auth.get("authorization_sha256") or ""),
    )
    ledger.setdefault("run_ids", [])
    if run_id not in ledger["run_ids"]:
        ledger["run_ids"].append(run_id)
    ledger.setdefault("entries", []).append(
        {
            "run_id": run_id,
            "status": "reserved",
            "reserved_at": _utc_now(),
            "authorization_sha256": str(auth.get("authorization_sha256") or ""),
            "bundle_sha256": bundle_context["manifest"]["frozen_protocol_sha256"],
            "participant_pool_manifest_sha256": _sha256_file(participant_pool_dir / "participant_pool_manifest.json"),
        }
    )
    _write_development_ledger(output_root, ledger)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    final_dir = output_root / f"phase8a-frozen-development-{timestamp}"
    if final_dir.exists():
        _update_run_lock(lock_path, status="failed", extra={"failed_at": _utc_now(), "failure_reason": "execution_output_exists"})
        ledger["entries"][-1].update({"status": "failed", "failed_at": _utc_now(), "failure_reason": "execution_output_exists"})
        _write_development_ledger(output_root, ledger)
        raise ValidationError(f"execution_output_exists:{final_dir}")

    try:
        records_path = participant_pool_dir.resolve() / "participant_pool_records.anonymized.json"
        records_sha256 = _sha256_file(records_path)
        if records_sha256 != str(bundle_context["manifest"].get("participant_pool_records_sha256") or ""):
            raise ValidationError("participant_pool_records_sha256_mismatch")
        records_by_participant = _load_participant_records(participant_pool_dir=participant_pool_dir)
        pool_context = dict(pool_metadata)
        pool_context["records_by_participant"] = records_by_participant
        development_targets = _build_development_targets_from_pool(bundle_context=bundle_context, pool_context=pool_context)
        built_target_fold_ids = _normalize_unique_fold_ids(
            [target["fold_id"] for target in development_targets], "built_targets"
        )
        authorization_fold_ids = _normalize_unique_fold_ids(auth.get("development_fold_ids"), "authorization")
        if not (built_target_fold_ids == current_fold_ids == authorization_fold_ids == frozen_fold_ids):
            raise ValidationError("four_way_development_fold_ids_mismatch")

        full_rows: list[dict[str, Any]] = []
        distance_rows: list[dict[str, Any]] = []
        source_hashes = {
            "protocol": bundle_context["manifest"]["protocol_py_sha256"],
            "frozen_protocol": bundle_context["manifest"]["frozen_protocol_sha256"],
            "pool_manifest": bundle_context["manifest"]["participant_pool_manifest_sha256"],
            "registry": bundle_context["manifest"]["registry_sha256"],
            "eligibility_report": bundle_context["manifest"]["eligibility_report_sha256"],
            "protocol_rules": bundle_context["manifest"]["protocol_rules_sha256"],
            "evaluator": bundle_context["manifest"]["split_evaluator_sha256"],
            "real_executor": bundle_context["manifest"]["real_split_executor_sha256"],
            "cli": bundle_context["manifest"]["cli_sha256"],
        }
        for target in development_targets:
            prior_rows = [dict(row) for row in target["prior_history_rows"]]
            full_prediction = _predict_with_variant(target=target, prior_rows=prior_rows, variant="full")
            distance_prediction = _predict_with_variant(target=target, prior_rows=prior_rows, variant="distance_only")
            full_rows.append(_model_row_from_prediction(target=target, prediction=full_prediction, variant="full", source_hashes=source_hashes))
            distance_rows.append(_model_row_from_prediction(target=target, prediction=distance_prediction, variant="distance_only", source_hashes=source_hashes))

        all_rows = full_rows + distance_rows
        full_metrics = build_metric_summary(full_rows, expected_fold_ids=list(frozen_fold_ids))
        distance_metrics = build_metric_summary(distance_rows, expected_fold_ids=list(frozen_fold_ids))
        full_metrics["leak_checks_passed"] = all(row["leak_check_snapshot"]["history_before_target_only"] for row in full_rows)
        distance_metrics["leak_checks_passed"] = all(row["leak_check_snapshot"]["history_before_target_only"] for row in distance_rows)

        with tempfile.TemporaryDirectory(dir=output_root) as tmp:
            temp_dir = Path(tmp)
            auth_snapshot_path = temp_dir / "execution_authorization.snapshot.json"
            auth_snapshot_path.write_bytes(authorization_path.read_bytes())

            execution_environment = {
                "schema_name": "execution_environment",
                "schema_version": AUTHORIZATION_SCHEMA_VERSION,
                "generated_at": _utc_now(),
                "bundle_dir": str(bundle_context["bundle_dir"]),
                "participant_pool_dir": str(participant_pool_dir.resolve()),
                "authorization_path": str(authorization_path.resolve()),
                "current_source_hashes": bundle_context["current_source_hashes"],
                "frozen_source_hashes": bundle_context["bundle_source_hashes"],
            }
            source_hash_verification = {
                "schema_name": "source_hash_verification",
                "schema_version": AUTHORIZATION_SCHEMA_VERSION,
                "generated_at": _utc_now(),
                "checks": [
                    {"file": "phase8a_evaluation_protocol.frozen.json", "passed": bundle_context["manifest"]["frozen_protocol_sha256"] == _sha256_file(bundle_context["bundle_dir"] / "phase8a_evaluation_protocol.frozen.json")},
                    {"file": "dataset_freeze_manifest.json", "passed": bundle_context["manifest"]["dataset_freeze_manifest_sha256"] == _sha256_file(bundle_context["bundle_dir"] / "dataset_freeze_manifest.json")},
                    {"file": "participant_pool_manifest.json", "passed": bundle_context["manifest"]["participant_pool_manifest_sha256"] == _sha256_file(participant_pool_dir / "participant_pool_manifest.json")},
                    {"file": "cohort_split_registry.json", "passed": bundle_context["manifest"]["registry_sha256"] == current_registry_sha},
                    {"file": "eligibility_report.json", "passed": bundle_context["manifest"]["eligibility_report_sha256"] == _sha256_file(participant_pool_dir / "eligibility_report.json")},
                    {"file": "participant_pool_status.json", "passed": bundle_context["manifest"]["participant_pool_status_sha256"] == _sha256_file(participant_pool_dir / "participant_pool_status.json")},
                    {"file": "participant_pool_split_index.json", "passed": bundle_context["manifest"]["participant_pool_split_index_sha256"] == _sha256_file(participant_pool_dir / "participant_pool_split_index.json")},
                    {"file": "participant_pool_records.anonymized.json", "passed": bundle_context["manifest"]["participant_pool_records_sha256"] == records_sha256},
                    {"file": "baseline_backtest/pipeline.py", "passed": bundle_context["current_source_hashes"]["baseline_backtest_pipeline_sha256"] == bundle_context["manifest"]["baseline_backtest_pipeline_sha256"]},
                    {"file": "baseline_backtest/constants.py", "passed": bundle_context["current_source_hashes"]["baseline_backtest_constants_sha256"] == bundle_context["manifest"]["baseline_backtest_constants_sha256"]},
                    {"file": "baseline_prediction/normalization.py", "passed": bundle_context["current_source_hashes"]["baseline_prediction_normalization_sha256"] == bundle_context["manifest"]["baseline_prediction_normalization_sha256"]},
                    {"file": "backtest_dataset/protocol_rules.py", "passed": bundle_context["current_source_hashes"]["backtest_dataset_protocol_rules_py_sha256"] == bundle_context["manifest"]["protocol_rules_sha256"]},
                    {"file": "backtest_dataset/split_evaluator.py", "passed": bundle_context["current_source_hashes"]["backtest_dataset_split_evaluator_py_sha256"] == bundle_context["manifest"]["split_evaluator_sha256"]},
                    {"file": "backtest_dataset/real_split_executor.py", "passed": current_real_executor_sha == bundle_context["manifest"]["real_split_executor_sha256"]},
                    {"file": "backtest_dataset/cli.py", "passed": current_cli_sha == bundle_context["manifest"]["cli_sha256"]},
                ],
            }
            frozen_fold_inventory = {
                "schema_name": "frozen_fold_inventory",
                "schema_version": AUTHORIZATION_SCHEMA_VERSION,
                "generated_at": _utc_now(),
                "fold_count": len(development_targets),
                "fold_ids": [target["fold_id"] for target in development_targets],
                "participant_references": [target["participant_reference"] for target in development_targets],
                "fold_id_digest": _sha256_json([target["fold_id"] for target in development_targets]),
            }
            development_metrics = {
                "schema_name": "development_metrics",
                "schema_version": AUTHORIZATION_SCHEMA_VERSION,
                "generated_at": _utc_now(),
                "full": full_metrics,
                "distance_only": distance_metrics,
                "prediction_invocations": len(all_rows),
            }
            execution_report = {
                "schema_name": "development_execution_report",
                "schema_version": AUTHORIZATION_SCHEMA_VERSION,
                "generated_at": _utc_now(),
                "execution_allowed": True,
                "split_name": "development",
                "frozen_bundle_sha256": bundle_context["manifest"]["frozen_protocol_sha256"],
                "participant_pool_manifest_sha256": _sha256_file(participant_pool_dir / "participant_pool_manifest.json"),
                "prediction_invocations": len(all_rows),
                "full_row_count": len(full_rows),
                "distance_only_row_count": len(distance_rows),
                "authorization_sha256": str(auth.get("authorization_sha256") or ""),
                "run_id": run_id,
            }
            execution_state_after = {
                "schema_name": "execution_state_after",
                "schema_version": AUTHORIZATION_SCHEMA_VERSION,
                "generated_at": _utc_now(),
                "development_status": "completed",
                "validation_status": "locked",
                "holdout_status": "locked",
                "development_run_count": 1,
                "validation_run_count": 0,
                "holdout_run_count": 0,
                "last_run_id": run_id,
                "run_id_consumed": True,
                "user_facing_prediction_allowed": False,
            }

            temp_files = {
                "authorization_verification.json": auth_verification,
                "execution_environment.json": execution_environment,
                "source_hash_verification.json": source_hash_verification,
                "frozen_fold_inventory.json": frozen_fold_inventory,
                "full_prediction_rows.json": full_rows,
                "distance_only_prediction_rows.json": distance_rows,
                "development_metrics.json": development_metrics,
                "development_execution_report.json": execution_report,
                "execution_state_after.json": execution_state_after,
            }
            for filename, payload in temp_files.items():
                _write_json(temp_dir / filename, payload)

            identity_denylist = _load_local_identity_denylist()
            if not identity_denylist:
                raise ValidationError("identity_denylist_empty")
            privacy_scan = _scan_privacy_artifacts(temp_dir, identity_denylist=identity_denylist)
            _write_json(temp_dir / "privacy_scan.json", privacy_scan)
            if not privacy_scan["passed"]:
                raise ValidationError("privacy_scan_failed")

            temp_dir.replace(final_dir)

        ledger["entries"][-1].update(
            {
                "status": "completed",
                "completed_at": _utc_now(),
                "result_dir": str(final_dir),
                "prediction_invocations": len(all_rows),
            }
        )
        _write_development_ledger(output_root, ledger)
        _update_run_lock(
            lock_path,
            status="completed",
            extra={
                "completed_at": _utc_now(),
                "result_dir": str(final_dir),
                "prediction_invocations": len(all_rows),
            },
        )
        return {
            "schema_name": "development_execution_report",
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "split_name": "development",
            "execution_allowed": True,
            "prediction_invocations": len(all_rows),
            "output_dir": str(final_dir),
            "full_row_count": len(full_rows),
            "distance_only_row_count": len(distance_rows),
            "development_fold_ids": list(frozen_fold_ids),
            "authorization_verification": auth_verification,
            "ledger_path": str(_development_ledger_path(output_root)),
            "lock_path": str(lock_path),
        }
    except Exception as exc:
        failure_reason = str(exc)
        if "lock_path" in locals() and lock_path.exists():
            try:
                _update_run_lock(lock_path, status="failed", extra={"failed_at": _utc_now(), "failure_reason": failure_reason})
            except Exception:
                pass
        if "ledger" in locals() and ledger.get("entries"):
            ledger["entries"][-1].update({"status": "failed", "failed_at": _utc_now(), "failure_reason": failure_reason})
            try:
                _write_development_ledger(output_root, ledger)
            except Exception:
                pass
        if isinstance(exc, ValidationError):
            return _blocked_development_report(bundle_context=bundle_context, reason=failure_reason)
        raise
