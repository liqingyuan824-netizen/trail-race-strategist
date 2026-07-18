"""Import, validation, manifest, and eligibility generation for Phase 8A.1."""

from __future__ import annotations

import csv
import json
import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import (
    CACHE_POLICY_VERSION,
    COMPLIANCE_STATUSES,
    FROZEN_MODELS,
    GENERATOR_VERSION,
    RUNNER_SPLITS,
    SAFETY_NOTICE,
    SCHEMA_VERSION,
    SOURCE_POLICY_VERSION,
)
from .report import build_missing_materials_markdown, build_validation_markdown
from .validation import (
    ValidationError,
    classify_compliance_status,
    parse_date,
    parse_finish_time_seconds,
    parse_float,
    parse_int,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _json_safe(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    raise ValidationError(f"unsupported_file_type:{suffix}")


def _split_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "|" in text:
        return [part.strip() for part in text.split("|") if part.strip()]
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]
    return [text]


def _canonical_confidence(record: Mapping[str, Any]) -> float | None:
    confidence = parse_float(record.get("data_confidence"))
    if confidence is None:
        return None
    return round(confidence, 4)


def _stable_runner_key(record: Mapping[str, Any]) -> str:
    key = record.get("pseudonymous_runner_id") or record.get("runner_key")
    if key:
        return str(key)
    source = "|".join(
        [
            str(record.get("event_id") or ""),
            str(record.get("event_name") or ""),
            str(record.get("source_url") or record.get("source_file") or ""),
            str(record.get("access_date") or ""),
        ]
    )
    return f"anon_{_sha256_text(source)[:12]}"


def _normalize_record(record: Mapping[str, Any], *, source_ref: str, source_kind_default: str, synthetic: bool) -> dict[str, Any]:
    finish_seconds = parse_finish_time_seconds(record)
    race_date = parse_date(record.get("race_date"))
    access_date = parse_date(record.get("access_date"))
    distance_km = parse_float(record.get("distance_km"))
    elevation_gain_m = parse_float(record.get("elevation_gain_m"))
    elevation_loss_m = parse_float(record.get("elevation_loss_m"))
    altitude = parse_float(record.get("altitude"))
    temperature = parse_float(record.get("temperature"))
    data_confidence = _canonical_confidence(record)
    source_kind = str(record.get("source_kind") or source_kind_default)
    source_url = record.get("source_url")
    source_file = record.get("source_file")
    usage_basis = record.get("usage_basis")
    license_status = record.get("license_status")
    route_version = record.get("route_version")
    terrain_tags = _split_values(record.get("terrain_tags"))

    compliance_status, issues = classify_compliance_status(
        {
            **dict(record),
            "source_kind": source_kind,
            "race_date": race_date.isoformat() if race_date else None,
            "access_date": access_date.isoformat() if access_date else None,
            "finish_time_seconds": finish_seconds,
            "distance_km": distance_km,
            "elevation_gain_m": elevation_gain_m,
            "data_confidence": data_confidence,
        }
    )

    normalized = {
        "record_id": record.get("record_id") or f"record_{_sha256_text(source_ref + '|' + str(record.get('event_id') or '') + '|' + str(record.get('race_date') or '') + '|' + str(record.get('pseudonymous_runner_id') or '') + '|' + str(route_version or '') + '|' + str(source_url or '') + '|' + str(source_file or ''))[:16]}",
        "pseudonymous_runner_id": _stable_runner_key(record),
        "event_id": record.get("event_id"),
        "event_name": record.get("event_name"),
        "race_date": race_date.isoformat() if race_date else None,
        "race_group": record.get("race_group"),
        "distance_km": distance_km,
        "elevation_gain_m": elevation_gain_m,
        "finish_time_seconds": finish_seconds,
        "result_status": str(record.get("result_status") or "").lower() or None,
        "source_kind": source_kind,
        "source_url": str(source_url) if source_url not in (None, "") else None,
        "source_file": str(source_file) if source_file not in (None, "") else None,
        "access_date": access_date.isoformat() if access_date else None,
        "usage_basis": str(usage_basis) if usage_basis not in (None, "") else None,
        "license_status": str(license_status) if license_status not in (None, "") else None,
        "route_version": str(route_version) if route_version not in (None, "") else None,
        "data_confidence": data_confidence,
        "elevation_loss_m": elevation_loss_m,
        "weather": record.get("weather"),
        "terrain_tags": terrain_tags,
        "altitude": altitude,
        "night_race": record.get("night_race"),
        "temperature": temperature,
        "runner_readiness": record.get("runner_readiness"),
        "synthetic": bool(synthetic or record.get("synthetic") is True or source_kind == "synthetic_fixture"),
        "source_ref": source_ref,
        "compliance_status": compliance_status,
        "compliance_issues": issues,
    }
    return normalized


def _load_csv(path: Path, *, source_kind_default: str = "local_evidence", synthetic: bool = False) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            _normalize_record(row, source_ref=str(path.resolve()), source_kind_default=source_kind_default, synthetic=synthetic)
            for row in reader
        ]


