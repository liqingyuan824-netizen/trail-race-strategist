"""Fail-closed W1 local FIT import and request-bound deletion."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .fit_adapter import FitDecodeError, parse_garmin_fit
from .features import build_feature_summary


class IngestError(ValueError):
    pass


class DeleteError(ValueError):
    pass


_FORBIDDEN = {"password", "cookie", "oauth_token", "device_serial_number", "external_account_id", "gps_points", "heart_rate_samples", "wellness_details", "finish_time_prediction", "cp_arrival_time", "prediction_probability"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_receipt_hash(unsigned_receipt: dict[str, Any]) -> str:
    """Return the W1 receipt digest over stable JSON, excluding the digest itself."""
    return hashlib.sha256(
        json.dumps(unsigned_receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_utc_confirmation(value: str) -> str:
    """Accept one explicit UTC confirmation instant and return its canonical form."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise IngestError("invalid_consent_confirmation_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestError("invalid_consent_confirmation_time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise IngestError("invalid_consent_confirmation_time")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_window_date(value: str) -> str:
    if not isinstance(value, str):
        raise IngestError("invalid_consent_window_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise IngestError("invalid_consent_window_date") from exc
    return parsed.isoformat()


def _is_e_drive(path: Path) -> bool:
    return path.resolve().drive.upper() == "E:"


def issue_consent_receipt(
    *,
    request_id: str,
    private_alias: str,
    consented_at: str,
    allowed_start_date: str,
    allowed_end_date: str,
    consent_root: Path,
    source_brand: str = "garmin",
) -> dict[str, Any]:
    """Issue one new W1-only consent receipt without accessing activity data.

    The caller supplies only consent metadata.  This function neither enumerates
    sources nor creates a wearable import request directory.
    """
    if not isinstance(request_id, str) or not re.fullmatch(r"wearable-req-[A-Za-z0-9-]+", request_id):
        raise IngestError("invalid_consent_request_id")
    if source_brand not in {"garmin", "coros"}:
        raise IngestError("invalid_consent_source_brand")
    if not isinstance(private_alias, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", private_alias):
        raise IngestError("invalid_consent_private_alias")
    if not isinstance(consent_root, Path) or not consent_root.is_dir() or not _is_e_drive(consent_root):
        raise IngestError("consent_root_must_be_existing_directory_on_e_drive")

    normalized_consented_at = _parse_utc_confirmation(consented_at)
    start_date = _parse_window_date(allowed_start_date)
    end_date = _parse_window_date(allowed_end_date)
    if start_date > end_date:
        raise IngestError("invalid_consent_date_window")

    target_dir = consent_root / request_id
    if target_dir.exists():
        raise IngestError("consent_request_target_already_exists")

    unsigned = {
        "schema_name": "wearable_consent_receipt",
        "schema_version": "1.0.0",
        "receipt_id": f"wearable-consent-{uuid4()}",
        "request_id": request_id,
        "consented_at": normalized_consented_at,
        "created_at": _now(),
        "subject_private_alias": private_alias,
        "data_owner_alias": private_alias,
        "privacy_mode": "local_private",
        "source_brand": source_brand,
        "allowed_data_window": {"start_date": start_date, "end_date": end_date},
        "allowed_purposes": ["derived_training_features", "readiness_advice"],
        "revocation_method": "request_id_deletion",
        "consent_scope": {
            "local_fit_import": True,
            "derived_training_features": True,
            "readiness_advice": True,
            "allow_model_research": False,
        },
        "retention": {
            "raw_fit_retention_days": 90,
            "derived_feature_retention_days": 365,
            "delete_by_request_id_supported": True,
        },
        "governance": {"user_facing_prediction_allowed": False},
    }
    receipt = {**unsigned, "immutable_receipt_hash": _canonical_receipt_hash(unsigned)}

    try:
        target_dir.mkdir()
        receipt_path = target_dir / "consent_receipt.json"
        with receipt_path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise IngestError("consent_request_target_already_exists") from exc
    except OSError as exc:
        raise IngestError("consent_receipt_write_failed") from exc

    validated, receipt_sha256 = _load_consent(receipt_path)
    if validated != receipt:
        raise IngestError("consent_receipt_self_validation_mismatch")
    return {
        "status": "issued",
        "request_id": request_id,
        "receipt_id": receipt["receipt_id"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
        "allow_model_research": False,
        "user_facing_prediction_allowed": False,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_new(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise IngestError(f"immutable_output_already_exists:{path.name}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _load_consent(path: Path) -> tuple[dict[str, Any], str]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestError("invalid_consent_receipt") from exc
    if not isinstance(receipt, dict):
        raise IngestError("invalid_consent_schema:not_an_object")
    forbidden_keys = _FORBIDDEN & set(receipt)
    if forbidden_keys:
        raise IngestError("invalid_consent_schema:forbidden_field")
    required_top = {"schema_name", "schema_version", "receipt_id", "request_id", "consented_at", "created_at", "subject_private_alias", "data_owner_alias", "privacy_mode", "source_brand", "allowed_data_window", "allowed_purposes", "revocation_method", "consent_scope", "retention", "governance", "immutable_receipt_hash"}
    if set(receipt) - required_top:
        raise IngestError("invalid_consent_schema:additional_property")
    if required_top - set(receipt):
        raise IngestError("invalid_consent_schema:missing_required_property")
    if not isinstance(receipt["receipt_id"], str) or not re.fullmatch(r"wearable-consent-[A-Za-z0-9-]+", receipt["receipt_id"]):
        raise IngestError("invalid_consent_schema:receipt_id")
    if not isinstance(receipt["request_id"], str) or not re.fullmatch(r"wearable-req-[A-Za-z0-9-]+", receipt["request_id"]):
        raise IngestError("invalid_consent_schema:request_id")
    if not isinstance(receipt["subject_private_alias"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", receipt["subject_private_alias"]):
        raise IngestError("invalid_consent_schema:subject_private_alias")
    if not isinstance(receipt["data_owner_alias"], str) or receipt["data_owner_alias"] != receipt["subject_private_alias"]:
        raise IngestError("invalid_consent_schema:data_owner_alias")
    for field in ("consented_at", "created_at"):
        if not isinstance(receipt[field], str):
            raise IngestError(f"invalid_consent_schema:{field}")
        try:
            datetime.fromisoformat(receipt[field].replace("Z", "+00:00"))
        except ValueError as exc:
            raise IngestError(f"invalid_consent_schema:{field}") from exc
    if receipt["privacy_mode"] != "local_private" or receipt["source_brand"] not in {"garmin", "coros"} or receipt["revocation_method"] != "request_id_deletion":
        raise IngestError("consent_contract_not_authorized_for_w1")
    window = receipt["allowed_data_window"]
    if not isinstance(window, dict) or set(window) != {"start_date", "end_date"}:
        raise IngestError("invalid_consent_schema:allowed_data_window")
    try:
        window_start = datetime.fromisoformat(f"{window['start_date']}T00:00:00+00:00").date()
        window_end = datetime.fromisoformat(f"{window['end_date']}T00:00:00+00:00").date()
    except (TypeError, ValueError) as exc:
        raise IngestError("invalid_consent_schema:allowed_data_window") from exc
    if window_start > window_end:
        raise IngestError("invalid_consent_schema:allowed_data_window")
    purposes = receipt["allowed_purposes"]
    if not isinstance(purposes, list) or not purposes or not all(isinstance(purpose, str) for purpose in purposes) or len(purposes) != len(set(purposes)) or not set(purposes).issubset({"derived_training_features", "readiness_advice"}) or "derived_training_features" not in purposes:
        raise IngestError("invalid_consent_schema:allowed_purposes")
    scope, retention, governance = receipt["consent_scope"], receipt["retention"], receipt["governance"]
    if not isinstance(scope, dict) or set(scope) != {"local_fit_import", "derived_training_features", "readiness_advice", "allow_model_research"}:
        raise IngestError("invalid_consent_schema:consent_scope")
    if not isinstance(retention, dict) or set(retention) != {"raw_fit_retention_days", "derived_feature_retention_days", "delete_by_request_id_supported"}:
        raise IngestError("invalid_consent_schema:retention")
    if not isinstance(governance, dict) or set(governance) != {"user_facing_prediction_allowed"}:
        raise IngestError("invalid_consent_schema:governance")
    if receipt.get("schema_name") != "wearable_consent_receipt" or receipt.get("schema_version") != "1.0.0":
        raise IngestError("unsupported_consent_receipt")
    if scope["local_fit_import"] is not True or scope["derived_training_features"] is not True or not isinstance(scope["readiness_advice"], bool) or scope["allow_model_research"] is not False:
        raise IngestError("consent_scope_not_authorized_for_w1")
    if retention["delete_by_request_id_supported"] is not True or type(retention["raw_fit_retention_days"]) is not int or type(retention["derived_feature_retention_days"]) is not int or retention["raw_fit_retention_days"] < 1 or retention["derived_feature_retention_days"] < 1:
        raise IngestError("invalid_consent_retention")
    if governance["user_facing_prediction_allowed"] is not False:
        raise IngestError("consent_governance_not_locked")
    immutable_hash = receipt.get("immutable_receipt_hash")
    if not isinstance(immutable_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", immutable_hash):
        raise IngestError("invalid_consent_schema:immutable_receipt_hash")
    unsigned = {key: value for key, value in receipt.items() if key != "immutable_receipt_hash"}
    expected_hash = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if immutable_hash != expected_hash:
        raise IngestError("consent_receipt_hash_mismatch")
    return receipt, _sha256(path)


def _normalized(request_id: str, source_sha256: str, parsed: dict[str, Any]) -> dict[str, Any]:
    activity = {
        "schema_name": "wearable_normalized_activity",
        "schema_version": "1.0.0",
        "request_id": request_id,
        "import_request_id": request_id,
        "activity_id": f"wearable-activity-{source_sha256[:20]}",
        "source_sha256": source_sha256,
        "started_at_unix": parsed["started_at_unix"],
        "duration_seconds": parsed["duration_seconds"],
        "distance_km": parsed["distance_km"],
        "ascent_m": parsed["ascent_m"],
        "gps_present": parsed["gps_present"],
        "heart_rate_present": parsed["heart_rate_present"],
        "average_heart_rate_bpm": parsed["average_heart_rate_bpm"],
    }
    if _FORBIDDEN & set(activity):
        raise IngestError("prohibited_normalized_field")
    return activity


def _summary(request_id: str, activity: dict[str, Any]) -> dict[str, Any]:
    summary = build_feature_summary([activity], generated_at=_now())
    activity_date = datetime.fromtimestamp(activity["started_at_unix"], UTC).date().isoformat()
    # W1's per-import artifact remains a single-activity snapshot; W2 callers
    # use build_feature_summary directly for a rolling 84-day aggregation.
    summary["aggregation_window"]["start_date"] = activity_date
    missing = summary["quality"]["missing_data_flags"]
    for presence_key, flag in (("gps_present", "gps_not_present"), ("heart_rate_present", "heart_rate_not_present")):
        if not activity[presence_key]:
            missing.append(flag)
    if missing and summary["uncertainty"]["level"] == "low":
        summary["uncertainty"] = {"level": "medium", "reasons": list(missing)}
    return summary


def _existing_hash(import_root: Path, source_sha256: str) -> str | None:
    for manifest_path in import_root.glob("wearable-req-*/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise IngestError("existing_manifest_unreadable_fail_closed")
        hashes = {payload.get("source_sha256")}
        hashes.update(
            item.get("source_sha256") for item in payload.get("files", [])
            if isinstance(item, dict) and item.get("status") == "completed"
        )
        if source_sha256 in hashes and payload.get("status") == "completed":
            return str(payload.get("request_id"))
    return None


def _allowed_window(receipt: dict[str, Any]) -> tuple[Any, Any]:
    window = receipt["allowed_data_window"]
    return (
        datetime.fromisoformat(f"{window['start_date']}T00:00:00+00:00").date(),
        datetime.fromisoformat(f"{window['end_date']}T00:00:00+00:00").date(),
    )


def _resolve_batch_sources(*, source_paths: list[Path] | None, source_dir: Path | None, private_root: Path) -> list[Path]:
    if bool(source_paths) == bool(source_dir):
        raise IngestError("exactly_one_of_source_paths_or_source_dir_required")
    if source_paths:
        sources = list(source_paths)
    else:
        assert source_dir is not None
        if not source_dir.is_dir() or not _inside(private_root, source_dir):
            raise IngestError("source_dir_must_be_inside_explicit_private_root")
        import_root = private_root / "wearable-imports"
        sources = [path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".fit" and not _inside(import_root, path)]
    if not sources:
        raise IngestError("no_fit_sources_found")
    return sources


def _file_result(source: Path, *, status: str, source_sha256: str | None = None, reason: str | None = None, parsed: dict[str, Any] | None = None, duplicate_of_request_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"source_filename": source.name, "status": status}
    if source_sha256 is not None:
        result["source_sha256"] = source_sha256
    if reason is not None:
        result["rejection_reason"] = reason
    if parsed is not None:
        result["activity_id"] = f"wearable-activity-{source_sha256[:20]}"
        result["activity_date"] = datetime.fromtimestamp(parsed["started_at_unix"], UTC).date().isoformat()
    if duplicate_of_request_id is not None:
        result["duplicate_of_request_id"] = duplicate_of_request_id
    return result


def ingest_fit_batch(*, source_paths: list[Path] | None = None, source_dir: Path | None = None, private_root: Path | None, consent_file: Path, dry_run: bool = False) -> dict[str, Any]:
    """Import a signed-consent FIT batch after complete in-memory preflight.

    Rejected files never reach raw, normalized, or derived storage.  A mixed
    batch records their reasons in the one request manifest; an all-rejected
    batch creates no request directory at all.
    """
    if private_root is None:
        raise IngestError("private_root_must_be_explicit")
    if not private_root.is_dir():
        raise IngestError("private_root_not_found")
    if not consent_file.is_file() or not _inside(private_root, consent_file):
        raise IngestError("consent_must_be_inside_explicit_private_root")
    consent, consent_sha = _load_consent(consent_file)
    sources = _resolve_batch_sources(source_paths=source_paths, source_dir=source_dir, private_root=private_root)
    request_id = consent["request_id"]
    request_dir = private_root / "wearable-imports" / request_id
    if request_dir.exists():
        raise IngestError("request_id_already_exists")
    import_root = private_root / "wearable-imports"
    window_start, window_end = _allowed_window(consent)
    files: list[dict[str, Any]] = []
    accepted: list[tuple[Path, str, dict[str, Any]]] = []
    seen_hashes: set[str] = set()
    for source in sources:
        if source.suffix.lower() != ".fit" or not source.is_file() or not _inside(private_root, source):
            files.append(_file_result(source, status="rejected", reason="source_must_be_fit_file_inside_explicit_private_root"))
            continue
        source_sha = _sha256(source)
        if source_sha in seen_hashes:
            files.append(_file_result(source, status="rejected", source_sha256=source_sha, reason="duplicate_source_sha256_in_batch"))
            continue
        seen_hashes.add(source_sha)
        try:
            parsed = parse_garmin_fit(source)
        except FitDecodeError as exc:
            files.append(_file_result(source, status="rejected", source_sha256=source_sha, reason=str(exc)))
            continue
        activity_date = datetime.fromtimestamp(parsed["started_at_unix"], UTC).date()
        if not window_start <= activity_date <= window_end:
            files.append(_file_result(source, status="rejected", source_sha256=source_sha, reason="activity_outside_allowed_data_window", parsed=parsed))
            continue
        duplicate_of = _existing_hash(import_root, source_sha) if import_root.exists() else None
        if duplicate_of:
            files.append(_file_result(source, status="rejected", source_sha256=source_sha, reason="duplicate_source_sha256_completed_request", parsed=parsed, duplicate_of_request_id=duplicate_of))
            continue
        files.append(_file_result(source, status="completed", source_sha256=source_sha, parsed=parsed))
        accepted.append((source, source_sha, parsed))
    preview = [_normalized(request_id, source_sha, parsed) for _source, source_sha, parsed in accepted]
    if dry_run:
        return {"dry_run": True, "request_id": request_id, "files": files, "eligible_activity_count": len(preview), "rejected_file_count": len(files) - len(preview), "activity_previews": preview, "no_files_written": True}
    if not accepted:
        return {"request_id": request_id, "status": "no_eligible_activities", "files": files, "no_files_written": True}
    import_root.mkdir(exist_ok=True)
    request_dir.mkdir()
    manifest = {"schema_name": "wearable_import_manifest", "schema_version": "1.1.0", "request_id": request_id, "created_at": _now(), "consent_receipt_sha256": consent_sha, "status": "started", "files": files}
    _write_json_new(request_dir / "manifest.json", manifest)
    for name in ("raw", "normalized", "derived", "receipts"):
        (request_dir / name).mkdir()
    activities = []
    for source, source_sha, parsed in accepted:
        activity = _normalized(request_id, source_sha, parsed)
        activities.append(activity)
        shutil.copy2(source, request_dir / "raw" / f"{activity['activity_id']}.fit")
        _write_json_new(request_dir / "normalized" / f"{activity['activity_id']}.json", activity)
    summary = build_feature_summary(activities, generated_at=_now())
    _write_json_new(request_dir / "derived" / "feature_summary.json", summary)
    _write_json_new(request_dir / "receipts" / "consent_receipt.json", consent)
    receipt = {"schema_name": "wearable_import_receipt", "schema_version": "1.1.0", "request_id": request_id, "status": "completed", "completed_at": _now(), "eligible_activity_count": len(activities), "rejected_file_count": len(files) - len(activities), "consent_receipt_sha256": consent_sha, "raw_retention_days": consent["retention"]["raw_fit_retention_days"], "derived_retention_days": consent["retention"]["derived_feature_retention_days"], "governance": {"allow_model_research": False, "user_facing_prediction_allowed": False}}
    _write_json_new(request_dir / "receipts" / "import_receipt.json", receipt)
    manifest["status"] = "completed"
    (request_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"request_id": request_id, "request_dir": str(request_dir), "status": "completed", "files": files, "eligible_activity_count": len(activities), "rejected_file_count": len(files) - len(activities)}


def ingest_fit(*, source: Path, private_root: Path | None, consent_file: Path, dry_run: bool = False) -> dict[str, Any]:
    """Backward-compatible one-file wrapper around the W1 batch importer."""
    result = ingest_fit_batch(source_paths=[source], private_root=private_root, consent_file=consent_file, dry_run=dry_run)
    if result.get("status") == "no_eligible_activities":
        reason = result["files"][0].get("rejection_reason", "no_eligible_activities")
        # Keep the historical one-file API's duplicate receipt behavior.  The
        # new batch entry point remains stricter: an all-rejected batch writes
        # nothing.  This compatibility branch stores no raw or derived data.
        if reason == "duplicate_source_sha256_completed_request" and private_root is not None:
            request_id = result["request_id"]
            request_dir = private_root / "wearable-imports" / request_id
            request_dir.mkdir(parents=True)
            file_result = result["files"][0]
            _write_json_new(request_dir / "manifest.json", {"schema_name": "wearable_import_manifest", "schema_version": "1.1.0", "request_id": request_id, "created_at": _now(), "status": "rejected_duplicate", "files": result["files"]})
            (request_dir / "receipts").mkdir()
            _write_json_new(request_dir / "receipts" / "import_receipt.json", {"schema_name": "wearable_import_receipt", "schema_version": "1.1.0", "request_id": request_id, "status": "rejected_duplicate", "duplicate_of_request_id": file_result.get("duplicate_of_request_id"), "source_sha256": file_result.get("source_sha256"), "completed_at": _now()})
            return {"request_id": request_id, "request_dir": str(request_dir), "status": "rejected_duplicate", "source_sha256": file_result.get("source_sha256")}
        raise IngestError(str(reason))
    if dry_run:
        preview = result["activity_previews"][0] if result["activity_previews"] else None
        return {"dry_run": True, "request_id": result["request_id"], "source_sha256": result["files"][0].get("source_sha256"), "activity_preview": preview, "no_files_written": True}
    # Legacy callers use stable singleton filenames and a one-activity summary
    # window.  The batch manifest still binds the activity ID and SHA-256.
    request_dir = Path(result["request_dir"])
    activity = result["files"][0]
    activity_id = activity["activity_id"]
    (request_dir / "raw" / f"{activity_id}.fit").replace(request_dir / "raw" / "activity.fit")
    activity_path = request_dir / "normalized" / f"{activity_id}.json"
    normalized = json.loads(activity_path.read_text(encoding="utf-8"))
    activity_path.replace(request_dir / "normalized" / "activity.json")
    (request_dir / "derived" / "feature_summary.json").write_text(json.dumps(_summary(result["request_id"], normalized), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def delete_request(*, request_id: str, private_root: Path | None, operator_kind: str = "local_user") -> dict[str, Any]:
    if private_root is None or not private_root.is_dir():
        raise DeleteError("private_root_must_be_explicit_and_exist")
    if not request_id.startswith("wearable-req-") or "/" in request_id or "\\" in request_id:
        raise DeleteError("invalid_request_id")
    request_dir = private_root / "wearable-imports" / request_id
    audit_path = private_root / "wearable-imports" / "deletion-audit" / f"{request_id}.json"
    if audit_path.exists():
        raise DeleteError("request_already_deleted")
    manifest_path = request_dir / "manifest.json"
    if not manifest_path.is_file():
        raise DeleteError("request_not_found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("request_id") != request_id:
        raise DeleteError("request_binding_mismatch")
    deleted = []
    for name in ("raw", "normalized", "derived", "receipts"):
        target = request_dir / name
        if target.exists():
            shutil.rmtree(target)
            deleted.append(name)
    if any((request_dir / name).exists() for name in ("raw", "normalized", "derived", "receipts")):
        raise DeleteError("deletion_verification_failed")
    audit_dir = private_root / "wearable-imports" / "deletion-audit"
    audit_dir.mkdir(exist_ok=True)
    audit = {"request_id": request_id, "deleted_at": _now(), "deleted_categories": deleted, "operator_kind": operator_kind, "derived_data_readable": False}
    _write_json_new(audit_path, audit)
    return audit
