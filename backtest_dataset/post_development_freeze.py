"""Freeze the audited development result before any validation authorization."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .protocol_freeze import _bundle_source_hashes
from .validation import ValidationError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, Mapping):
        raise ValidationError(f"{path.name}:expected_json_object")
    return dict(value)


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build_post_development_frozen_bundle(
    *, prior_bundle_dir: Path, development_result_dir: Path, output_dir: Path
) -> dict[str, Any]:
    prior_bundle_dir, development_result_dir = prior_bundle_dir.resolve(), development_result_dir.resolve()
    prior_protocol = _load(prior_bundle_dir / "phase8a_evaluation_protocol.frozen.json")
    prior_manifest = _load(prior_bundle_dir / "protocol_freeze_manifest.json")
    prior_dataset = _load(prior_bundle_dir / "dataset_freeze_manifest.json")
    report = _load(development_result_dir / "development_execution_report.json")
    metrics = _load(development_result_dir / "development_metrics.json")
    state = _load(development_result_dir / "execution_state_after.json")
    privacy = _load(development_result_dir / "privacy_scan.json")
    decision = _load(development_result_dir / "development_decision.json")
    if prior_protocol.get("freeze_version") != "v9" or prior_manifest.get("freeze_version") != "v9":
        raise ValidationError("post_development_prior_bundle_not_v9")
    if report.get("execution_allowed") is not True or state.get("development_status") != "completed":
        raise ValidationError("development_not_completed")
    if privacy.get("passed") is not True or privacy.get("public_export_allowed") is not False:
        raise ValidationError("development_privacy_not_ready")
    if decision.get("candidate_for_validation") != "full":
        raise ValidationError("development_candidate_not_full")
    if report.get("run_id") != state.get("last_run_id") or report.get("prediction_invocations") != 34:
        raise ValidationError("development_execution_identity_mismatch")

    output_dir.mkdir(parents=True, exist_ok=False)
    source_hashes = _bundle_source_hashes()
    decision_frozen = copy.deepcopy(decision)
    decision_frozen.update(
        {
            "schema_name": "development_decision_frozen",
            "schema_version": "1.0.0",
            "frozen_at": _now(),
            "development_completed": True,
            "development_decision_frozen": True,
            "candidate_for_validation": "full",
            "candidate_model_source_sha256s": [
                prior_manifest["baseline_backtest_pipeline_sha256"],
                prior_manifest["baseline_backtest_constants_sha256"],
                prior_manifest["baseline_prediction_normalization_sha256"],
            ],
            "distance_only_comparator_frozen": True,
            "distance_only_is_tunable_candidate": False,
            "unique_candidate_frozen": False,
            "validation_unlock_approved": False,
            "validation_allowed": False,
            "holdout_allowed": False,
            "source_development_metrics_sha256": _hash(development_result_dir / "development_metrics.json"),
            "source_development_report_sha256": _hash(development_result_dir / "development_execution_report.json"),
            "source_privacy_scan_sha256": _hash(development_result_dir / "privacy_scan.json"),
        }
    )
    decision_path = output_dir / "development_decision.frozen.json"
    _write(decision_path, decision_frozen)
    decision_hash = _hash(decision_path)

    protocol = copy.deepcopy(prior_protocol)
    protocol["freeze_version"] = "v10"
    protocol["development_evidence_binding"] = {
        "run_id": report["run_id"],
        "development_result_dir": str(development_result_dir),
        "development_execution_report_sha256": _hash(development_result_dir / "development_execution_report.json"),
        "development_metrics_sha256": _hash(development_result_dir / "development_metrics.json"),
        "development_privacy_scan_sha256": _hash(development_result_dir / "privacy_scan.json"),
        "development_decision_frozen_sha256": decision_hash,
    }
    protocol["frozen_source_hashes"] = {**source_hashes, "post_development_freeze_sha256": _hash(Path(__file__))}
    protocol["stage_boundaries"]["stage_d"].update({"allowed": False, "development_completed": True})
    protocol["stage_boundaries"]["stage_v"].update(
        {"allowed": True, "status": "ready_not_run", "validation_unlock_approved": False, "approval": False}
    )
    protocol["stage_boundaries"]["stage_h"].update(
        {"allowed": False, "status": "locked", "holdout_unlock_approved": False, "approval": False}
    )
    protocol["execution_locks"]["validation"].update(
        {
            "stage_allowed": True,
            "previous_stage_ready": True,
            "development_completed": True,
            "development_decision_frozen": True,
            "validation_unlock_approved": False,
            "validation_executed_once": False,
        }
    )
    protocol["execution_locks"]["holdout"].update(
        {"stage_allowed": False, "validation_completed": False, "unique_candidate_frozen": False, "holdout_unlock_approved": False}
    )
    protocol["split_execution_guards"] = {"development": False, "validation": False, "holdout": False}
    protocol["governance"].update(
        {"development_evaluation_run": True, "validation_evaluation_run": False, "holdout_evaluation_run": False, "model_validated": False, "user_facing_prediction_allowed": False}
    )
    protocol_path = output_dir / "phase8a_evaluation_protocol.frozen.json"
    _write(protocol_path, protocol)
    protocol_hash = _hash(protocol_path)

    initial_state = {
        "schema_name": "post_development_execution_state",
        "schema_version": "1.0.0",
        "generated_at": _now(),
        "development_status": "completed",
        "development_run_count": 1,
        "development_decision_frozen": True,
        "candidate_for_validation": "full",
        "distance_only_comparator_frozen": True,
        "validation_status": "ready_not_run",
        "validation_unlock_approved": False,
        "validation_run_count": 0,
        "holdout_status": "locked",
        "holdout_run_count": 0,
        "unique_candidate_frozen": False,
        "model_validated": False,
        "user_facing_prediction_allowed": False,
    }
    _write(output_dir / "initial_execution_state.json", initial_state)

    dataset = copy.deepcopy(prior_dataset)
    dataset.update(
        {
            "freeze_version": "v10",
            "generated_at": _now(),
            "frozen_protocol_sha256": protocol_hash,
            "development_decision_frozen_sha256": decision_hash,
            "frozen_source_hashes": protocol["frozen_source_hashes"],
        }
    )
    dataset_path = output_dir / "dataset_freeze_manifest.json"
    _write(dataset_path, dataset)
    dataset_hash = _hash(dataset_path)

    readiness = {
        "schema_name": "evaluation_readiness",
        "schema_version": "4.0.0",
        "generated_at": _now(),
        "evaluation_protocol_status": "frozen",
        "development_evaluation_run": True,
        "development_decision_frozen": True,
        "candidate_for_validation": "full",
        "validation_evaluation_run": False,
        "holdout_evaluation_run": False,
        "model_validated": False,
        "user_facing_prediction_allowed": False,
        "stage_d": {"allowed": False, "status": "completed"},
        "stage_v": {"allowed": True, "status": "ready_not_run", "validation_unlock_approved": False, "approval": False},
        "stage_h": {"allowed": False, "status": "locked", "holdout_unlock_approved": False, "approval": False},
        "frozen_protocol_sha256": protocol_hash,
        "dataset_freeze_manifest_sha256": dataset_hash,
        "development_decision_frozen_sha256": decision_hash,
    }
    _write(output_dir / "evaluation_readiness.json", readiness)

    manifest = copy.deepcopy(prior_manifest)
    manifest.update(
        {
            "schema_version": "4.0.0",
            "generated_at": _now(),
            "freeze_version": "v10",
            "frozen_protocol_path": str(protocol_path),
            "frozen_protocol_sha256": protocol_hash,
            "dataset_freeze_manifest_path": str(dataset_path),
            "dataset_freeze_manifest_sha256": dataset_hash,
            "evaluation_readiness_path": str(output_dir / "evaluation_readiness.json"),
            "evaluation_readiness_sha256": _hash(output_dir / "evaluation_readiness.json"),
            "initial_execution_state_path": str(output_dir / "initial_execution_state.json"),
            "initial_execution_state_sha256": _hash(output_dir / "initial_execution_state.json"),
            "development_decision_frozen_sha256": decision_hash,
            "development_execution_report_sha256": protocol["development_evidence_binding"]["development_execution_report_sha256"],
            "development_metrics_sha256": protocol["development_evidence_binding"]["development_metrics_sha256"],
            "development_privacy_scan_sha256": protocol["development_evidence_binding"]["development_privacy_scan_sha256"],
            "real_split_executor_sha256": source_hashes["backtest_dataset_real_split_executor_py_sha256"],
            "cli_sha256": source_hashes["backtest_dataset_cli_py_sha256"],
            "evaluation_cli_sha256": source_hashes["backtest_dataset_evaluation_cli_py_sha256"],
            "frozen_source_hashes": protocol["frozen_source_hashes"],
        }
    )
    _write(output_dir / "protocol_freeze_manifest.json", manifest)
    validation_report = {
        "schema_name": "post_development_freeze_validation_report",
        "schema_version": "1.0.0",
        "generated_at": _now(),
        "passed": True,
        "checks": [
            "development_completed",
            "development_decision_frozen",
            "full_candidate_bound",
            "distance_only_comparator_bound",
            "validation_ready_not_run_unapproved",
            "holdout_locked",
            "unique_candidate_not_prematurely_frozen",
        ],
    }
    _write(output_dir / "protocol_validation_report.json", validation_report)
    (output_dir / "phase8a_evaluation_protocol.frozen.md").write_text(
        "# Phase 8A Post-development Frozen v10\n\n- Candidate for validation: `full`\n- Validation: `ready_not_run`, approval required\n- Holdout: `locked`\n- User-facing prediction: `false`\n",
        encoding="utf-8",
    )
    return {"protocol": protocol, "manifest": manifest, "decision": decision_frozen, "readiness": readiness}


def build_validation_authorization_template(*, frozen_bundle_dir: Path, output_root: Path) -> dict[str, Any]:
    protocol = _load(frozen_bundle_dir / "phase8a_evaluation_protocol.frozen.json")
    manifest = _load(frozen_bundle_dir / "protocol_freeze_manifest.json")
    state = _load(frozen_bundle_dir / "initial_execution_state.json")
    if protocol.get("freeze_version") not in {"v10", "v11"} or manifest.get("freeze_version") not in {"v10", "v11"}:
        raise ValidationError("validation_template_requires_post_development_bundle")
    folds = list(manifest.get("validation_fold_ids") or [])
    if folds != list(protocol["execution_locks"]["validation"]["frozen_fold_ids"]) or len(folds) != 9 or len(set(folds)) != 9:
        raise ValidationError("validation_frozen_fold_ids_mismatch")
    if state.get("development_decision_frozen") is not True or state.get("validation_status") != "ready_not_run":
        raise ValidationError("validation_previous_stage_not_frozen")
    template = {
        "schema_name": "validation_execution_authorization",
        "schema_version": "1.0.0",
        "split": "validation",
        "run_id": str(uuid.uuid4()),
        "approved": False,
        "single_use": True,
        "authorized_at": None,
        "authorized_by": "user_explicit_approval",
        "frozen_protocol_sha256": manifest["frozen_protocol_sha256"],
        "dataset_freeze_manifest_sha256": manifest["dataset_freeze_manifest_sha256"],
        "development_decision_frozen_sha256": manifest["development_decision_frozen_sha256"],
        "candidate_model": "full",
        "comparator_model": "distance_only",
        "validation_fold_ids": folds,
        "validation_fold_ids_sha256": hashlib.sha256(json.dumps(folds, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "authorization_sha256": None,
        "notes": "template only; validation remains locked until explicit approval",
    }
    output_root.mkdir(parents=True, exist_ok=False)
    path = output_root / "validation_execution_authorization.template.json"
    _write(path, template)
    return {"authorization_template": template, "template_path": path}


def build_validation_ready_v11_bundle(*, prior_bundle_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Rebind the post-development state to the production validation executor."""
    prior_bundle_dir = prior_bundle_dir.resolve()
    protocol = _load(prior_bundle_dir / "phase8a_evaluation_protocol.frozen.json")
    manifest = _load(prior_bundle_dir / "protocol_freeze_manifest.json")
    dataset = _load(prior_bundle_dir / "dataset_freeze_manifest.json")
    readiness = _load(prior_bundle_dir / "evaluation_readiness.json")
    state = _load(prior_bundle_dir / "initial_execution_state.json")
    decision = _load(prior_bundle_dir / "development_decision.frozen.json")
    if protocol.get("freeze_version") != "v10" or state.get("validation_status") != "ready_not_run":
        raise ValidationError("validation_v11_prior_state_invalid")
    output_dir.mkdir(parents=True, exist_ok=False)
    source_hashes = _bundle_source_hashes()
    validation_executor_hash = _hash(Path("backtest_dataset/validation_executor.py"))
    post_freeze_hash = _hash(Path(__file__))
    protocol["freeze_version"] = "v11"
    protocol["frozen_source_hashes"] = {**source_hashes, "validation_executor_sha256": validation_executor_hash, "post_development_freeze_sha256": post_freeze_hash}
    protocol["execution_locks"]["validation"].update({"validation_executor_sha256": validation_executor_hash, "validation_unlock_approved": False, "validation_executed_once": False})
    protocol_path = output_dir / "phase8a_evaluation_protocol.frozen.json"; _write(protocol_path, protocol); protocol_hash = _hash(protocol_path)
    decision_path = output_dir / "development_decision.frozen.json"; _write(decision_path, decision); decision_hash = _hash(decision_path)
    state["generated_at"] = _now(); _write(output_dir / "initial_execution_state.json", state)
    dataset.update({"freeze_version": "v11", "generated_at": _now(), "frozen_protocol_sha256": protocol_hash, "development_decision_frozen_sha256": decision_hash, "validation_executor_sha256": validation_executor_hash, "frozen_source_hashes": protocol["frozen_source_hashes"]})
    dataset_path = output_dir / "dataset_freeze_manifest.json"; _write(dataset_path, dataset); dataset_hash = _hash(dataset_path)
    readiness.update({"generated_at": _now(), "frozen_protocol_sha256": protocol_hash, "dataset_freeze_manifest_sha256": dataset_hash, "development_decision_frozen_sha256": decision_hash, "validation_executor_sha256": validation_executor_hash})
    _write(output_dir / "evaluation_readiness.json", readiness)
    manifest.update({
        "freeze_version": "v11", "generated_at": _now(), "frozen_protocol_path": str(protocol_path), "frozen_protocol_sha256": protocol_hash,
        "dataset_freeze_manifest_path": str(dataset_path), "dataset_freeze_manifest_sha256": dataset_hash,
        "evaluation_readiness_path": str(output_dir / "evaluation_readiness.json"), "evaluation_readiness_sha256": _hash(output_dir / "evaluation_readiness.json"),
        "initial_execution_state_path": str(output_dir / "initial_execution_state.json"), "initial_execution_state_sha256": _hash(output_dir / "initial_execution_state.json"),
        "development_decision_frozen_sha256": decision_hash, "validation_executor_sha256": validation_executor_hash,
        "real_split_executor_sha256": source_hashes["backtest_dataset_real_split_executor_py_sha256"], "cli_sha256": source_hashes["backtest_dataset_cli_py_sha256"],
        "evaluation_cli_sha256": source_hashes["backtest_dataset_evaluation_cli_py_sha256"], "frozen_source_hashes": protocol["frozen_source_hashes"],
    })
    _write(output_dir / "protocol_freeze_manifest.json", manifest)
    _write(output_dir / "protocol_validation_report.json", {"schema_name": "validation_ready_v11_report", "passed": True, "checks": ["validation_executor_bound", "validation_unapproved", "holdout_locked"]})
    (output_dir / "phase8a_evaluation_protocol.frozen.md").write_text("# Phase 8A Validation-ready Frozen v11\n\nValidation is ready but unapproved. Holdout remains locked.\n", encoding="utf-8")
    return {"protocol": protocol, "manifest": manifest, "state": state, "decision": decision}