def _load_json(path: Path, *, source_kind_default: str = "local_evidence", synthetic: bool = False) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, Mapping):
        records = payload.get("records", [])
    else:
        raise ValidationError("json_root_not_list_or_mapping")
    if not isinstance(records, list):
        raise ValidationError("records_not_list")
    source_ref = str(path.resolve())
    return [
        _normalize_record(row, source_ref=source_ref, source_kind_default=source_kind_default, synthetic=synthetic)
        for row in records
        if isinstance(row, Mapping)
    ]


def load_dataset_files(paths: Sequence[Path], *, source_kind_default: str = "local_evidence", synthetic: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        kind = _detect_file_kind(path)
        if kind == "csv":
            records.extend(_load_csv(path, source_kind_default=source_kind_default, synthetic=synthetic))
        else:
            records.extend(_load_json(path, source_kind_default=source_kind_default, synthetic=synthetic))
    return records


def normalize_records(records: Sequence[Mapping[str, Any]], *, source_ref: str = "memory://records", source_kind_default: str = "local_evidence", synthetic: bool = False) -> list[dict[str, Any]]:
    return [
        _normalize_record(record, source_ref=source_ref, source_kind_default=source_kind_default, synthetic=synthetic)
        for record in records
    ]


def _record_signature(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("pseudonymous_runner_id"),
        record.get("event_id"),
        record.get("race_date"),
        str(record.get("result_status") or "").strip().lower() or "unknown",
        record.get("finish_time_seconds"),
        record.get("route_version"),
    )


def _group_by_runner(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get("pseudonymous_runner_id") or "unknown")].append(dict(record))
    for runner_id in groups:
        groups[runner_id].sort(key=lambda item: (item.get("race_date") or "", item.get("event_id") or "", item.get("record_id") or ""))
    return groups


def _record_cohort(record: Mapping[str, Any]) -> str:
    return "synthetic" if record.get("synthetic") else "real"


def _detect_conflicts(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]], set[str]]:
    duplicate_map: dict[str, str] = {}
    conflict_groups: dict[str, list[str]] = defaultdict(list)
    route_conflict_keys: set[str] = set()
    seen_signatures: dict[tuple[Any, ...], str] = {}
    seen_event_dates: dict[tuple[Any, ...], list[str]] = defaultdict(list)

    for index, record in enumerate(records):
        record_id = str(record.get("_row_key") or f"{record.get('record_id')}::{index}")
        signature = _record_signature(record)
        if signature in seen_signatures:
            duplicate_map[record_id] = seen_signatures[signature]
        else:
            seen_signatures[signature] = record_id

        event_key = (record.get("pseudonymous_runner_id"), record.get("event_id"), record.get("race_date"))
        seen_event_dates[event_key].append(record_id)
        conflict_groups[str(event_key)].append(record_id)

    for key, record_ids in seen_event_dates.items():
        if len(record_ids) > 1:
            route_conflict_keys.add(str(key))

    return duplicate_map, conflict_groups, route_conflict_keys


