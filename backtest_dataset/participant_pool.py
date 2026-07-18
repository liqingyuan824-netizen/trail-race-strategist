"""Participant pool builder for merged anonymous participant imports."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .participant_trial import _dedupe_participant_records
from .pipeline import build_dataset_manifest, write_dataset_outputs
from .validation import ValidationError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValidationError(f"{path.name}:expected_json_object")
    return payload


def _load_registry(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path)
    if str(payload.get("schema_name") or "") != "cohort_split_registry":
        raise ValidationError("cohort_registry:unexpected_schema_name")
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise ValidationError("cohort_registry:entries_not_list")
    registry: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValidationError("cohort_registry:entry_not_mapping")
        participant_reference = str(entry.get("participant_reference") or "").strip()
        assigned_split = str(entry.get("assigned_split") or "").strip()
        if not participant_reference:
            raise ValidationError("cohort_registry:participant_reference_required")
        if participant_reference in registry:
            raise ValidationError(f"cohort_registry:duplicate_participant_reference:{participant_reference}")
        if assigned_split not in {"development", "validation", "holdout"}:
            raise ValidationError(f"cohort_registry:invalid_split:{participant_reference}")
        registry[participant_reference] = dict(entry)
    return registry


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_anonymized_payload(path: Path, payload: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if str(payload.get("schema_name") or "") != "participant_records_anonymized":
        raise ValidationError(f"{path.name}:unexpected_schema_name")
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise ValidationError(f"{path.name}:records_not_list")
    participant_reference = str(payload.get("participant_reference") or "")
    pseudonymous_runner_id = str(payload.get("pseudonymous_runner_id") or "")
    if not participant_reference:
        raise ValidationError(f"{path.name}:participant_reference_required")
    if not pseudonymous_runner_id:
        raise ValidationError(f"{path.name}:pseudonymous_runner_id_required")
    for record in records:
        if not isinstance(record, Mapping):
            raise ValidationError(f"{path.name}:record_not_mapping")
        if str(record.get("pseudonymous_runner_id") or "") != pseudonymous_runner_id:
            raise ValidationError(f"{path.name}:runner_id_mismatch")
        for sensitive_field in ("provided_name", "provided_itra_id", "participant_identity_map", "identity_map"):
            if sensitive_field in record:
                raise ValidationError(f"{path.name}:sensitive_field_present:{sensitive_field}")
    return participant_reference, [dict(record) for record in records if isinstance(record, Mapping)]


def _participant_source_inventory(participant_dir: Path, records_file: Path, payload: Mapping[str, Any], record_count: int, unique_count: int) -> dict[str, Any]:
    return {
        "participant_dir": str(participant_dir.resolve()),
        "records_file": str(records_file.resolve()),
        "file_hash": _sha256_file(records_file),
        "participant_reference": str(payload.get("participant_reference") or ""),
        "pseudonymous_runner_id": str(payload.get("pseudonymous_runner_id") or ""),
        "assigned_split": str(payload.get("assigned_split") or ""),
        "record_count": record_count,
        "unique_record_count": unique_count,
    }


def _anonymize_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    anonymized: list[dict[str, Any]] = []
    for record in records:
        anonymized.append(
            {
                "record_id": record.get("record_id"),
                "pseudonymous_runner_id": record.get("pseudonymous_runner_id"),
                "participant_reference": record.get("participant_reference"),
                "assigned_split": record.get("assigned_split"),
                "event_id": record.get("event_id"),
                "event_name": record.get("event_name"),
                "race_date": record.get("race_date"),
                "race_group": record.get("race_group"),
                "distance_km": record.get("distance_km"),
                "elevation_gain_m": record.get("elevation_gain_m"),
                "finish_time_seconds": record.get("finish_time_seconds"),
                "result_status": record.get("result_status"),
                "route_version": record.get("route_version"),
                "data_confidence": record.get("data_confidence"),
                "compliance_status": record.get("compliance_status"),
                "synthetic": bool(record.get("synthetic")),
                "result_status_source": record.get("result_status_source"),
            }
        )
    return anonymized


def _pool_status_payload(
    *,
    participant_count: int,
    manifest: Mapping[str, Any],
    duplicate_records_removed: int,
    split_counts: Mapping[str, int],
    split_folds: Mapping[str, int],
) -> dict[str, Any]:
    real_eligible_folds = int(manifest["dataset"]["real_eligible_folds"])
    synthetic_eligible_folds = int(manifest["dataset"].get("synthetic_eligible_folds", 0))
    return {
        "schema_name": "participant_pool_status",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_count": participant_count,
        "real_runner_count": participant_count,
        "development_runner_count": int(split_counts.get("development", 0)),
        "validation_runner_count": int(split_counts.get("validation", 0)),
        "holdout_runner_count": int(split_counts.get("holdout", 0)),
        "real_eligible_folds": real_eligible_folds,
        "development_eligible_folds": int(split_folds.get("development", 0)),
        "validation_eligible_folds": int(split_folds.get("validation", 0)),
        "holdout_eligible_folds": int(split_folds.get("holdout", 0)),
        "synthetic_eligible_folds": synthetic_eligible_folds,
        "distance_to_30": max(30 - real_eligible_folds, 0),
        "calibration_status": "insufficient_evaluation_data" if real_eligible_folds < 30 else "calibrated_candidate",
        "calibration_allowed": bool(manifest["dataset"].get("calibration_allowed")),
        "user_facing_prediction_allowed": bool(manifest["dataset"].get("user_facing_prediction_allowed")),
        "holdout_locked": True,
        "holdout_model_evaluation_allowed": False,
        "holdout_error_metrics_available": False,
        "duplicate_records_removed": duplicate_records_removed,
    }


def build_participant_pool(*, participant_dirs: Sequence[Path], cohort_registry: Path, output_dir: Path) -> dict[str, Any]:
    if not participant_dirs:
        raise ValidationError("participant_dir_required")
    output_dir.mkdir(parents=True, exist_ok=True)
    registry = _load_registry(cohort_registry)

    raw_records: list[dict[str, Any]] = []
    source_inventory: list[dict[str, Any]] = []
    participant_payloads: list[dict[str, Any]] = []
    split_assignments: dict[str, str] = {}
    participant_refs_by_split: dict[str, set[str]] = {
        "development": set(),
        "validation": set(),
        "holdout": set(),
    }

    for participant_dir in participant_dirs:
        records_file = participant_dir / "participant_records.anonymized.json"
        if not records_file.exists():
            raise ValidationError(f"missing_participant_records:{records_file}")
        payload = _load_json(records_file)
        participant_reference, records = _validate_anonymized_payload(records_file, payload)
        if participant_reference not in registry:
            raise ValidationError(f"cohort_registry_missing_participant_reference:{participant_reference}")
        assigned_split = str(registry[participant_reference].get("assigned_split") or "")
        participant_payload = dict(payload)
        participant_payload["assigned_split"] = assigned_split
        participant_payloads.append(participant_payload)
        split_assignments[participant_reference] = assigned_split
        participant_refs_by_split[assigned_split].add(participant_reference)
        for record in records:
            enriched = dict(record)
            enriched["participant_reference"] = participant_reference
            enriched["assigned_split"] = assigned_split
            raw_records.append(enriched)
        source_inventory.append(
            _participant_source_inventory(
                participant_dir=participant_dir,
                records_file=records_file,
                payload=participant_payload,
                record_count=len(records),
                unique_count=len(records),
            )
        )

    unique_records, dedupe_summary = _dedupe_participant_records(raw_records)
    split_records: dict[str, list[dict[str, Any]]] = {"development": [], "validation": [], "holdout": []}
    for record in unique_records:
        split = str(record.get("assigned_split") or "")
        if split not in split_records:
            raise ValidationError(f"unexpected_assigned_split:{split}")
        split_records[split].append(record)

    split_manifests = {
        split: build_dataset_manifest(records)
        for split, records in split_records.items()
    }
    split_folds = {split: int(split_manifests[split]["dataset"]["real_eligible_folds"]) for split in split_manifests}
    split_counts = {split: len(participant_refs_by_split[split]) for split in participant_refs_by_split}
    split_index_entries = [
        {
            "participant_reference": participant_reference,
            "assigned_split": split_assignments[participant_reference],
            "immutable_assignment": bool(registry[participant_reference].get("immutable_assignment", False)),
        }
        for participant_reference in sorted(split_assignments)
    ]
    participant_records_payload = {
        "schema_name": "participant_pool_records_anonymized",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_count": len(participant_payloads),
        "records": _anonymize_records(unique_records),
        "summary": {
            "raw_record_count": dedupe_summary["input_records"],
            "unique_record_count": dedupe_summary["unique_records"],
            "duplicate_record_count": dedupe_summary["duplicate_records"],
        },
    }
    _write_json(output_dir / "participant_pool_records.anonymized.json", participant_records_payload)
    _write_json(output_dir / "participant_pool_sources.json", source_inventory)
    _write_json(
        output_dir / "participant_pool_split_index.json",
        {
            "schema_name": "participant_pool_split_index",
            "schema_version": "1.0.0",
            "generated_at": _utc_now(),
            "cohort_registry": str(cohort_registry.resolve()),
            "entries": split_index_entries,
        },
    )

    dataset_outputs = write_dataset_outputs(
        records=unique_records,
        output_dir=output_dir,
        source_files=[participant_dir / "participant_records.anonymized.json" for participant_dir in participant_dirs],
    )
    manifest = dataset_outputs["manifest"]
    status_payload = _pool_status_payload(
        participant_count=len(participant_payloads),
        manifest=manifest,
        duplicate_records_removed=int(dedupe_summary["duplicate_records"]),
        split_counts=split_counts,
        split_folds=split_folds,
    )
    pool_manifest = {
        "schema_name": "participant_pool_manifest",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_count": len(participant_payloads),
        "cohort_registry": str(cohort_registry.resolve()),
        "holdout_locked": True,
        "holdout_model_evaluation_allowed": False,
        "holdout_error_metrics_available": False,
        "source_inventory": source_inventory,
        "split_index": split_index_entries,
        "dedupe_summary": {
            "input_records": dedupe_summary["input_records"],
            "unique_records": dedupe_summary["unique_records"],
            "duplicate_records": dedupe_summary["duplicate_records"],
        },
        "governance": {
            "holdout_locked": True,
            "holdout_model_evaluation_allowed": False,
            "holdout_error_metrics_available": False,
        },
        "dataset": manifest["dataset"],
    }
    _write_json(output_dir / "participant_pool_manifest.json", pool_manifest)
    _write_json(output_dir / "participant_pool_status.json", status_payload)
    (output_dir / "participant_pool_report.md").write_text(
        "\n".join(
            [
                "# Participant Pool Report",
                "",
                "## Status",
                f"- participant_count: `{status_payload['participant_count']}`",
                f"- real_runner_count: `{status_payload['real_runner_count']}`",
                f"- real_eligible_folds: `{status_payload['real_eligible_folds']}`",
                f"- development_runner_count: `{status_payload['development_runner_count']}`",
                f"- validation_runner_count: `{status_payload['validation_runner_count']}`",
                f"- holdout_runner_count: `{status_payload['holdout_runner_count']}`",
                f"- development_eligible_folds: `{status_payload['development_eligible_folds']}`",
                f"- validation_eligible_folds: `{status_payload['validation_eligible_folds']}`",
                f"- holdout_eligible_folds: `{status_payload['holdout_eligible_folds']}`",
                f"- synthetic_eligible_folds: `{status_payload['synthetic_eligible_folds']}`",
                f"- distance_to_30: `{status_payload['distance_to_30']}`",
                f"- calibration_status: `{status_payload['calibration_status']}`",
                f"- calibration_allowed: `{status_payload['calibration_allowed']}`",
                f"- user_facing_prediction_allowed: `{status_payload['user_facing_prediction_allowed']}`",
                f"- holdout_locked: `{status_payload['holdout_locked']}`",
                f"- holdout_model_evaluation_allowed: `{status_payload['holdout_model_evaluation_allowed']}`",
                f"- holdout_error_metrics_available: `{status_payload['holdout_error_metrics_available']}`",
                "",
                "## Dedupe",
                f"- input_records: `{dedupe_summary['input_records']}`",
                f"- unique_records: `{dedupe_summary['unique_records']}`",
                f"- duplicate_records: `{dedupe_summary['duplicate_records']}`",
                "",
                "## Sources",
            ]
            + [f"- {row['participant_dir']} -> {row['records_file']}" for row in source_inventory]
        ),
        encoding="utf-8",
    )
    return {
        "participant_pool_records": participant_records_payload,
        "participant_pool_sources": source_inventory,
        "participant_pool_manifest": pool_manifest,
        "participant_pool_status": status_payload,
        "manifest": manifest,
        "eligibility_report": dataset_outputs["eligibility_report"],
        "dedupe_summary": dedupe_summary,
    }

