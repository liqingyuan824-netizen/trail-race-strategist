"""Fail-closed Phase 8A final closeout after a completed validation run.

This module never invokes a model or a split executor.  It only verifies and
binds already-written frozen/evaluation evidence.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .real_split_executor import (
    _load_local_identity_denylist,
    _load_mapping,
    _scan_privacy_artifacts,
    _sha256_file,
    _write_json,
)
from .validation import ValidationError
from .validation_executor import _load_context


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValidationError(reason)


def _aggregate_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    coverage = metrics.get("coverage") or {}
    return {
        "runner_macro_mdape": metrics.get("runner_macro_mdape"),
        "pooled_mdape": metrics.get("pooled_mdape"),
        "mae_minutes": metrics.get("mae_minutes"),
        "signed_bias_minutes": metrics.get("signed_bias_minutes"),
        "prediction_count": metrics.get("prediction_count"),
        "prediction_completeness": metrics.get("prediction_completeness"),
        "coverage": {
            "optimistic": coverage.get("optimistic"),
            "baseline": coverage.get("baseline"),
            "conservative": coverage.get("conservative"),
        },
    }


def build_phase8a_final_closeout(
    *,
    frozen_bundle_dir: Path,
    participant_pool_dir: Path,
    validation_result_dir: Path,
    validation_ledger_path: Path,
    test_evidence_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Close Phase 8A from immutable evidence without running a new split."""

    bundle = frozen_bundle_dir.resolve()
    pool = participant_pool_dir.resolve()
    result = validation_result_dir.resolve()
    ledger_path = validation_ledger_path.resolve()
    test_path = test_evidence_path.resolve()
    output = output_dir.resolve()
    _require(not output.exists(), "closeout_output_already_exists")

    ctx = _load_context(bundle, pool)
    report = _load_mapping(result / "validation_execution_report.json")
    gate = _load_mapping(result / "validation_gate_decision.json")
    metrics = _load_mapping(result / "validation_metrics.json")
    state = _load_mapping(result / "execution_state_after.json")
    privacy = _load_mapping(result / "privacy_scan.json")
    ledger = _load_mapping(ledger_path)
    test_evidence = _load_mapping(test_path)

    run_id = str(report.get("run_id") or "")
    entries = [entry for entry in ledger.get("entries", []) if entry.get("run_id") == run_id]
    _require(report.get("execution_allowed") is True, "closeout_validation_not_executed")
    _require(report.get("prediction_invocations") == 18, "closeout_prediction_count_mismatch")
    _require(report.get("gate_passed") is False, "closeout_requires_failed_validation_gate")
    _require(gate.get("passed") is False and gate.get("decision") == "retain_distance_only", "closeout_gate_decision_mismatch")
    _require(gate.get("input_gate_passed") is True, "closeout_input_gate_failed")
    _require(len(gate.get("frozen_validation_fold_ids") or []) == 9, "closeout_fold_count_mismatch")
    _require(gate.get("full_fold_ids") == gate.get("frozen_validation_fold_ids"), "closeout_full_fold_binding_mismatch")
    _require(gate.get("distance_only_fold_ids") == gate.get("frozen_validation_fold_ids"), "closeout_comparator_fold_binding_mismatch")
    _require(state.get("validation_status") == "completed" and state.get("validation_run_count") == 1, "closeout_validation_state_mismatch")
    _require(state.get("holdout_status") == "locked" and state.get("holdout_run_count") == 0, "closeout_holdout_boundary_invalid")
    _require(state.get("unique_candidate_frozen") is False, "closeout_unique_candidate_must_remain_false")
    _require(state.get("user_facing_prediction_allowed") is False, "closeout_user_facing_boundary_invalid")
    _require(privacy.get("passed") is True and privacy.get("hit_count") == 0, "closeout_source_privacy_failed")
    _require(len(entries) == 1 and entries[0].get("status") == "completed", "closeout_ledger_entry_invalid")
    _require(entries[0].get("gate_passed") is False, "closeout_ledger_gate_mismatch")
    _require(test_evidence.get("full_suite_passed") is True, "closeout_tests_not_passed")

    result_files = [
        "validation_execution_report.json",
        "validation_gate_decision.json",
        "validation_metrics.json",
        "execution_state_after.json",
        "privacy_scan.json",
        "full_prediction_rows.json",
        "distance_only_prediction_rows.json",
        "execution_authorization.snapshot.json",
    ]
    result_hashes = {name: _sha256_file(result / name) for name in result_files}
    source_bindings = {
        "frozen_bundle_path": str(bundle),
        "frozen_protocol_sha256": ctx["manifest"]["frozen_protocol_sha256"],
        "protocol_freeze_manifest_sha256": _sha256_file(bundle / "protocol_freeze_manifest.json"),
        "dataset_freeze_manifest_sha256": ctx["manifest"]["dataset_freeze_manifest_sha256"],
        "development_decision_frozen_sha256": ctx["manifest"]["development_decision_frozen_sha256"],
        "validation_result_path": str(result),
        "validation_result_hashes": result_hashes,
        "validation_ledger_path": str(ledger_path),
        "validation_ledger_sha256": _sha256_file(ledger_path),
        "test_evidence_path": str(test_path),
        "test_evidence_sha256": _sha256_file(test_path),
        "test_source_sha256": _sha256_file(Path("tests/test_phase8a_final_closeout.py")),
    }
    closeout_state = {
        "schema_name": "phase8a_final_closeout_state",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "phase": "Phase 8A",
        "status": "closed_after_failed_validation",
        "validation_gate_passed": False,
        "validation_decision": "retain_distance_only",
        "full_model_status": "rejected",
        "retained_reference_model": "distance_only",
        "holdout_status": "permanently_not_entered_for_this_protocol_and_cohort",
        "holdout_evaluation_run": False,
        "holdout_run_count": 0,
        "unique_candidate_frozen": False,
        "model_validated": False,
        "user_facing_prediction_allowed": False,
        "future_reevaluation_requires_new_data_and_new_protocol": True,
        "phase9_entered": False,
    }
    public_summary = {
        "schema_name": "phase8a_public_aggregate_closeout_summary",
        "schema_version": "1.0.0",
        "classification": "public_aggregate_only",
        "phase": "Phase 8A",
        "status": "closed_after_failed_validation",
        "validation_fold_count": 9,
        "validation_gate_passed": False,
        "validation_decision": "retain_distance_only",
        "full_model_status": "rejected",
        "retained_reference_model": "distance_only",
        "aggregate_metrics": {
            "full": _aggregate_metrics(metrics["full"]),
            "distance_only": _aggregate_metrics(metrics["distance_only"]),
        },
        "gate_checks": [
            {"check": item.get("check"), "passed": item.get("passed")}
            for item in gate.get("checks", [])
        ],
        "holdout_evaluation_run": False,
        "user_facing_prediction_allowed": False,
        "future_reevaluation_requires_new_data_and_new_protocol": True,
    }
    _require(not any(key in json.dumps(public_summary, ensure_ascii=False).lower() for key in ("runner_reference", "fold_id", "provided_name", "itra_id", "identity_map")), "closeout_public_summary_not_aggregate_only")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        temp_dir = Path(temporary)
        _write_json(temp_dir / "phase8a_final_closeout_state.json", closeout_state)
        _write_json(temp_dir / "phase8a_public_aggregate_summary.json", public_summary)
        _write_json(temp_dir / "source_bindings.json", source_bindings)
        manifest = {
            "schema_name": "phase8a_final_closeout_manifest",
            "schema_version": "1.0.0",
            "generated_at": _utc_now(),
            "closeout_state_sha256": _sha256_file(temp_dir / "phase8a_final_closeout_state.json"),
            "public_aggregate_summary_sha256": _sha256_file(temp_dir / "phase8a_public_aggregate_summary.json"),
            "source_bindings_sha256": _sha256_file(temp_dir / "source_bindings.json"),
            "source_bindings": source_bindings,
        }
        _write_json(temp_dir / "phase8a_final_closeout_manifest.json", manifest)
        scan = _scan_privacy_artifacts(temp_dir, identity_denylist=_load_local_identity_denylist())
        _require(scan.get("passed") is True, "closeout_privacy_scan_failed")
        _write_json(temp_dir / "privacy_scan.json", scan)
        temp_dir.replace(output)

    pointer_payload = {
        "schema_name": "phase8a_closeout_status_pointer",
        "schema_version": "1.0.0",
        "status": "closed_after_failed_validation",
        "closeout_bundle_path": str(output),
        "closeout_manifest_sha256": _sha256_file(output / "phase8a_final_closeout_manifest.json"),
        "source_artifacts_preserved_unmodified": True,
    }
    pointer_tag = output.name
    pointer_dir = output.parent / "phase8a-closeout-status-pointers" / pointer_tag
    pointer_dir.mkdir(parents=True, exist_ok=False)
    bundle_pointer = pointer_dir / "frozen_protocol_v11.json"
    result_pointer = pointer_dir / "validation_result.json"
    _require(not bundle_pointer.exists() and not result_pointer.exists(), "closeout_pointer_already_exists")
    _write_json(bundle_pointer, {**pointer_payload, "source_kind": "frozen_protocol_v11", "source_path": str(bundle)})
    _write_json(result_pointer, {**pointer_payload, "source_kind": "validation_result", "source_path": str(result)})
    return {
        "output_dir": output,
        "manifest": manifest,
        "closeout_state": closeout_state,
        "public_summary": public_summary,
        "privacy_scan": scan,
        "bundle_pointer": bundle_pointer,
        "result_pointer": result_pointer,
    }
