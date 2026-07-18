"""Freeze the Phase 8A v3 draft into an immutable protocol bundle."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _freeze_stage_boundaries(protocol_payload: dict[str, Any]) -> None:
    stage_boundaries = protocol_payload.get("stage_boundaries")
    if not isinstance(stage_boundaries, dict):
        raise ValidationError("protocol:stage_boundaries_missing")
    stage_boundaries.setdefault("stage_d", {})
    stage_boundaries.setdefault("stage_v", {})
    stage_boundaries.setdefault("stage_h", {})
    stage_boundaries["stage_d"].update(
        {
            "allowed": True,
            "development_unlock_approved": False,
            "approval": False,
            "validation_unlock_approved": False,
            "holdout_unlock_approved": False,
        }
    )
    stage_boundaries["stage_v"].update(
        {
            "allowed": False,
            "development_unlock_approved": False,
            "approval": False,
            "validation_unlock_approved": False,
            "holdout_unlock_approved": False,
        }
    )
    stage_boundaries["stage_h"].update(
        {
            "allowed": False,
            "development_unlock_approved": False,
            "approval": False,
            "validation_unlock_approved": False,
            "holdout_unlock_approved": False,
        }
    )


def _frozen_gov() -> dict[str, Any]:
    return {
        "dataset_minimum_reached": True,
        "model_validated": False,
        "development_evaluation_run": False,
        "validation_evaluation_run": False,
        "holdout_evaluation_run": False,
        "user_facing_prediction_allowed": False,
        "holdout_locked": True,
        "holdout_model_evaluation_allowed": False,
        "holdout_error_metrics_available": False,
    }


def _freeze_manifest_path(output_dir: Path) -> Path:
    return output_dir / "protocol_freeze_manifest.json"


def _model_source_hashes(protocol_payload: Mapping[str, Any]) -> list[str]:
    hashes: list[str] = []
    for model in protocol_payload.get("candidate_models", []):
        if not isinstance(model, Mapping):
            continue
        for source in model.get("source_code_files", []):
            if not isinstance(source, Mapping):
                continue
            sha = str(source.get("sha256") or "").strip()
            if sha:
                hashes.append(sha)
    return sorted(set(hashes))


def _bundle_source_hashes() -> dict[str, str]:
    files = {
        "backtest_dataset_protocol_py_sha256": Path("backtest_dataset") / "protocol.py",
        "backtest_dataset_protocol_rules_py_sha256": Path("backtest_dataset") / "protocol_rules.py",
        "backtest_dataset_split_evaluator_py_sha256": Path("backtest_dataset") / "split_evaluator.py",
        "backtest_dataset_real_split_executor_py_sha256": Path("backtest_dataset") / "real_split_executor.py",
        "backtest_dataset_evaluation_cli_py_sha256": Path("backtest_dataset") / "evaluation_cli.py",
        "backtest_dataset_cli_py_sha256": Path("backtest_dataset") / "cli.py",
        "baseline_backtest_pipeline_sha256": Path("baseline_backtest") / "pipeline.py",
        "baseline_backtest_constants_sha256": Path("baseline_backtest") / "constants.py",
        "baseline_prediction_normalization_sha256": Path("baseline_prediction") / "normalization.py",
    }
    return {name: _sha256_file(path) for name, path in files.items()}


def build_phase8a_frozen_protocol(
    *,
    draft_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    draft_dir = draft_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    draft_protocol_path = draft_dir / "phase8a_evaluation_protocol.draft.json"
    draft_dataset_manifest_path = draft_dir / "dataset_freeze_manifest.json"
    draft_readiness_path = draft_dir / "evaluation_readiness.json"
    draft_report_path = draft_dir / "protocol_validation_report.json"
    if not draft_protocol_path.exists():
        raise ValidationError(f"missing_draft_protocol:{draft_protocol_path}")
    if not draft_dataset_manifest_path.exists():
        raise ValidationError(f"missing_draft_dataset_manifest:{draft_dataset_manifest_path}")
    if not draft_readiness_path.exists():
        raise ValidationError(f"missing_draft_readiness:{draft_readiness_path}")
    if not draft_report_path.exists():
        raise ValidationError(f"missing_draft_validation_report:{draft_report_path}")

    draft_protocol = _load_json(draft_protocol_path)
    draft_dataset_manifest = _load_json(draft_dataset_manifest_path)
    draft_readiness = _load_json(draft_readiness_path)
    draft_validation_report = _load_json(draft_report_path)

    if str(draft_protocol.get("evaluation_protocol_version") or "") != "v3":
        raise ValidationError("draft_protocol_version_mismatch")
    if str(draft_protocol.get("evaluation_protocol_status") or "").lower() != "draft":
        raise ValidationError("draft_protocol_status_mismatch")
    if not bool(draft_readiness.get("dataset_minimum_reached")):
        raise ValidationError("draft_readiness_not_ready")

    frozen_protocol = copy.deepcopy(draft_protocol)
    frozen_protocol["evaluation_protocol_status"] = "frozen"
    _freeze_stage_boundaries(frozen_protocol)
    frozen_protocol["governance"] = _frozen_gov()

    pool_binding = frozen_protocol.get("pool_binding")
    if not isinstance(pool_binding, dict):
        raise ValidationError("draft_protocol_pool_binding_missing")

    protocol_rules_path = Path(str(pool_binding["protocol_rules_path"]))
    protocol_rules_sha256 = str(pool_binding["protocol_rules_sha256"])
    eligibility_report_sha256 = str(pool_binding["eligibility_report_sha256"])
    participant_pool_manifest_sha256 = str(pool_binding["participant_pool_manifest_sha256"])
    cohort_registry_sha256 = str(pool_binding["cohort_registry_sha256"])
    participant_pool_status_sha256 = str(pool_binding["participant_pool_status_sha256"])
    pool_dir = Path(str(pool_binding["pool_dir"]))
    pool_records_path = pool_dir / "participant_pool_records.anonymized.json"
    pool_split_index_path = pool_dir / "participant_pool_split_index.json"
    if not pool_records_path.exists() or not pool_split_index_path.exists():
        raise ValidationError("draft_protocol_pool_artifacts_missing")
    participant_pool_records_sha256 = _sha256_file(pool_records_path)
    participant_pool_split_index_sha256 = _sha256_file(pool_split_index_path)
    source_inventory = list(pool_binding.get("source_inventory", []))
    eligible_fold_ids_by_split = pool_binding.get("eligible_fold_ids_by_split")
    if not isinstance(eligible_fold_ids_by_split, Mapping):
        raise ValidationError("draft_protocol_fold_ids_missing")

    baseline_pipeline = Path("baseline_backtest") / "pipeline.py"
    baseline_constants = Path("baseline_backtest") / "constants.py"
    baseline_normalization = Path("baseline_prediction") / "normalization.py"
    split_evaluator = Path("backtest_dataset") / "split_evaluator.py"
    real_split_executor = Path("backtest_dataset") / "real_split_executor.py"
    evaluation_cli = Path("backtest_dataset") / "evaluation_cli.py"
    cli_path = Path("backtest_dataset") / "cli.py"
    protocol_py = Path("backtest_dataset") / "protocol.py"
    model_source_sha256s = _model_source_hashes(frozen_protocol)
    bundle_source_hashes = _bundle_source_hashes()

    frozen_protocol["execution_locks"] = {
        "development": {
            "protocol_status": "frozen",
            "stage_allowed": True,
            "current_protocol_sha256": "<bind-at-run-time>",
            "frozen_protocol_sha256": "<bind-at-run-time>",
            "current_pool_manifest_sha256": participant_pool_manifest_sha256,
            "frozen_pool_manifest_sha256": participant_pool_manifest_sha256,
            "current_registry_sha256": cohort_registry_sha256,
            "frozen_registry_sha256": cohort_registry_sha256,
            "current_eligibility_report_sha256": eligibility_report_sha256,
            "frozen_eligibility_report_sha256": eligibility_report_sha256,
            "current_model_source_sha256s": model_source_sha256s,
            "frozen_model_source_sha256s": model_source_sha256s,
            "current_protocol_rules_sha256": protocol_rules_sha256,
            "frozen_protocol_rules_sha256": protocol_rules_sha256,
            "current_evaluator_source_sha256": _sha256_file(split_evaluator),
            "frozen_evaluator_source_sha256": _sha256_file(split_evaluator),
            "current_real_executor_source_sha256": _sha256_file(real_split_executor),
            "frozen_real_executor_source_sha256": _sha256_file(real_split_executor),
            "current_fold_ids": list(eligible_fold_ids_by_split["development"]),
            "frozen_fold_ids": list(eligible_fold_ids_by_split["development"]),
            "development_unlock_approved": False,
        },
        "validation": {
            "protocol_status": "frozen",
            "stage_allowed": False,
            "current_protocol_sha256": "<bind-at-run-time>",
            "frozen_protocol_sha256": "<bind-at-run-time>",
            "current_pool_manifest_sha256": participant_pool_manifest_sha256,
            "frozen_pool_manifest_sha256": participant_pool_manifest_sha256,
            "current_registry_sha256": cohort_registry_sha256,
            "frozen_registry_sha256": cohort_registry_sha256,
            "current_eligibility_report_sha256": eligibility_report_sha256,
            "frozen_eligibility_report_sha256": eligibility_report_sha256,
            "current_model_source_sha256s": model_source_sha256s,
            "frozen_model_source_sha256s": model_source_sha256s,
            "current_protocol_rules_sha256": protocol_rules_sha256,
            "frozen_protocol_rules_sha256": protocol_rules_sha256,
            "current_evaluator_source_sha256": _sha256_file(split_evaluator),
            "frozen_evaluator_source_sha256": _sha256_file(split_evaluator),
            "current_real_executor_source_sha256": _sha256_file(real_split_executor),
            "frozen_real_executor_source_sha256": _sha256_file(real_split_executor),
            "current_fold_ids": list(eligible_fold_ids_by_split["validation"]),
            "frozen_fold_ids": list(eligible_fold_ids_by_split["validation"]),
            "previous_stage_ready": False,
            "development_completed": False,
            "development_decision_frozen": False,
            "validation_unlock_approved": False,
            "validation_executed_once": False,
        },
        "holdout": {
            "protocol_status": "frozen",
            "stage_allowed": False,
            "current_protocol_sha256": "<bind-at-run-time>",
            "frozen_protocol_sha256": "<bind-at-run-time>",
            "current_pool_manifest_sha256": participant_pool_manifest_sha256,
            "frozen_pool_manifest_sha256": participant_pool_manifest_sha256,
            "current_registry_sha256": cohort_registry_sha256,
            "frozen_registry_sha256": cohort_registry_sha256,
            "current_eligibility_report_sha256": eligibility_report_sha256,
            "frozen_eligibility_report_sha256": eligibility_report_sha256,
            "current_model_source_sha256s": model_source_sha256s,
            "frozen_model_source_sha256s": model_source_sha256s,
            "current_protocol_rules_sha256": protocol_rules_sha256,
            "frozen_protocol_rules_sha256": protocol_rules_sha256,
            "current_evaluator_source_sha256": _sha256_file(split_evaluator),
            "frozen_evaluator_source_sha256": _sha256_file(split_evaluator),
            "current_real_executor_source_sha256": _sha256_file(real_split_executor),
            "frozen_real_executor_source_sha256": _sha256_file(real_split_executor),
            "current_fold_ids": list(eligible_fold_ids_by_split["holdout"]),
            "frozen_fold_ids": list(eligible_fold_ids_by_split["holdout"]),
            "validation_completed": False,
            "unique_candidate_frozen": False,
            "holdout_unlock_approved": False,
            "holdout_executed_once": False,
        },
    }

    frozen_protocol["split_execution_guards"] = {
        "development": True,
        "validation": False,
        "holdout": False,
    }
    frozen_protocol["holdout_locked"] = True
    frozen_protocol["holdout_model_evaluation_allowed"] = False
    frozen_protocol["holdout_error_metrics_available"] = False
    frozen_protocol["user_facing_prediction_allowed"] = False
    frozen_protocol["freeze_version"] = "v9"
    frozen_protocol["pool_binding"].update(
        {
            "participant_pool_records_path": str(pool_records_path),
            "participant_pool_records_sha256": participant_pool_records_sha256,
            "participant_pool_split_index_path": str(pool_split_index_path),
            "participant_pool_split_index_sha256": participant_pool_split_index_sha256,
        }
    )
    frozen_protocol["frozen_source_hashes"] = {
        **bundle_source_hashes,
        "protocol_rules_sha256": protocol_rules_sha256,
        "split_evaluator_sha256": _sha256_file(split_evaluator),
        "real_split_executor_sha256": _sha256_file(real_split_executor),
        "evaluation_cli_sha256": _sha256_file(evaluation_cli),
        "cli_sha256": _sha256_file(cli_path),
        "protocol_py_sha256": _sha256_file(protocol_py),
    }

    frozen_protocol_path = output_dir / "phase8a_evaluation_protocol.frozen.json"
    _write_json(frozen_protocol_path, frozen_protocol)

    initial_execution_state = {
        "schema_name": "initial_execution_state",
        "schema_version": "3.0.0",
        "generated_at": _utc_now(),
        "development_status": "ready_not_run",
        "validation_status": "locked",
        "holdout_status": "locked",
        "development_run_count": 0,
        "validation_run_count": 0,
        "holdout_run_count": 0,
        "selected_candidate": None,
        "development_decision_frozen": False,
        "unique_candidate_frozen": False,
    }
    _write_json(output_dir / "initial_execution_state.json", initial_execution_state)

    frozen_protocol_sha256 = _sha256_file(frozen_protocol_path)
    dataset_manifest = copy.deepcopy(draft_dataset_manifest)
    dataset_manifest["schema_version"] = "3.0.0"
    dataset_manifest["generated_at"] = _utc_now()
    dataset_manifest["freeze_state"] = "frozen"
    dataset_manifest["freeze_version"] = "v9"
    dataset_manifest["participant_pool_records_sha256"] = participant_pool_records_sha256
    dataset_manifest["participant_pool_split_index_sha256"] = participant_pool_split_index_sha256
    dataset_manifest["participant_pool_status_sha256"] = participant_pool_status_sha256
    dataset_manifest["frozen_protocol_sha256"] = frozen_protocol_sha256
    dataset_manifest["protocol_rules_sha256"] = protocol_rules_sha256
    dataset_manifest["split_evaluator_sha256"] = _sha256_file(split_evaluator)
    dataset_manifest["real_split_executor_sha256"] = _sha256_file(real_split_executor)
    dataset_manifest["evaluation_cli_sha256"] = _sha256_file(evaluation_cli)
    dataset_manifest["cli_sha256"] = _sha256_file(cli_path)
    dataset_manifest["protocol_py_sha256"] = _sha256_file(protocol_py)
    dataset_manifest["frozen_source_hashes"] = dict(frozen_protocol["frozen_source_hashes"])
    dataset_manifest_path = output_dir / "dataset_freeze_manifest.json"
    _write_json(dataset_manifest_path, dataset_manifest)
    dataset_freeze_manifest_sha256 = _sha256_file(dataset_manifest_path)

    readiness = {
        "schema_name": "evaluation_readiness",
        "schema_version": "3.0.0",
        "generated_at": _utc_now(),
        "dataset_minimum_reached": True,
        "evaluation_protocol_status": "frozen",
        "development_evaluation_run": False,
        "validation_evaluation_run": False,
        "holdout_evaluation_run": False,
        "model_validated": False,
        "user_facing_prediction_allowed": False,
        "holdout_locked": True,
        "holdout_model_evaluation_allowed": False,
        "holdout_error_metrics_available": False,
        "stage_d": {"allowed": True, "development_unlock_approved": False, "approval": False},
        "stage_v": {"allowed": False, "validation_unlock_approved": False, "approval": False},
        "stage_h": {"allowed": False, "holdout_unlock_approved": False, "approval": False},
        "frozen_protocol_sha256": frozen_protocol_sha256,
        "dataset_freeze_manifest_sha256": dataset_freeze_manifest_sha256,
        "protocol_rules_sha256": protocol_rules_sha256,
        "split_evaluator_sha256": _sha256_file(split_evaluator),
        "real_split_executor_sha256": _sha256_file(real_split_executor),
        "evaluation_cli_sha256": _sha256_file(evaluation_cli),
        "cli_sha256": _sha256_file(cli_path),
        "protocol_py_sha256": _sha256_file(protocol_py),
        "frozen_source_hashes": dict(frozen_protocol["frozen_source_hashes"]),
    }
    _write_json(output_dir / "evaluation_readiness.json", readiness)
    evaluation_readiness_sha256 = _sha256_file(output_dir / "evaluation_readiness.json")

    protocol_freeze_manifest = {
        "schema_name": "protocol_freeze_manifest",
        "schema_version": "3.0.0",
        "generated_at": _utc_now(),
        "freeze_version": "v9",
        "frozen_protocol_path": str(frozen_protocol_path),
        "frozen_protocol_sha256": frozen_protocol_sha256,
        "dataset_freeze_manifest_path": str(dataset_manifest_path),
        "dataset_freeze_manifest_sha256": dataset_freeze_manifest_sha256,
        "evaluation_readiness_path": str(output_dir / "evaluation_readiness.json"),
        "evaluation_readiness_sha256": evaluation_readiness_sha256,
        "initial_execution_state_path": str(output_dir / "initial_execution_state.json"),
        "initial_execution_state_sha256": _sha256_file(output_dir / "initial_execution_state.json"),
        "participant_pool_manifest_sha256": participant_pool_manifest_sha256,
        "registry_sha256": cohort_registry_sha256,
        "eligibility_report_sha256": eligibility_report_sha256,
        "participant_pool_status_sha256": participant_pool_status_sha256,
        "participant_pool_records_sha256": participant_pool_records_sha256,
        "participant_pool_split_index_sha256": participant_pool_split_index_sha256,
        "baseline_backtest_pipeline_sha256": _sha256_file(baseline_pipeline),
        "baseline_backtest_constants_sha256": _sha256_file(baseline_constants),
        "baseline_prediction_normalization_sha256": _sha256_file(baseline_normalization),
        "protocol_rules_sha256": protocol_rules_sha256,
        "split_evaluator_sha256": _sha256_file(split_evaluator),
        "real_split_executor_sha256": _sha256_file(real_split_executor),
        "evaluation_cli_sha256": _sha256_file(evaluation_cli),
        "cli_sha256": _sha256_file(cli_path),
        "protocol_py_sha256": _sha256_file(protocol_py),
        "development_fold_ids": list(eligible_fold_ids_by_split["development"]),
        "validation_fold_ids": list(eligible_fold_ids_by_split["validation"]),
        "holdout_fold_ids": list(eligible_fold_ids_by_split["holdout"]),
        "model_source_sha256s": model_source_sha256s,
        "frozen_source_hashes": dict(frozen_protocol["frozen_source_hashes"]),
    }
    protocol_freeze_manifest_path = _freeze_manifest_path(output_dir)
    _write_json(protocol_freeze_manifest_path, protocol_freeze_manifest)
    protocol_freeze_manifest_sha256 = _sha256_file(protocol_freeze_manifest_path)

    validation_checks = [
        {"check": "frozen_protocol_status", "passed": frozen_protocol["evaluation_protocol_status"] == "frozen"},
        {"check": "protocol_hash_bound", "passed": protocol_freeze_manifest["frozen_protocol_sha256"] == frozen_protocol_sha256},
        {"check": "dataset_manifest_hash_bound", "passed": protocol_freeze_manifest["dataset_freeze_manifest_sha256"] == dataset_freeze_manifest_sha256},
        {"check": "readiness_hash_bound", "passed": protocol_freeze_manifest["evaluation_readiness_sha256"] == evaluation_readiness_sha256},
        {"check": "initial_execution_state_hash_bound", "passed": protocol_freeze_manifest["initial_execution_state_sha256"] == _sha256_file(output_dir / "initial_execution_state.json")},
        {"check": "protocol_rules_hash_bound", "passed": protocol_freeze_manifest["protocol_rules_sha256"] == protocol_rules_sha256},
        {"check": "split_evaluator_hash_bound", "passed": protocol_freeze_manifest["split_evaluator_sha256"] == _sha256_file(split_evaluator)},
        {"check": "real_split_executor_hash_bound", "passed": protocol_freeze_manifest["real_split_executor_sha256"] == _sha256_file(real_split_executor)},
        {"check": "frozen_source_hashes_bound", "passed": protocol_freeze_manifest["frozen_source_hashes"] == frozen_protocol["frozen_source_hashes"]},
        {"check": "freeze_manifest_hash_bound", "passed": bool(protocol_freeze_manifest_sha256)},
        {"check": "fold_sets_bound", "passed": all(len(protocol_freeze_manifest[f"{split}_fold_ids"]) == count for split, count in {"development": 17, "validation": 9, "holdout": 10}.items())},
        {"check": "development_only_executes", "passed": bool(frozen_protocol["split_execution_guards"]["development"]) and not bool(frozen_protocol["split_execution_guards"]["validation"]) and not bool(frozen_protocol["split_execution_guards"]["holdout"])},
        {"check": "readiness_locked", "passed": readiness["user_facing_prediction_allowed"] is False and readiness["holdout_locked"] is True and readiness["stage_v"]["allowed"] is False and readiness["stage_h"]["allowed"] is False},
        {"check": "protocol_validation_report_preserved", "passed": str(draft_validation_report.get("schema_name") or "") == "protocol_validation_report"},
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
    _write_json(output_dir / "protocol_validation_report.json", validation_report)

    (output_dir / "phase8a_evaluation_protocol.frozen.md").write_text(
        "\n".join(
            [
                "# Phase 8A Evaluation Protocol Frozen v9",
                "",
                f"- Frozen protocol: `{frozen_protocol_path.name}`",
                f"- Protocol SHA-256: `{frozen_protocol_sha256}`",
                f"- Development folds: `{len(protocol_freeze_manifest['development_fold_ids'])}`",
                f"- Validation folds: `{len(protocol_freeze_manifest['validation_fold_ids'])}`",
                f"- Holdout folds: `{len(protocol_freeze_manifest['holdout_fold_ids'])}`",
                "- Development is the only split that may pass execution checks in this frozen state.",
                "- Validation and holdout remain locked.",
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
            + [f"- {check['check']}: {'PASS' if check['passed'] else 'FAIL'}" for check in validation_checks]
            + [
                "",
                "## Summary",
                f"- passed: `{validation_report['summary']['passed']}`",
                f"- failed: `{validation_report['summary']['failed']}`",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "frozen_protocol": frozen_protocol,
        "protocol_freeze_manifest": protocol_freeze_manifest,
        "dataset_freeze_manifest": dataset_manifest,
        "evaluation_readiness": readiness,
        "initial_execution_state": initial_execution_state,
        "validation_report": validation_report,
    }