def _attach_conflict_flags(records: list[dict[str, Any]], duplicate_map: dict[str, str], conflict_groups: dict[str, list[str]], route_conflict_keys: set[str]) -> None:
    by_record_id = {str(record.get("_row_key") or record["record_id"]): record for record in records}
    for record in records:
        row_key = str(record.get("_row_key") or record["record_id"])
        record["duplicate_of"] = duplicate_map.get(row_key)
        event_key = str((record.get("pseudonymous_runner_id"), record.get("event_id"), record.get("race_date")))
        conflict_ids = conflict_groups.get(event_key, [])
        conflict_signatures = {
            _record_signature(by_record_id[rid])
            for rid in conflict_ids
            if rid in by_record_id
        }
        record["conflict_group_id"] = event_key if len(conflict_ids) > 1 else None
        record["route_version_conflict"] = event_key in route_conflict_keys and len({by_record_id[rid].get("route_version") for rid in conflict_ids if rid in by_record_id}) > 1
        if record["duplicate_of"]:
            record["compliance_status"] = "invalid_record"
            record["compliance_issues"] = list(dict.fromkeys(record["compliance_issues"] + ["duplicate_record"]))
        elif record["route_version_conflict"]:
            if record["compliance_status"] == "usable":
                record["compliance_status"] = "restricted"
            record["compliance_issues"] = list(dict.fromkeys(record["compliance_issues"] + ["route_version_conflict"]))
        elif len(conflict_ids) > 1 and len(conflict_signatures) > 1:
            if record["compliance_status"] == "usable":
                record["compliance_status"] = "restricted"
            record["compliance_issues"] = list(dict.fromkeys(record["compliance_issues"] + ["source_conflict_preserved"]))


def _prepare_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if isinstance(record, Mapping) and {"record_id", "compliance_status"}.issubset(record.keys()):
            copied = dict(record)
        else:
            copied = _normalize_record(
                record,
                source_ref=str(record.get("source_ref") or "memory://records"),
                source_kind_default=str(record.get("source_kind") or "local_evidence"),
                synthetic=bool(record.get("synthetic")),
            )
        copied["_row_key"] = str(copied.get("record_id") or f"record_{index}") + f"::{index}"
        prepared.append(copied)
    duplicate_map, conflict_groups, route_conflict_keys = _detect_conflicts(prepared)
    _attach_conflict_flags(prepared, duplicate_map, conflict_groups, route_conflict_keys)
    return prepared


def _bucket_history_depth(count: int) -> str:
    if count <= 0:
        return "no_history"
    if count == 1:
        return "1_history"
    if count == 2:
        return "2_history"
    return "3plus_history"


