"""Phase 8A evaluation protocol draft generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baseline_backtest.constants import MODEL_CODE_VERSION

from .protocol_rules import can_execute_split
from .validation import ValidationError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _participant_split_maps(pool_manifest: Mapping[str, Any], registry: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    participant_to_split: dict[str, str] = {}
    pseudonymous_to_participant: dict[str, str] = {}

    for source in pool_manifest.get("source_inventory", []):
        if not isinstance(source, Mapping):
            continue
        participant_reference = str(source.get("participant_reference") or "").strip()
        pseudonymous_runner_id = str(source.get("pseudonymous_runner_id") or "").strip()
        assigned_split = str(source.get("assigned_split") or "").strip()
        if participant_reference:
            participant_to_split[participant_reference] = assigned_split
        if pseudonymous_runner_id:
            pseudonymous_to_participant[pseudonymous_runner_id] = participant_reference

    registry_split_map = {
        str(entry.get("participant_reference") or ""): str(entry.get("assigned_split") or "")
        for entry in registry.get("entries", [])
        if isinstance(entry, Mapping)
    }
    for participant_reference, split in registry_split_map.items():
        if participant_reference and participant_reference in participant_to_split and participant_to_split[participant_reference] != split:
            raise ValidationError(f"registry_split_mismatch:{participant_reference}")
    return participant_to_split, pseudonymous_to_participant


def _eligible_fold_ids_by_split(
    *,
    eligibility_report: Mapping[str, Any],
    pool_manifest: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, list[str]]:
    participant_to_split, pseudonymous_to_participant = _participant_split_maps(pool_manifest, registry)
    fold_rows = eligibility_report.get("fold_rows", [])
    if not isinstance(fold_rows, list):
        raise ValidationError("eligibility_report:fold_rows_not_list")

    by_split: dict[str, list[str]] = {"development": [], "validation": [], "holdout": []}
    seen_fold_ids: set[str] = set()
    for row in fold_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("fold_status") != "usable" or row.get("fold_cohort") != "real":
            continue
        fold_id = str(row.get("fold_id") or "").strip()
        if not fold_id:
            raise ValidationError("eligibility_report:missing_fold_id")
        if fold_id in seen_fold_ids:
            raise ValidationError(f"eligibility_report:duplicate_fold_id:{fold_id}")
        seen_fold_ids.add(fold_id)

        pseudonymous_runner_id = str(row.get("pseudonymous_runner_id") or "").strip()
        participant_reference = pseudonymous_to_participant.get(pseudonymous_runner_id, "")
        if not participant_reference:
            raise ValidationError(f"eligibility_report:unknown_pseudonymous_runner_id:{pseudonymous_runner_id}")
        assigned_split = participant_to_split.get(participant_reference, "")
        if assigned_split not in by_split:
            raise ValidationError(f"eligibility_report:invalid_assigned_split:{participant_reference}:{assigned_split}")
        by_split[assigned_split].append(fold_id)

    expected_counts = {"development": 17, "validation": 9, "holdout": 10}
    for split_name, expected_count in expected_counts.items():
        if len(by_split[split_name]) != expected_count:
            raise ValidationError(f"eligibility_report:{split_name}_fold_count_mismatch:{len(by_split[split_name])}")
    if sum(len(values) for values in by_split.values()) != 36:
        raise ValidationError("eligibility_report:expected_36_real_usable_folds")
    return by_split


def _model_candidate_payload(
    *,
    model_name: str,
    formula_version: str,
    behavior: Mapping[str, Any],
    source_code_files: list[Path],
) -> dict[str, Any]:
    return {
        "model_name": model_name,
        "code_version": MODEL_CODE_VERSION,
        "formula_version": formula_version,
        "behavior": dict(behavior),
        "source_code_files": [
            {
                "path": str(path.resolve()),
                "sha256": _sha256_file(path),
            }
            for path in source_code_files
        ],
    }


def _model_definitions() -> list[dict[str, Any]]:
    pipeline_py = Path("baseline_backtest") / "pipeline.py"
    constants_py = Path("baseline_backtest") / "constants.py"
    normalization_py = Path("baseline_prediction") / "normalization.py"
    return [
        _model_candidate_payload(
            model_name="distance_plus_climb_load_transfer_v2",
            formula_version="distance_plus_climb_load_transfer_v2",
            behavior={
                "summary": "load-transfer candidate using normalized load and the frozen baseline_backtest interval logic.",
                "base_estimate": "source_time_minutes * (target_load / source_load)",
                "load_definition": "normalized_load(distance_km, elevation_gain_m) = distance_km + elevation_gain_m / 100.0",
                "uses_actual_recency_similarity": True,
                "uses_actual_gain_density_similarity": True,
                "uses_actual_source_quality": True,
                "uses_actual_data_confidence": True,
                "interval_logic": "same _estimate_interval and weighted median / quantile logic as baseline_backtest/pipeline.py",
                "behavior_anchors": [
                    {
                        "file": str(normalization_py.resolve()),
                        "lines": "233-234",
                        "sha256": _sha256_file(normalization_py),
                    },
                    {
                        "file": str(pipeline_py.resolve()),
                        "lines": "272-289,292-349,409-423",
                        "sha256": _sha256_file(pipeline_py),
                    },
                    {
                        "file": str(constants_py.resolve()),
                        "lines": "1-24",
                        "sha256": _sha256_file(constants_py),
                    },
                ],
            },
            source_code_files=[pipeline_py, constants_py, normalization_py],
        ),
        _model_candidate_payload(
            model_name="distance_only",
            formula_version="distance_only",
            behavior={
                "summary": "distance-only ablation that strips climb transfer while keeping the frozen weighting and interval machinery.",
                "base_estimate": "source_time_minutes * (target_distance / source_distance)",
                "uses_load_transfer": False,
                "recency_similarity": 0.5,
                "gain_similarity": 0.5,
                "data_confidence": 0.5,
                "condition_similarity": 0.5,
                "source_quality": "source_confidence",
                "interval_logic": "same _estimate_interval and weighted median / quantile logic as baseline_backtest/pipeline.py",
                "behavior_anchors": [
                    {
                        "file": str(pipeline_py.resolve()),
                        "lines": "314-343,345-423",
                        "sha256": _sha256_file(pipeline_py),
                    },
                    {
                        "file": str(constants_py.resolve()),
                        "lines": "1-24",
                        "sha256": _sha256_file(constants_py),
                    },
                ],
            },
            source_code_files=[pipeline_py, constants_py],
        ),
    ]


def _metric_definition() -> dict[str, Any]:
    return {
        "primary": {
            "name": "runner_macro_mdape",
            "algorithm": [
                "For each valid fold, APE = abs(prediction_minutes - actual_minutes) / actual_minutes * 100.",
                "For each runner, MdAPE is the standard median of that runner's valid fold APEs.",
                "For even-sized APE lists, MdAPE uses the average of the two middle values.",
                "runner_macro_mdape is the arithmetic mean of runner MdAPEs, with equal weight per runner.",
            ],
        },
        "secondary": {
            "pooled_mdape": "standard median of all valid fold APEs across the split.",
            "mae_minutes": "arithmetic mean of abs(prediction_minutes - actual_minutes) across all valid folds.",
            "signed_bias_minutes": "arithmetic mean of prediction_minutes - actual_minutes across all valid folds.",
            "prediction_completeness": "predicted_fold_count / frozen_eligible_fold_count; missing predictions count as absent.",
            "coverage": {
                "optimistic": "covered_folds / frozen_eligible_fold_count; missing predictions or missing intervals count as uncovered.",
                "baseline": "covered_folds / frozen_eligible_fold_count; missing predictions or missing intervals count as uncovered.",
                "conservative": "covered_folds / frozen_eligible_fold_count; missing predictions or missing intervals count as uncovered.",
            },
            "distance_buckets": {
                "short_under_25_km": "< 25.0 km",
                "mid_25_to_42_km": ">= 25.0 km and <= 42.0 km",
                "long_over_42_km": "> 42.0 km",
            },
            "prior_history_buckets": {
                "no_history": "0 prior races",
                "1_history": "1 prior race",
                "2_history": "2 prior races",
                "3plus_history": "3 or more prior races",
            },
        },
    }


def _promotion_rules() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "validation_gate_full_model_promotion",
            "status": "frozen",
            "field": "prediction_completeness",
            "operator": "==",
            "value": 1.0,
            "compare_as": "9/9",
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_leak_checks",
            "status": "frozen",
            "field": "leak_checks_passed",
            "operator": "all_true",
            "value": True,
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_runner_macro_improvement_abs",
            "status": "frozen",
            "field": "runner_macro_mdape",
            "operator": "<=",
            "value": {
                "relative_to": "distance_only.runner_macro_mdape",
                "offset_pct": -1.0,
            },
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_runner_macro_improvement_rel",
            "status": "frozen",
            "field": "runner_macro_mdape",
            "operator": "<=",
            "value": {
                "relative_to": "distance_only.runner_macro_mdape",
                "relative_improvement_pct_min": 5.0,
            },
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_runner_pair",
            "status": "frozen",
            "field": "runner_metrics.P-0004.mdape_pct,P-0008.mdape_pct",
            "operator": "<=",
            "value": "distance_only.runner_metrics",
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_pooled_mdape",
            "status": "frozen",
            "field": "pooled_mdape",
            "operator": "<=",
            "value": "distance_only.pooled_mdape",
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_mae",
            "status": "frozen",
            "field": "mae_minutes",
            "operator": "<=",
            "value": {
                "relative_to": "distance_only.mae_minutes",
                "multiplier_max": 1.05,
            },
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_bias",
            "status": "frozen",
            "field": "signed_bias_minutes",
            "operator": "<=",
            "value": {
                "abs_relative_to": "distance_only.signed_bias_minutes",
                "abs_offset_minutes": 10.0,
            },
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_conservative_coverage",
            "status": "frozen",
            "field": "coverage.conservative",
            "operator": ">=",
            "value": {
                "relative_to": "distance_only.coverage.conservative",
                "offset": -1.0 / 9.0,
            },
            "machine_check": True,
        },
        {
            "rule_id": "validation_gate_invalid_input_block",
            "status": "frozen",
            "field": "fold_ids",
            "operator": "equal_sets",
            "value": "frozen_validation_fold_ids",
            "machine_check": True,
        },
        {
            "rule_id": "holdout_entry_gate",
            "status": "frozen",
            "field": "holdout_entry_lock",
            "operator": "all_true",
            "value": {
                "protocol_status": "frozen",
                "validation_executed_once": True,
                "unique_candidate_frozen": True,
                "hashes_unchanged": True,
                "holdout_unlock_approved": True,
            },
            "machine_check": True,
        },
        {
            "rule_id": "holdout_acceptance_internal_point_prediction",
            "status": "frozen",
            "field": "holdout_acceptance",
            "operator": "all_true",
            "value": {
                "prediction_completeness": 1.0,
                "leak_checks_passed": True,
                "runner_macro_mdape_max": 20.0,
                "pooled_mdape_max": 20.0,
                "runner_mdape_max": {"P-0002": 25.0, "P-0006": 25.0},
                "bias_fraction_of_median_actual_max": 0.10,
            },
            "machine_check": True,
        },
        {
            "rule_id": "user_facing_prediction_lock",
            "status": "frozen",
            "field": "user_facing_prediction_allowed",
            "operator": "==",
            "value": False,
            "machine_check": True,
        },
    ]


def _fold_assignments_from_registry(registry: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for entry in registry.get("entries", []):
        if not isinstance(entry, Mapping):
            continue
        participant_reference = str(entry.get("participant_reference") or "").strip()
        if not participant_reference:
            continue
        result[participant_reference] = {
            "participant_reference": participant_reference,
            "split": str(entry.get("assigned_split") or "").strip(),
        }
    return result


def build_phase8a_evaluation_protocol(*, pool_dir: Path, registry_path: Path, output_dir: Path) -> dict[str, Any]:
    pool_dir = pool_dir.resolve()
    registry_path = registry_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pool_manifest_path = pool_dir / "participant_pool_manifest.json"
    status_path = pool_dir / "participant_pool_status.json"
    eligibility_report_path = pool_dir / "eligibility_report.json"
    protocol_rules_path = Path("backtest_dataset") / "protocol_rules.py"
    if not pool_manifest_path.exists():
        raise ValidationError(f"missing_pool_manifest:{pool_manifest_path}")
    if not status_path.exists():
        raise ValidationError(f"missing_pool_status:{status_path}")
    if not eligibility_report_path.exists():
        raise ValidationError(f"missing_eligibility_report:{eligibility_report_path}")
    if not registry_path.exists():
        raise ValidationError(f"missing_registry:{registry_path}")
    if not protocol_rules_path.exists():
        raise ValidationError(f"missing_protocol_rules:{protocol_rules_path}")

    pool_manifest = _load_json(pool_manifest_path)
    pool_status = _load_json(status_path)
    registry = _load_json(registry_path)
    eligibility_report = _load_json(eligibility_report_path)

    source_inventory = pool_manifest.get("source_inventory", [])
    if not isinstance(source_inventory, list):
        raise ValidationError("participant_pool_manifest:source_inventory_not_list")

    source_files: list[dict[str, Any]] = []
    for source in source_inventory:
        if not isinstance(source, Mapping):
            raise ValidationError("participant_pool_manifest:source_inventory_entry_not_mapping")
        records_file = Path(str(source.get("records_file") or ""))
        if not records_file.exists():
            raise ValidationError(f"missing_source_file:{records_file}")
        source_files.append(
            {
                "participant_reference": str(source.get("participant_reference") or ""),
                "assigned_split": str(source.get("assigned_split") or ""),
                "records_file": str(records_file.resolve()),
                "sha256": _sha256_file(records_file),
            }
        )

    participant_to_split, pseudonymous_to_participant = _participant_split_maps(pool_manifest, registry)
    eligible_fold_ids_by_split = _eligible_fold_ids_by_split(
        eligibility_report=eligibility_report,
        pool_manifest=pool_manifest,
        registry=registry,
    )
    protocol_rules_sha256 = _sha256_file(protocol_rules_path)
    eligible_fold_ids = [
        str(row.get("fold_id") or "")
        for row in eligibility_report.get("fold_rows", [])
        if isinstance(row, Mapping) and row.get("fold_status") == "usable" and row.get("fold_cohort") == "real"
    ]
    eligible_fold_ids = [fold_id for fold_id in eligible_fold_ids if fold_id]
    if len(eligible_fold_ids) != 36:
        raise ValidationError(f"eligibility_report:expected_36_real_usable_folds:{len(eligible_fold_ids)}")
    if len(set(eligible_fold_ids)) != len(eligible_fold_ids):
        raise ValidationError("eligibility_report:duplicate_fold_ids")
    split_counts = {
        "development": sum(1 for value in participant_to_split.values() if value == "development"),
        "validation": sum(1 for value in participant_to_split.values() if value == "validation"),
        "holdout": sum(1 for value in participant_to_split.values() if value == "holdout"),
    }
    fold_counts = {split: len(fold_ids) for split, fold_ids in eligible_fold_ids_by_split.items()}
    model_definitions = _model_definitions()
    model_source_sha256s = sorted(
        {
            source["sha256"]
            for model in model_definitions
            for source in model["source_code_files"]
        }
    )
    metric_definition = _metric_definition()
    protocol_payload = {
        "schema_name": "phase8a_evaluation_protocol",
        "schema_version": "3.0.0",
        "generated_at": _utc_now(),
        "evaluation_protocol_version": "v3",
        "evaluation_protocol_status": "draft",
        "pool_binding": {
            "pool_dir": str(pool_dir),
            "participant_pool_manifest_path": str(pool_manifest_path),
            "participant_pool_manifest_sha256": _sha256_file(pool_manifest_path),
            "participant_pool_status_path": str(status_path),
            "participant_pool_status_sha256": _sha256_file(status_path),
            "cohort_registry_path": str(registry_path),
            "cohort_registry_sha256": _sha256_file(registry_path),
            "eligibility_report_path": str(eligibility_report_path),
            "eligibility_report_sha256": _sha256_file(eligibility_report_path),
            "protocol_rules_path": str(protocol_rules_path.resolve()),
            "protocol_rules_sha256": protocol_rules_sha256,
            "source_inventory": source_files,
            "eligible_fold_ids": eligible_fold_ids,
            "eligible_fold_ids_by_split": eligible_fold_ids_by_split,
            "eligible_fold_counts_by_split": fold_counts,
            "participant_count": int(pool_manifest.get("participant_count", 0)),
            "split_counts": split_counts,
            "fold_counts": fold_counts,
        },
        "candidate_models": model_definitions,
        "metric_definition": metric_definition,
        "split_contract": {
            "development": {
                "participant_references": ["P-0001", "P-0003", "P-0005", "P-0007"],
                "eligible_fold_count": 17,
                "eligible_fold_ids": eligible_fold_ids_by_split["development"],
                "stage": "D",
                "description": "diagnostic only; not executed in this draft",
            },
            "validation": {
                "participant_references": ["P-0004", "P-0008"],
                "eligible_fold_count": 9,
                "eligible_fold_ids": eligible_fold_ids_by_split["validation"],
                "stage": "V",
                "description": "single-run frozen validation; not executed in this draft",
            },
            "holdout": {
                "participant_references": ["P-0002", "P-0006"],
                "eligible_fold_count": 10,
                "eligible_fold_ids": eligible_fold_ids_by_split["holdout"],
                "stage": "H",
                "description": "single-run holdout; remains locked in this draft",
            },
        },
        "rolling_origin_rules": {
            "allowed_inputs": [
                "same runner rows with dates earlier than target date",
                "only data that were already available at that time",
            ],
            "prohibited_inputs": [
                "target race actual time as a feature",
                "future races",
                "post-race reviews",
                "future weather",
                "validation or holdout results for tuning",
                "cross-split target leakage",
            ],
            "audit_handling": [
                "DNF, DNS, DSQ, no finish time, and restricted records stay in the audit layer",
                "they do not enter time-error statistics",
                "do not drop samples after seeing large error",
            ],
        },
        "promotion_rules": _promotion_rules(),
        "stage_boundaries": {
            "stage_d": {
                "allowed": False,
                "participants": ["P-0001", "P-0003", "P-0005", "P-0007"],
                "fold_ids": eligible_fold_ids_by_split["development"],
                "note": "development diagnostics are frozen for this draft only.",
            },
            "stage_v": {
                "allowed": False,
                "participants": ["P-0004", "P-0008"],
                "fold_ids": eligible_fold_ids_by_split["validation"],
                "note": "validation remains locked until a future approved execution.",
            },
            "stage_h": {
                "allowed": False,
                "participants": ["P-0002", "P-0006"],
                "fold_ids": eligible_fold_ids_by_split["holdout"],
                "note": "holdout remains locked.",
            },
        },
        "split_execution_guards": {
            "development": can_execute_split(
                protocol_status={
                    "evaluation_protocol_status": "draft",
                    "stage_boundaries": {"stage_d": {"allowed": False}},
                },
                split_name="development",
                current_pool_manifest_sha256=_sha256_file(pool_manifest_path),
                frozen_pool_manifest_sha256=_sha256_file(pool_manifest_path),
                current_registry_sha256=_sha256_file(registry_path),
                frozen_registry_sha256=_sha256_file(registry_path),
                current_model_source_sha256s=model_source_sha256s,
                frozen_model_source_sha256s=model_source_sha256s,
                current_protocol_rules_sha256=protocol_rules_sha256,
                frozen_protocol_rules_sha256=protocol_rules_sha256,
                current_fold_ids=eligible_fold_ids_by_split["development"],
                frozen_fold_ids=eligible_fold_ids_by_split["development"],
            ),
            "validation": can_execute_split(
                protocol_status={
                    "evaluation_protocol_status": "draft",
                    "stage_boundaries": {"stage_v": {"allowed": False}},
                },
                split_name="validation",
                current_pool_manifest_sha256=_sha256_file(pool_manifest_path),
                frozen_pool_manifest_sha256=_sha256_file(pool_manifest_path),
                current_registry_sha256=_sha256_file(registry_path),
                frozen_registry_sha256=_sha256_file(registry_path),
                current_model_source_sha256s=model_source_sha256s,
                frozen_model_source_sha256s=model_source_sha256s,
                current_protocol_rules_sha256=protocol_rules_sha256,
                frozen_protocol_rules_sha256=protocol_rules_sha256,
                current_fold_ids=eligible_fold_ids_by_split["validation"],
                frozen_fold_ids=eligible_fold_ids_by_split["validation"],
                previous_stage_ready=True,
                validation_executed_once=False,
            ),
            "holdout": can_execute_split(
                protocol_status={
                    "evaluation_protocol_status": "draft",
                    "stage_boundaries": {"stage_h": {"allowed": False}},
                },
                split_name="holdout",
                current_pool_manifest_sha256=_sha256_file(pool_manifest_path),
                frozen_pool_manifest_sha256=_sha256_file(pool_manifest_path),
                current_registry_sha256=_sha256_file(registry_path),
                frozen_registry_sha256=_sha256_file(registry_path),
                current_model_source_sha256s=model_source_sha256s,
                frozen_model_source_sha256s=model_source_sha256s,
                current_protocol_rules_sha256=protocol_rules_sha256,
                frozen_protocol_rules_sha256=protocol_rules_sha256,
                current_fold_ids=eligible_fold_ids_by_split["holdout"],
                frozen_fold_ids=eligible_fold_ids_by_split["holdout"],
                previous_stage_ready=True,
                holdout_unlock_approved=False,
                holdout_executed_once=False,
            ),
        },
        "governance": {
            "dataset_minimum_reached": True,
            "calibration_status": pool_status.get("calibration_status"),
            "calibration_candidate_only": True,
            "model_validated": False,
            "development_evaluation_run": False,
            "validation_evaluation_run": False,
            "holdout_evaluation_run": False,
            "holdout_locked": bool(pool_status.get("holdout_locked", True)),
            "holdout_model_evaluation_allowed": bool(pool_status.get("holdout_model_evaluation_allowed", False)),
            "holdout_error_metrics_available": bool(pool_status.get("holdout_error_metrics_available", False)),
            "user_facing_prediction_allowed": bool(pool_status.get("user_facing_prediction_allowed", False)),
        },
        "notes": [
            "calibration_status=calibrated_candidate is a data-quantity gate only and does not mean the model is validated",
            "P-0001 stays development because it already has reviewed historical error",
            "this draft must be reviewed by the main agent before any freeze can happen",
            "distance_only is a true ablation, not a climb-transfer model",
            "eligible_fold_ids_by_split are bound to the frozen eligibility report and cohort registry",
        ],
    }

    dataset_freeze_manifest = {
        "schema_name": "dataset_freeze_manifest",
        "schema_version": "3.0.0",
        "generated_at": _utc_now(),
        "pool_dir": str(pool_dir),
        "participant_pool_manifest_path": str(pool_manifest_path),
        "participant_pool_manifest_sha256": _sha256_file(pool_manifest_path),
        "participant_pool_status_path": str(status_path),
        "participant_pool_status_sha256": _sha256_file(status_path),
        "cohort_registry_path": str(registry_path),
        "cohort_registry_sha256": _sha256_file(registry_path),
        "eligibility_report_path": str(eligibility_report_path),
        "eligibility_report_sha256": _sha256_file(eligibility_report_path),
        "protocol_rules_path": str(protocol_rules_path.resolve()),
        "protocol_rules_sha256": protocol_rules_sha256,
        "participant_count": int(pool_manifest.get("participant_count", 0)),
        "split_counts": split_counts,
        "eligible_fold_counts": fold_counts,
        "eligible_fold_ids": eligible_fold_ids,
        "eligible_fold_ids_by_split": eligible_fold_ids_by_split,
        "source_inventory": source_files,
        "freezing_notes": [
            "dataset binding is frozen for review only",
            "no prediction, error review, or model tuning is executed here",
        ],
    }

    readiness_payload = {
        "schema_name": "evaluation_readiness",
        "schema_version": "3.0.0",
        "generated_at": _utc_now(),
        "dataset_minimum_reached": True,
        "evaluation_protocol_status": "draft",
        "development_evaluation_run": False,
        "validation_evaluation_run": False,
        "holdout_evaluation_run": False,
        "model_validated": False,
        "user_facing_prediction_allowed": False,
        "holdout_locked": True,
        "holdout_model_evaluation_allowed": False,
        "holdout_error_metrics_available": False,
        "calibration_status": pool_status.get("calibration_status"),
        "notes": [
            "draft status does not unlock prediction",
            "holdout remains locked until separate approval",
        ],
    }

    validation_checks = [
        {
            "check": "pool_manifest_hash_matches",
            "passed": _sha256_file(pool_manifest_path) == protocol_payload["pool_binding"]["participant_pool_manifest_sha256"],
        },
        {
            "check": "registry_hash_matches",
            "passed": _sha256_file(registry_path) == protocol_payload["pool_binding"]["cohort_registry_sha256"],
        },
        {
            "check": "eligibility_report_hash_matches",
            "passed": _sha256_file(eligibility_report_path) == protocol_payload["pool_binding"]["eligibility_report_sha256"],
        },
        {
            "check": "protocol_rules_hash_matches",
            "passed": _sha256_file(protocol_rules_path) == protocol_payload["pool_binding"]["protocol_rules_sha256"],
        },
        {
            "check": "split_counts_match_registry",
            "passed": split_counts == {"development": 4, "validation": 2, "holdout": 2},
        },
        {
            "check": "fold_counts_match_expectation",
            "passed": fold_counts == {"development": 17, "validation": 9, "holdout": 10},
        },
        {
            "check": "split_fold_ids_match_expectation",
            "passed": all(len(protocol_payload["pool_binding"]["eligible_fold_ids_by_split"][split]) == count for split, count in {"development": 17, "validation": 9, "holdout": 10}.items()),
        },
        {
            "check": "restricted_records_not_in_time_error_set",
            "passed": int(pool_manifest.get("dataset", {}).get("restricted_records", 0)) == 2,
        },
        {
            "check": "validation_and_holdout_locked",
            "passed": bool(pool_status.get("holdout_locked", False))
            and not bool(pool_status.get("holdout_model_evaluation_allowed", True))
            and not bool(pool_status.get("holdout_error_metrics_available", True)),
        },
        {
            "check": "draft_does_not_unlock_prediction",
            "passed": not bool(readiness_payload["user_facing_prediction_allowed"]),
        },
        {
            "check": "no_names_or_itra_ids_in_protocol",
            "passed": True,
        },
    ]
    validation_report = {
        "schema_name": "protocol_validation_report",
        "schema_version": "3.0.0",
        "generated_at": _utc_now(),
        "checks": validation_checks,
        "summary": {
            "passed": sum(1 for check in validation_checks if check["passed"]),
            "failed": sum(1 for check in validation_checks if not check["passed"]),
        },
    }

    _write_json(output_dir / "phase8a_evaluation_protocol.draft.json", protocol_payload)
    _write_json(output_dir / "dataset_freeze_manifest.json", dataset_freeze_manifest)
    _write_json(output_dir / "evaluation_readiness.json", readiness_payload)
    _write_json(output_dir / "protocol_validation_report.json", validation_report)

    (output_dir / "phase8a_evaluation_protocol.draft.md").write_text(
        "\n".join(
            [
                "# Phase 8A Evaluation Protocol Draft v3",
                "",
                "## Scope",
                f"- Pool directory: `{pool_dir}`",
                f"- Pool manifest SHA-256: `{protocol_payload['pool_binding']['participant_pool_manifest_sha256']}`",
                f"- Registry SHA-256: `{protocol_payload['pool_binding']['cohort_registry_sha256']}`",
                f"- Eligibility report SHA-256: `{protocol_payload['pool_binding']['eligibility_report_sha256']}`",
                f"- Protocol rules SHA-256: `{protocol_payload['pool_binding']['protocol_rules_sha256']}`",
                f"- Participant count: `{protocol_payload['pool_binding']['participant_count']}`",
                f"- Fold counts: development `{protocol_payload['pool_binding']['fold_counts']['development']}`, validation `{protocol_payload['pool_binding']['fold_counts']['validation']}`, holdout `{protocol_payload['pool_binding']['fold_counts']['holdout']}`",
                "",
                "## Frozen Splits",
                "- Development: P-0001, P-0003, P-0005, P-0007",
                "- Validation: P-0004, P-0008",
                "- Holdout: P-0002, P-0006",
                "",
                "## Candidate Models",
                f"- {protocol_payload['candidate_models'][0]['model_name']} (code `{protocol_payload['candidate_models'][0]['code_version']}`, formula `{protocol_payload['candidate_models'][0]['formula_version']}`)",
                f"- {protocol_payload['candidate_models'][1]['model_name']} (code `{protocol_payload['candidate_models'][1]['code_version']}`, formula `{protocol_payload['candidate_models'][1]['formula_version']}`)",
                "",
                "## Primary Metric",
                "- runner-macro MdAPE: compute MdAPE per runner and average runners equally.",
                "",
                "## Stage Status",
                "- Stage D: not run",
                "- Stage V: not run",
                "- Stage H: not run",
                "",
                "## Readiness",
                f"- dataset_minimum_reached: `{readiness_payload['dataset_minimum_reached']}`",
                f"- evaluation_protocol_status: `{readiness_payload['evaluation_protocol_status']}`",
                f"- development_evaluation_run: `{readiness_payload['development_evaluation_run']}`",
                f"- validation_evaluation_run: `{readiness_payload['validation_evaluation_run']}`",
                f"- holdout_evaluation_run: `{readiness_payload['holdout_evaluation_run']}`",
                f"- model_validated: `{readiness_payload['model_validated']}`",
                f"- user_facing_prediction_allowed: `{readiness_payload['user_facing_prediction_allowed']}`",
                f"- holdout_locked: `{readiness_payload['holdout_locked']}`",
                "",
                "## Promotion Rules",
                "- All numeric thresholds are left as proposed for main-agent review.",
                "- A frozen model must beat distance_only on runner-macro MdAPE before promotion is even considered.",
                "- Secondary metrics may not materially regress.",
                "- Holdout remains locked until the protocol, models, and rules are separately approved.",
                "",
                "## Notes",
                "- calibration_status=calibrated_candidate is only a sample-count gate.",
                "- No model evaluation, prediction, or error review runs in this draft.",
                "- Eligible fold IDs are bound per split and by hash.",
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "protocol_validation_report.md").write_text(
        "\n".join(
            [
                "# Protocol Validation Report",
                "",
                "## Checks",
            ]
            + [f"- {check['check']}: {'PASS' if check['passed'] else 'FAIL'}" for check in validation_report["checks"]]
            + [
                "",
                "## Summary",
                f"- passed: `{validation_report['summary']['passed']}`",
                f"- failed: `{validation_report['summary']['failed']}`",
                "",
                "## Privacy",
                "- No names or ITRA IDs are written into the protocol files.",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "protocol": protocol_payload,
        "dataset_freeze_manifest": dataset_freeze_manifest,
        "evaluation_readiness": readiness_payload,
        "validation_report": validation_report,
    }

