"""Bundle-first single-use Phase 8A validation executor."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .protocol_rules import build_metric_summary, evaluate_validation_gate
from .real_split_executor import (
    _build_development_targets_from_pool,
    _load_local_identity_denylist,
    _load_mapping,
    _load_participant_records,
    _model_row_from_prediction,
    _predict_with_variant,
    _scan_privacy_artifacts,
    _sha256_file,
    _sha256_json,
    _utc_now,
    _write_json,
)
from .validation import ValidationError


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_name": "validation_execution_report", "split_name": "validation", "execution_allowed": False, "prediction_invocations": 0, "blocked_reason": reason}


def _load_context(bundle: Path, pool: Path) -> dict[str, Any]:
    manifest = _load_mapping(bundle / "protocol_freeze_manifest.json")
    protocol = _load_mapping(bundle / "phase8a_evaluation_protocol.frozen.json")
    state = _load_mapping(bundle / "initial_execution_state.json")
    decision = _load_mapping(bundle / "development_decision.frozen.json")
    if manifest.get("freeze_version") != "v11" or protocol.get("freeze_version") != "v11":
        raise ValidationError("validation_requires_v11")
    bound = {
        "frozen_protocol_sha256": bundle / "phase8a_evaluation_protocol.frozen.json",
        "dataset_freeze_manifest_sha256": bundle / "dataset_freeze_manifest.json",
        "evaluation_readiness_sha256": bundle / "evaluation_readiness.json",
        "initial_execution_state_sha256": bundle / "initial_execution_state.json",
        "development_decision_frozen_sha256": bundle / "development_decision.frozen.json",
        "participant_pool_manifest_sha256": pool / "participant_pool_manifest.json",
        "participant_pool_status_sha256": pool / "participant_pool_status.json",
        "participant_pool_records_sha256": pool / "participant_pool_records.anonymized.json",
        "participant_pool_split_index_sha256": pool / "participant_pool_split_index.json",
        "eligibility_report_sha256": pool / "eligibility_report.json",
        "baseline_backtest_pipeline_sha256": Path("baseline_backtest/pipeline.py"),
        "baseline_backtest_constants_sha256": Path("baseline_backtest/constants.py"),
        "baseline_prediction_normalization_sha256": Path("baseline_prediction/normalization.py"),
        "protocol_rules_sha256": Path("backtest_dataset/protocol_rules.py"),
        "real_split_executor_sha256": Path("backtest_dataset/real_split_executor.py"),
        "validation_executor_sha256": Path("backtest_dataset/validation_executor.py"),
        "cli_sha256": Path("backtest_dataset/cli.py"),
        "evaluation_cli_sha256": Path("backtest_dataset/evaluation_cli.py"),
    }
    for key, path in bound.items():
        if not path.exists() or manifest.get(key) != _sha256_file(path):
            raise ValidationError(f"validation_hash_mismatch:{key}")
    registry = Path(str(protocol["pool_binding"]["cohort_registry_path"]))
    if manifest.get("registry_sha256") != _sha256_file(registry):
        raise ValidationError("validation_hash_mismatch:registry_sha256")
    if state.get("development_decision_frozen") is not True or state.get("validation_status") != "ready_not_run":
        raise ValidationError("validation_previous_stage_not_ready")
    if decision.get("candidate_for_validation") != "full" or decision.get("distance_only_comparator_frozen") is not True:
        raise ValidationError("validation_candidate_binding_mismatch")
    if state.get("holdout_status") != "locked" or state.get("unique_candidate_frozen") is not False:
        raise ValidationError("holdout_boundary_invalid")
    folds = list(manifest.get("validation_fold_ids") or [])
    if folds != list(protocol["execution_locks"]["validation"]["frozen_fold_ids"]) or len(folds) != 9 or len(set(folds)) != 9:
        raise ValidationError("validation_fold_binding_mismatch")
    pool_manifest = _load_mapping(pool / "participant_pool_manifest.json")
    eligibility = _load_mapping(pool / "eligibility_report.json")
    source_by_runner = {str(x["pseudonymous_runner_id"]): dict(x) for x in pool_manifest["source_inventory"]}
    rows = [dict(x) for x in eligibility["fold_rows"] if x.get("fold_status") == "usable" and x.get("fold_cohort") == "real" and source_by_runner.get(str(x.get("pseudonymous_runner_id")), {}).get("assigned_split") == "validation"]
    current = [str(x["fold_id"]) for x in rows]
    if current != folds:
        raise ValidationError("validation_current_folds_mismatch")
    participants = sorted({source_by_runner[str(x["pseudonymous_runner_id"])]["participant_reference"] for x in rows})
    if participants != ["P-0004", "P-0008"]:
        raise ValidationError("validation_participant_set_mismatch")
    return {"manifest": manifest, "protocol": protocol, "state": state, "decision": decision, "folds": folds, "pool_manifest": pool_manifest, "source_by_runner": source_by_runner, "rows": rows}


def _authorize(path: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    auth = _load_mapping(path)
    if auth.get("schema_name") != "validation_execution_authorization" or auth.get("split") != "validation" or auth.get("approved") is not True or auth.get("single_use") is not True:
        raise ValidationError("validation_authorization_invalid")
    if auth.get("authorized_by") != "user_explicit_approval" or not auth.get("authorized_at"):
        raise ValidationError("validation_authorization_provenance_invalid")
    if auth.get("frozen_protocol_sha256") != ctx["manifest"]["frozen_protocol_sha256"] or auth.get("dataset_freeze_manifest_sha256") != ctx["manifest"]["dataset_freeze_manifest_sha256"] or auth.get("development_decision_frozen_sha256") != ctx["manifest"]["development_decision_frozen_sha256"]:
        raise ValidationError("validation_authorization_hash_mismatch")
    if auth.get("candidate_model") != "full" or auth.get("comparator_model") != "distance_only":
        raise ValidationError("validation_authorization_candidate_mismatch")
    folds = list(auth.get("validation_fold_ids") or [])
    if folds != ctx["folds"] or auth.get("validation_fold_ids_sha256") != _sha256_json(folds):
        raise ValidationError("validation_authorization_fold_mismatch")
    run_id = str(auth.get("run_id") or "")
    if not run_id:
        raise ValidationError("validation_authorization_run_id_missing")
    return {**auth, "authorization_sha256": _sha256_file(path)}


def run_bundle_first_validation(*, frozen_bundle_dir: Path, participant_pool_dir: Path, authorization_path: Path, output_root: Path) -> dict[str, Any]:
    try:
        ctx = _load_context(frozen_bundle_dir.resolve(), participant_pool_dir.resolve())
        auth = _authorize(authorization_path, ctx)
    except ValidationError as exc:
        return _blocked(str(exc))
    output_root.mkdir(parents=True, exist_ok=True)
    ledger_path = output_root / "validation_execution_ledger.json"
    ledger = _load_mapping(ledger_path) if ledger_path.exists() else {"schema_name": "validation_execution_ledger", "run_ids": [], "entries": []}
    run_id = auth["run_id"]
    if run_id in ledger["run_ids"]:
        return _blocked("validation_run_id_already_consumed")
    lock_dir = output_root / ".validation-run-locks"; lock_dir.mkdir(exist_ok=True)
    lock_path = lock_dir / f"{run_id}.lock"
    try:
        with lock_path.open("x", encoding="utf-8") as handle:
            json.dump({"run_id": run_id, "status": "reserved", "authorization_sha256": auth["authorization_sha256"]}, handle)
    except FileExistsError:
        return _blocked("validation_run_id_already_reserved")
    entry = {"run_id": run_id, "status": "reserved", "reserved_at": _utc_now(), "authorization_sha256": auth["authorization_sha256"]}
    ledger["run_ids"].append(run_id); ledger["entries"].append(entry); _write_json(ledger_path, ledger)
    try:
        records = _load_participant_records(participant_pool_dir=participant_pool_dir)
        pool_context = {"source_by_runner": ctx["source_by_runner"], "records_by_participant": records, "development_fold_rows": ctx["rows"]}
        targets = _build_development_targets_from_pool(bundle_context=ctx, pool_context=pool_context)
        for target in targets:
            target["split"] = "validation"
        if [x["fold_id"] for x in targets] != ctx["folds"]:
            raise ValidationError("validation_built_folds_mismatch")
        hashes = {"frozen_protocol": ctx["manifest"]["frozen_protocol_sha256"], "validation_executor": ctx["manifest"]["validation_executor_sha256"]}
        full_rows = []; comparator_rows = []
        for target in targets:
            prior = [dict(x) for x in target["prior_history_rows"]]
            full_rows.append(_model_row_from_prediction(target=target, prediction=_predict_with_variant(target=target, prior_rows=prior, variant="full"), variant="full", source_hashes=hashes))
            comparator_rows.append(_model_row_from_prediction(target=target, prediction=_predict_with_variant(target=target, prior_rows=prior, variant="distance_only"), variant="distance_only", source_hashes=hashes))
        full_metrics = build_metric_summary(full_rows, expected_fold_ids=ctx["folds"]); comparator_metrics = build_metric_summary(comparator_rows, expected_fold_ids=ctx["folds"])
        full_metrics["leak_checks_passed"] = all(x["leak_check_snapshot"]["history_before_target_only"] for x in full_rows)
        comparator_metrics["leak_checks_passed"] = all(x["leak_check_snapshot"]["history_before_target_only"] for x in comparator_rows)
        gate = evaluate_validation_gate(full_metrics=full_metrics, distance_only_metrics=comparator_metrics, frozen_validation_fold_ids=ctx["folds"])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"); final = output_root / f"phase8a-frozen-validation-{stamp}"
        with tempfile.TemporaryDirectory(dir=output_root) as tmp:
            td = Path(tmp)
            authorization_path_bytes = authorization_path.read_bytes(); (td / "execution_authorization.snapshot.json").write_bytes(authorization_path_bytes)
            artifacts = {
                "full_prediction_rows.json": full_rows,
                "distance_only_prediction_rows.json": comparator_rows,
                "validation_metrics.json": {"full": full_metrics, "distance_only": comparator_metrics},
                "validation_gate_decision.json": gate,
                "validation_execution_report.json": {"schema_name": "validation_execution_report", "split_name": "validation", "execution_allowed": True, "run_id": run_id, "prediction_invocations": 18, "gate_passed": gate["passed"]},
                "execution_state_after.json": {"validation_status": "completed", "validation_run_count": 1, "holdout_status": "locked", "holdout_run_count": 0, "unique_candidate_frozen": False, "user_facing_prediction_allowed": False},
            }
            for name, value in artifacts.items(): _write_json(td / name, value)
            scan = _scan_privacy_artifacts(td, identity_denylist=_load_local_identity_denylist()); _write_json(td / "privacy_scan.json", scan)
            if not scan["passed"]: raise ValidationError("validation_privacy_scan_failed")
            td.replace(final)
        entry.update({"status": "completed", "completed_at": _utc_now(), "result_dir": str(final), "gate_passed": gate["passed"]}); _write_json(ledger_path, ledger)
        _write_json(lock_path, {"run_id": run_id, "status": "completed", "result_dir": str(final)})
        return {"schema_name": "validation_execution_report", "split_name": "validation", "execution_allowed": True, "prediction_invocations": 18, "output_dir": str(final), "gate": gate}
    except Exception as exc:
        entry.update({"status": "failed", "failed_at": _utc_now(), "failure_reason": str(exc)}); _write_json(ledger_path, ledger); _write_json(lock_path, {"run_id": run_id, "status": "failed"})
        return _blocked(str(exc))