def _compute_fold_rows(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups = _group_by_runner(records)
    fold_rows: list[dict[str, Any]] = []
    runner_summary: dict[str, Any] = {}
    for runner_id, runner_records in groups.items():
        usable_records = [record for record in runner_records if record.get("compliance_status") == "usable"]
        usable_records.sort(key=lambda item: (item.get("race_date") or "", item.get("event_id") or "", item.get("record_id") or ""))
        cohorts = {
            "real": [record for record in usable_records if _record_cohort(record) == "real"],
            "synthetic": [record for record in usable_records if _record_cohort(record) == "synthetic"],
        }
        cohort_depth_counts = {"real": Counter(), "synthetic": Counter()}
        cohort_eligible_counts = {"real": 0, "synthetic": 0}
        cohort_insufficient_counts = {"real": 0, "synthetic": 0}
        for cohort_name, cohort_records in cohorts.items():
            for index, target in enumerate(cohort_records):
                prior = cohort_records[:index]
                depth_bucket = _bucket_history_depth(len(prior))
                if not prior:
                    fold_status = "insufficient_history"
                    cohort_insufficient_counts[cohort_name] += 1
                else:
                    fold_status = "usable"
                    cohort_eligible_counts[cohort_name] += 1
                cohort_depth_counts[cohort_name][depth_bucket] += 1
                fold_rows.append(
                    {
                        "fold_id": f"{runner_id}:{cohort_name}:{target['record_id']}",
                        "pseudonymous_runner_id": runner_id,
                        "fold_cohort": cohort_name,
                        "target_record_id": target["record_id"],
                        "event_id": target.get("event_id"),
                        "event_name": target.get("event_name"),
                        "race_date": target.get("race_date"),
                        "prior_record_ids": [item["record_id"] for item in prior],
                        "prior_record_count": len(prior),
                        "history_depth_bucket": depth_bucket,
                        "fold_status": fold_status,
                        "target_compliance_status": target.get("compliance_status"),
                        "route_version": target.get("route_version"),
                        "source_kind": target.get("source_kind"),
                        "synthetic": bool(target.get("synthetic")),
                        "data_confidence": target.get("data_confidence"),
                    }
                )
        runner_summary[runner_id] = {
            "record_count": len(runner_records),
            "real_record_count": sum(1 for record in runner_records if not record.get("synthetic")),
            "synthetic_record_count": sum(1 for record in runner_records if record.get("synthetic")),
            "usable_record_count": len(usable_records),
            "real_usable_record_count": len(cohorts["real"]),
            "synthetic_usable_record_count": len(cohorts["synthetic"]),
            "real_eligible_fold_count": cohort_eligible_counts["real"],
            "synthetic_eligible_fold_count": cohort_eligible_counts["synthetic"],
            "real_insufficient_history_fold_count": cohort_insufficient_counts["real"],
            "synthetic_insufficient_history_fold_count": cohort_insufficient_counts["synthetic"],
            "eligible_fold_count": cohort_eligible_counts["real"],
            "total_eligible_fold_count": cohort_eligible_counts["real"] + cohort_eligible_counts["synthetic"],
            "fold_depth_counts": {
                "real": dict(cohort_depth_counts["real"]),
                "synthetic": dict(cohort_depth_counts["synthetic"]),
            },
        }
    return fold_rows, runner_summary


def build_dataset_manifest(records: Sequence[Mapping[str, Any]], *, source_files: Sequence[Path] | None = None) -> dict[str, Any]:
    records = _prepare_records(records)
    source_files = list(source_files or [])
    fold_rows, runner_summary = _compute_fold_rows(records)
    compliance_counts = Counter(record.get("compliance_status") for record in records)
    fold_status_counts = Counter(fold.get("fold_status") for fold in fold_rows)
    fold_depth_counts = Counter(fold.get("history_depth_bucket") for fold in fold_rows)
    real_fold_rows = [fold for fold in fold_rows if fold.get("fold_cohort") == "real"]
    synthetic_fold_rows = [fold for fold in fold_rows if fold.get("fold_cohort") == "synthetic"]
    synthetic_records = sum(1 for record in records if record.get("synthetic"))
    real_records = len(records) - synthetic_records
    real_usable_records = sum(1 for record in records if record.get("compliance_status") == "usable" and not record.get("synthetic"))
    synthetic_usable_records = sum(1 for record in records if record.get("compliance_status") == "usable" and record.get("synthetic"))
    real_fold_status_counts = Counter(fold.get("fold_status") for fold in real_fold_rows)
    synthetic_fold_status_counts = Counter(fold.get("fold_status") for fold in synthetic_fold_rows)

    source_inventory = []
    for path in source_files:
        source_inventory.append(
            {
                "source_uri": str(path.resolve()),
                "source_kind": _detect_file_kind(path),
                "file_hash": _sha256_file(path),
                "access_date": _utc_now(),
                "license_status": "unknown",
                "usage_basis": "user-supplied local file",
                "auto_access_allowed": False,
                "immutable": True,
            }
        )

    fold_depth_counts = {bucket: int(fold_depth_counts.get(bucket, 0)) for bucket in ("no_history", "1_history", "2_history", "3plus_history")}
    compliance_counts = {status: int(compliance_counts.get(status, 0)) for status in sorted(COMPLIANCE_STATUSES)}
    fold_status_counts = {status: int(fold_status_counts.get(status, 0)) for status in ("usable", "insufficient_history")}

    manifest = {
        "schema_name": "backtest_dataset_manifest",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "frozen_models": FROZEN_MODELS,
        "splits": {
            "development": {"status": "reserved", "record_ids": [], "eligible_fold_ids": []},
            "validation": {"status": "reserved", "record_ids": [], "eligible_fold_ids": []},
            "holdout": {"status": "reserved", "record_ids": [], "eligible_fold_ids": []},
        },
        "validation_modes": {
            "rolling_origin": {"enabled": True, "description": "single-runner chronological folds"},
            "cross_runner": {"enabled": True, "description": "reserved for future generalization checks"},
        },
        "source_inventory": source_inventory,
        "dataset": {
            "total_records": len(records),
            "real_records": real_records,
            "synthetic_records": synthetic_records,
            "real_usable_records": real_usable_records,
            "synthetic_usable_records": synthetic_usable_records,
            "usable_records": compliance_counts.get("usable", 0),
            "restricted_records": compliance_counts.get("restricted", 0),
            "blocked_by_data_rights_records": compliance_counts.get("blocked_by_data_rights", 0),
            "missing_course_data_records": compliance_counts.get("missing_course_data", 0),
            "invalid_records": compliance_counts.get("invalid_record", 0),
            "total_eligible_folds": fold_status_counts.get("usable", 0),
            "eligible_folds": int(real_fold_status_counts.get("usable", 0)),
            "real_eligible_folds": int(real_fold_status_counts.get("usable", 0)),
            "synthetic_eligible_folds": int(synthetic_fold_status_counts.get("usable", 0)),
            "real_insufficient_history_folds": int(real_fold_status_counts.get("insufficient_history", 0)),
            "synthetic_insufficient_history_folds": int(synthetic_fold_status_counts.get("insufficient_history", 0)),
            "insufficient_history_folds": fold_status_counts.get("insufficient_history", 0),
            "fold_depth_counts": fold_depth_counts,
            "formal_gate_basis": "real_eligible_folds",
            "calibration_allowed": bool(real_fold_status_counts.get("usable", 0) >= 30 and compliance_counts.get("blocked_by_data_rights", 0) == 0 and compliance_counts.get("invalid_record", 0) == 0),
            "user_facing_prediction_allowed": False,
        },
        "runner_summary": runner_summary,
        "record_index": [
            {
                "record_id": record.get("record_id"),
                "pseudonymous_runner_id": record.get("pseudonymous_runner_id"),
                "event_id": record.get("event_id"),
                "event_name": record.get("event_name"),
                "race_date": record.get("race_date"),
                "compliance_status": record.get("compliance_status"),
                "source_kind": record.get("source_kind"),
                "synthetic": bool(record.get("synthetic")),
                "duplicate_of": record.get("duplicate_of"),
                "conflict_group_id": record.get("conflict_group_id"),
                "route_version_conflict": bool(record.get("route_version_conflict")),
                "data_confidence": record.get("data_confidence"),
            }
            for record in records
        ],
    }
    return manifest


def build_eligibility_report(records: Sequence[Mapping[str, Any]], *, source_files: Sequence[Path] | None = None) -> dict[str, Any]:
    prepared_records = _prepare_records(records)
    manifest = build_dataset_manifest(prepared_records, source_files=source_files)
    fold_rows, runner_summary = _compute_fold_rows(prepared_records)
    compliance_counts = Counter(record.get("compliance_status") for record in prepared_records)
    fold_depth_counts = Counter(fold.get("history_depth_bucket") for fold in fold_rows)
    real_fold_rows = [fold for fold in fold_rows if fold.get("fold_cohort") == "real"]
    synthetic_fold_rows = [fold for fold in fold_rows if fold.get("fold_cohort") == "synthetic"]
    real_fold_status_counts = Counter(fold.get("fold_status") for fold in real_fold_rows)
    synthetic_fold_status_counts = Counter(fold.get("fold_status") for fold in synthetic_fold_rows)
    status_by_record = {record.get("record_id"): record.get("compliance_status") for record in prepared_records}
    status_notes = []
    if compliance_counts.get("blocked_by_data_rights", 0):
        status_notes.append("Some records were preserved as evidence but blocked from formal backtest use because rights were unclear or restricted.")
    if compliance_counts.get("missing_course_data", 0):
        status_notes.append("Some records lack course metadata such as route_version and remain out of the formal pool.")
    if compliance_counts.get("invalid_record", 0):
        status_notes.append("Malformed or duplicate records were retained in the evidence layer but marked invalid.")
    if manifest["dataset"]["real_eligible_folds"] < 30:
        status_notes.append("The current pool is below the target 30-50 compliant real folds.")
    if manifest["dataset"]["synthetic_eligible_folds"] > 0:
        status_notes.append("Synthetic folds are tracked separately and do not contribute to the formal calibration gate.")

    calibration_allowed = bool(
        manifest["dataset"]["real_eligible_folds"] >= 30
        and manifest["dataset"]["blocked_by_data_rights_records"] == 0
        and manifest["dataset"]["invalid_records"] == 0
    )
    overall_status = _overall_status(manifest)

    report = {
        "schema_name": "eligibility_report",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "overall_status": overall_status,
        "summary": {
            "total_records": manifest["dataset"]["total_records"],
            "real_records": manifest["dataset"]["real_records"],
            "synthetic_records": manifest["dataset"]["synthetic_records"],
            "usable_records": manifest["dataset"]["usable_records"],
            "real_usable_records": manifest["dataset"]["real_usable_records"],
            "synthetic_usable_records": manifest["dataset"]["synthetic_usable_records"],
            "eligible_folds": manifest["dataset"]["eligible_folds"],
            "total_eligible_folds": manifest["dataset"]["total_eligible_folds"],
            "real_eligible_folds": manifest["dataset"]["real_eligible_folds"],
            "synthetic_eligible_folds": manifest["dataset"]["synthetic_eligible_folds"],
            "real_insufficient_history_folds": manifest["dataset"]["real_insufficient_history_folds"],
            "synthetic_insufficient_history_folds": manifest["dataset"]["synthetic_insufficient_history_folds"],
            "valid_folds": manifest["dataset"]["real_eligible_folds"],
            "insufficient_history_folds": manifest["dataset"]["insufficient_history_folds"],
            "compliance_counts": {status: int(compliance_counts.get(status, 0)) for status in sorted(COMPLIANCE_STATUSES)},
            "fold_depth_counts": {bucket: int(fold_depth_counts.get(bucket, 0)) for bucket in ("no_history", "1_history", "2_history", "3plus_history")},
        },
        "runner_summary": runner_summary,
        "fold_rows": fold_rows,
        "record_status_map": status_by_record,
        "notes": status_notes,
        "missing_materials": _missing_materials(manifest),
        "restricted_materials": _restricted_materials(prepared_records),
        "evidence_materials": _evidence_materials(source_files or []),
        "dataset_manifest": manifest,
        "formal_gate_basis": manifest["dataset"]["formal_gate_basis"],
        "calibration_allowed": calibration_allowed,
        "user_facing_prediction_allowed": False,
        "real_eligible_folds": manifest["dataset"]["real_eligible_folds"],
        "synthetic_eligible_folds": manifest["dataset"]["synthetic_eligible_folds"],
        "validation_markdown": build_validation_markdown(
            {
                "overall_status": overall_status,
                "summary": {
                    "total_records": manifest["dataset"]["total_records"],
                    "real_records": manifest["dataset"]["real_records"],
                    "synthetic_records": manifest["dataset"]["synthetic_records"],
                    "real_usable_records": manifest["dataset"]["real_usable_records"],
                    "synthetic_usable_records": manifest["dataset"]["synthetic_usable_records"],
                    "eligible_folds": manifest["dataset"]["eligible_folds"],
                    "total_eligible_folds": manifest["dataset"]["total_eligible_folds"],
                    "real_eligible_folds": manifest["dataset"]["real_eligible_folds"],
                    "synthetic_eligible_folds": manifest["dataset"]["synthetic_eligible_folds"],
                    "real_insufficient_history_folds": manifest["dataset"]["real_insufficient_history_folds"],
                    "synthetic_insufficient_history_folds": manifest["dataset"]["synthetic_insufficient_history_folds"],
                    "valid_folds": manifest["dataset"]["real_eligible_folds"],
                    "compliance_counts": {status: int(compliance_counts.get(status, 0)) for status in sorted(COMPLIANCE_STATUSES)},
                    "fold_depth_counts": {bucket: int(fold_depth_counts.get(bucket, 0)) for bucket in ("no_history", "1_history", "2_history", "3plus_history")},
                },
                "runner_summary": runner_summary,
                "missing_materials": _missing_materials(manifest),
                "notes": status_notes,
                "formal_gate_basis": manifest["dataset"]["formal_gate_basis"],
                "calibration_allowed": calibration_allowed,
                "user_facing_prediction_allowed": False,
            }
        ),
        "missing_materials_markdown": build_missing_materials_markdown(
            {
                "missing_materials": _missing_materials(manifest),
                "restricted_materials": _restricted_materials(prepared_records),
                "evidence_materials": _evidence_materials(source_files or []),
            }
        ),
    }
    return report


def _overall_status(manifest: Mapping[str, Any]) -> str:
    if manifest["dataset"]["real_eligible_folds"] >= 30 and manifest["dataset"]["blocked_by_data_rights_records"] == 0 and manifest["dataset"]["invalid_records"] == 0:
        return "usable"
    if manifest["dataset"]["blocked_by_data_rights_records"] > 0:
        return "blocked_by_data_rights"
    if manifest["dataset"]["missing_course_data_records"] > 0:
        return "missing_course_data"
    if manifest["dataset"]["invalid_records"] > 0:
        return "invalid_record"
    if manifest["dataset"]["real_eligible_folds"] < 1:
        return "insufficient_history"
    return "restricted"


def _missing_materials(manifest: Mapping[str, Any]) -> list[str]:
    items: list[str] = []
    if manifest["dataset"]["real_eligible_folds"] < 30:
        items.append("Need at least 30-50 compliant real rolling-origin folds before calibration can be claimed.")
    if manifest["dataset"]["missing_course_data_records"] > 0:
        items.append("Provide route_version and course metadata for records currently marked missing_course_data.")
    if manifest["dataset"]["blocked_by_data_rights_records"] > 0:
        items.append("Provide explicit data-use permission or open-license basis for blocked records if they are to enter the formal pool.")
    if not manifest["source_inventory"]:
        items.append("Attach source files or URLs so the manifest can preserve file_hash and access provenance.")
    return items


def _restricted_materials(records: Sequence[Mapping[str, Any]]) -> list[str]:
    items: list[str] = []
    for record in records:
        if record.get("compliance_status") != "usable":
            items.append(
                f"{record.get('record_id')}: {record.get('event_name')} on {record.get('race_date')} ({record.get('compliance_status')})"
            )
    return items


def _evidence_materials(source_files: Sequence[Path]) -> list[str]:
    items: list[str] = []
    for path in source_files:
        items.append(f"{path.resolve()}")
    items.append("CSV template: backtest_dataset/templates/backtest_dataset_template.csv")
    items.append("JSON template: backtest_dataset/templates/backtest_dataset_template.json")
    return items


def write_dataset_outputs(
    *,
    records: Sequence[Mapping[str, Any]],
    output_dir: Path,
    source_files: Sequence[Path] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_dataset_manifest(records, source_files=source_files)
    eligibility_report = build_eligibility_report(records, source_files=source_files)

    (output_dir / "backtest_dataset_manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "eligibility_report.json").write_text(
        json.dumps(_json_safe(eligibility_report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "dataset_validation_report.md").write_text(
        eligibility_report["validation_markdown"],
        encoding="utf-8",
    )
    (output_dir / "合规与缺失资料清单.md").write_text(
        eligibility_report["missing_materials_markdown"],
        encoding="utf-8",
    )
    return {
        "manifest": manifest,
        "eligibility_report": eligibility_report,
    }


def build_dataset_artifacts(*, input_paths: Sequence[Path], output_dir: Path, synthetic: bool = False) -> dict[str, Any]:
    records = load_dataset_files(input_paths, synthetic=synthetic)
    return write_dataset_outputs(records=records, output_dir=output_dir, source_files=input_paths)
