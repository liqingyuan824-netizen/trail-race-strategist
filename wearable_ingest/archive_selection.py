"""Authorized, memory-only selection of activity FIT files from account exports.

This is deliberately a staging boundary, not an import or research operation.
Non-FIT archive members may be read only to classify nested containers; they
are never extracted, logged, or retained.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from .fit_adapter import FitDecodeError, parse_garmin_fit
from .pipeline import IngestError, _is_e_drive, _load_consent

_MAX_MEMBERS = 20_000
_MAX_DEPTH = 3
_MAX_TOP_LEVEL_ARCHIVE_BYTES = 1024 * 1024 * 1024
_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_NESTED_BYTES = 512 * 1024 * 1024
_MAX_FIT_BYTES = 512 * 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: dict[str, Any]) -> str:
    return _digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def issue_archive_selection_authorization(*, selection_request_id: str, private_alias: str, consented_at: str, allowed_start_date: str, allowed_end_date: str, authorization_root: Path, w1_consent_file: Path) -> dict[str, Any]:
    """Write one immutable authorization that supplements, never alters, W1."""
    if not re.fullmatch(r"archive-selection-[A-Za-z0-9-]+", selection_request_id or ""):
        raise IngestError("invalid_archive_selection_request_id")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", private_alias or ""):
        raise IngestError("invalid_archive_selection_private_alias")
    if not isinstance(authorization_root, Path) or not authorization_root.is_dir() or not _is_e_drive(authorization_root):
        raise IngestError("archive_selection_root_must_be_existing_private_directory")
    w1, w1_sha = _load_consent(w1_consent_file)
    if w1["subject_private_alias"] != private_alias:
        raise IngestError("archive_selection_w1_alias_mismatch")
    if allowed_start_date != w1["allowed_data_window"]["start_date"] or allowed_end_date != w1["allowed_data_window"]["end_date"]:
        raise IngestError("archive_selection_window_must_match_w1")
    try:
        timestamp = datetime.fromisoformat(consented_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise IngestError("invalid_archive_selection_confirmation_time") from exc
    if not consented_at.endswith("Z") or timestamp.tzinfo is None:
        raise IngestError("invalid_archive_selection_confirmation_time")
    target = authorization_root / selection_request_id
    if target.exists():
        raise IngestError("archive_selection_request_target_already_exists")
    unsigned = {
        "schema_name": "archive_selection_authorization", "schema_version": "1.0.0",
        "authorization_id": f"archive-selection-auth-{uuid4()}", "selection_request_id": selection_request_id,
        "created_at": _now(), "consented_at": consented_at, "subject_private_alias": private_alias,
        "allowed_data_window": {"start_date": allowed_start_date, "end_date": allowed_end_date},
        "w1_consent_receipt_sha256": w1_sha, "local_full_archive_inspection": True,
        "revocation_method": "selection_request_id_deletion", "retention_days": 90,
        "governance": {"allow_model_research": False, "user_facing_prediction_allowed": False},
    }
    receipt = {**unsigned, "immutable_authorization_hash": _canonical(unsigned)}
    try:
        target.mkdir()
        path = target / "archive_selection_authorization.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2); handle.write("\n")
    except OSError as exc:
        raise IngestError("archive_selection_authorization_write_failed") from exc
    return {"status": "issued", "selection_request_id": selection_request_id, "authorization_path": str(path), "allow_model_research": False, "user_facing_prediction_allowed": False}


def _load_authorization(path: Path, consent: dict[str, Any], consent_sha: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestError("invalid_archive_selection_authorization") from exc
    required = {"schema_name", "schema_version", "authorization_id", "selection_request_id", "created_at", "consented_at", "subject_private_alias", "allowed_data_window", "w1_consent_receipt_sha256", "local_full_archive_inspection", "revocation_method", "retention_days", "governance", "immutable_authorization_hash"}
    if not isinstance(value, dict) or set(value) != required or value.get("schema_name") != "archive_selection_authorization" or value.get("schema_version") != "1.0.0":
        raise IngestError("invalid_archive_selection_authorization_schema")
    unsigned = {key: item for key, item in value.items() if key != "immutable_authorization_hash"}
    if value["immutable_authorization_hash"] != _canonical(unsigned):
        raise IngestError("archive_selection_authorization_hash_mismatch")
    if not re.fullmatch(r"archive-selection-[A-Za-z0-9-]+", value["selection_request_id"]):
        raise IngestError("invalid_archive_selection_authorization_schema")
    if value["subject_private_alias"] != consent["subject_private_alias"] or value["w1_consent_receipt_sha256"] != consent_sha:
        raise IngestError("archive_selection_authorization_consent_mismatch")
    if value["allowed_data_window"] != consent["allowed_data_window"] or value["local_full_archive_inspection"] is not True or value["revocation_method"] != "selection_request_id_deletion" or type(value["retention_days"]) is not int or value["retention_days"] < 1:
        raise IngestError("archive_selection_authorization_not_authorized")
    if value["governance"] != {"allow_model_research": False, "user_facing_prediction_allowed": False}:
        raise IngestError("archive_selection_governance_not_locked")
    return value


def _safe(name: str) -> None:
    item = PurePosixPath(name)
    if not name or "\\" in name or item.is_absolute() or ".." in item.parts:
        raise IngestError("archive_path_traversal_detected")


def _select(payload: bytes, *, depth: int, counters: dict[str, int], prefix: str = "") -> list[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist(); counters["members"] += len(infos)
            if counters["members"] > _MAX_MEMBERS: raise IngestError("archive_member_limit_exceeded")
            selected: list[tuple[str, bytes]] = []
            for info in infos:
                _safe(info.filename)
                if info.flag_bits & 1: raise IngestError("encrypted_archive_member_rejected")
                if info.is_dir(): continue
                suffix = PurePosixPath(info.filename).suffix.lower()
                if suffix not in {".fit", ".zip"}: continue
                if info.file_size < 0 or info.file_size > _MAX_MEMBER_BYTES: raise IngestError("archive_member_size_limit_exceeded")
                member = archive.read(info)  # FIT or nested container only; never non-activity payload.
                if suffix == ".fit":
                    counters["fit_bytes"] += len(member)
                    if counters["fit_bytes"] > _MAX_FIT_BYTES: raise IngestError("fit_candidate_budget_exceeded")
                    selected.append((prefix + info.filename, member))
                else:
                    if depth >= _MAX_DEPTH: raise IngestError("nested_archive_depth_limit_exceeded")
                    counters["nested_bytes"] += len(member)
                    if counters["nested_bytes"] > _MAX_NESTED_BYTES: raise IngestError("nested_archive_read_budget_exceeded")
                    selected.extend(_select(member, depth=depth + 1, counters=counters, prefix=prefix + info.filename + "/"))
            return selected
    except zipfile.BadZipFile as exc:
        raise IngestError("invalid_zip_archive") from exc


def stage_authorized_full_archive(*, source_archive: Path, staging_root: Path, w1_consent_file: Path, authorization_file: Path, staging_request_id: str, source_brand: str) -> dict[str, Any]:
    """Select parseable activity FIT files to a fresh staging child, fail closed."""
    if not isinstance(source_archive, Path) or not source_archive.is_file() or source_archive.suffix.lower() != ".zip": raise IngestError("source_archive_must_be_existing_zip")
    if source_archive.stat().st_size > _MAX_TOP_LEVEL_ARCHIVE_BYTES: raise IngestError("source_archive_read_budget_exceeded")
    if not isinstance(staging_root, Path) or not staging_root.is_dir() or not _is_e_drive(staging_root): raise IngestError("staging_root_must_be_existing_private_directory")
    if not re.fullmatch(r"fit-stage-[A-Za-z0-9-]+", staging_request_id or ""): raise IngestError("invalid_staging_request_id")
    consent, consent_sha = _load_consent(w1_consent_file)
    if source_brand != consent["source_brand"]: raise IngestError("consent_source_brand_mismatch")
    authorization = _load_authorization(authorization_file, consent, consent_sha)
    target = staging_root / "fit-staging" / staging_request_id
    if target.exists(): raise IngestError("staging_request_target_already_exists")
    try:
        candidates = _select(source_archive.read_bytes(), depth=0, counters={"members": 0, "nested_bytes": 0, "fit_bytes": 0})
    except OSError as exc: raise IngestError("source_archive_unreadable") from exc
    accepted: list[tuple[str, bytes, str, dict[str, Any]]] = []; seen: set[str] = set(); rejected = 0
    with tempfile.TemporaryDirectory(dir=staging_root) as temporary:
        for ordinal, (name, payload) in enumerate(candidates):
            digest = _digest(payload)
            if digest in seen: rejected += 1; continue
            seen.add(digest); candidate = Path(temporary) / f"candidate-{ordinal}.fit"; candidate.write_bytes(payload)
            try: parsed = parse_garmin_fit(candidate)
            except FitDecodeError: rejected += 1; continue
            accepted.append((name, payload, digest, parsed))
    if not accepted: raise IngestError("archive_contains_no_valid_activity_fit")
    try:
        target.mkdir(parents=True); activities = target / "activities"; activities.mkdir(); selected = []
        for ordinal, (name, payload, digest, parsed) in enumerate(accepted, 1):
            filename = f"activity-{ordinal:04d}-{digest[:16]}.fit"; (activities / filename).write_bytes(payload)
            selected.append({"source_sha256": digest, "staged_filename": filename, "parser": "local_fit_activity_aggregate_v1", "activity_date": datetime.fromtimestamp(parsed["started_at_unix"], UTC).date().isoformat(), "selection_reason": "parseable_activity_fit"})
        receipt = {"schema_name": "authorized_archive_selection_staging_receipt", "schema_version": "1.0.0", "staging_request_id": staging_request_id, "selection_request_id": authorization["selection_request_id"], "created_at": _now(), "source_brand": source_brand, "source_archive_sha256": _file_digest(source_archive), "w1_consent_receipt_sha256": consent_sha, "archive_selection_authorization_sha256": _file_digest(authorization_file), "selected_activity_count": len(selected), "rejected_fit_candidate_count": rejected, "selected_activity_sources": selected, "governance": {"allow_model_research": False, "user_facing_prediction_allowed": False}, "next_step": "dry_run_import_required"}
        (target / "staging_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True); raise IngestError("staging_write_failed") from exc
    return {"status": "staged", "staging_request_id": staging_request_id, "staging_dir": str(target), "selected_activity_count": len(accepted), "rejected_fit_candidate_count": rejected, "next_step": "dry_run_import_required", "allow_model_research": False, "user_facing_prediction_allowed": False}
