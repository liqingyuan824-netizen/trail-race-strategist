"""Fail-closed staging of activity FIT records from an authorized ZIP archive.

This module deliberately stops before W1 import.  It never inspects non-FIT
payloads in a mixed account export, and it emits no public artifact.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .fit_adapter import FitDecodeError, parse_garmin_fit
from .pipeline import IngestError, _is_e_drive, _load_consent


_MAX_NESTED_DEPTH = 2
_MAX_MEMBER_COUNT = 3_000
_MAX_MEMBER_BYTES = 50 * 1024 * 1024
# Nested ZIP containers and the final FIT candidates are separate payload
# classes.  A nested container must be read to inspect it, but its bytes are
# not a FIT candidate and must not consume the FIT-candidate budget again.
_MAX_NESTED_ARCHIVE_BYTES = 200 * 1024 * 1024
_MAX_FIT_CANDIDATE_BYTES = 200 * 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(name: str) -> None:
    # ZIP paths are POSIX by specification, but reject Windows separators too:
    # they become traversal paths when later handled on Windows.
    if not name or "\\" in name:
        raise IngestError("archive_path_traversal_detected")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise IngestError("archive_path_traversal_detected")


def _validate_zip_members(
    archive: zipfile.ZipFile,
    *,
    seen_count: list[int],
    nested_archive_size: list[int],
    fit_candidate_size: list[int],
) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    seen_count[0] += len(infos)
    if seen_count[0] > _MAX_MEMBER_COUNT:
        raise IngestError("archive_member_limit_exceeded")
    for info in infos:
        _safe_member_name(info.filename)
        if info.flag_bits & 0x1:
            raise IngestError("encrypted_archive_member_rejected")
        # Every member is checked for unsafe metadata above. Only FIT files and
        # nested ZIPs are ever read, so only those objects consume a payload
        # budget. Mixed account exports commonly include large JSON/media
        # payloads; treating their central-directory sizes as bytes we will
        # read would incorrectly reject an otherwise valid FIT export.
        suffix = PurePosixPath(info.filename).suffix.lower()
        if suffix in {".fit", ".zip"}:
            if info.file_size < 0 or info.file_size > _MAX_MEMBER_BYTES:
                raise IngestError("archive_member_size_limit_exceeded")
            if suffix == ".zip":
                nested_archive_size[0] += info.file_size
                if nested_archive_size[0] > _MAX_NESTED_ARCHIVE_BYTES:
                    raise IngestError("nested_archive_read_budget_exceeded")
            else:
                fit_candidate_size[0] += info.file_size
                if fit_candidate_size[0] > _MAX_FIT_CANDIDATE_BYTES:
                    raise IngestError("fit_candidate_budget_exceeded")
    return infos


def _fit_candidates(
    payload: Path | bytes,
    *,
    depth: int,
    seen_count: list[int],
    nested_archive_size: list[int],
    fit_candidate_size: list[int],
) -> list[tuple[str, bytes]]:
    """Return FIT payloads only; nested ZIP bytes are read solely as archives."""
    try:
        from io import BytesIO

        archive_source: Path | BytesIO = payload if isinstance(payload, Path) else BytesIO(payload)
        with zipfile.ZipFile(archive_source) as archive:
            infos = _validate_zip_members(
                archive,
                seen_count=seen_count,
                nested_archive_size=nested_archive_size,
                fit_candidate_size=fit_candidate_size,
            )
            found: list[tuple[str, bytes]] = []
            for info in infos:
                if info.is_dir():
                    continue
                suffix = PurePosixPath(info.filename).suffix.lower()
                if suffix == ".fit":
                    # Reading a FIT candidate is the only activity-payload read.
                    found.append((info.filename, archive.read(info)))
                elif suffix == ".zip" and depth < _MAX_NESTED_DEPTH:
                    nested = archive.read(info)
                    try:
                        found.extend(
                            _fit_candidates(
                                nested,
                                depth=depth + 1,
                                seen_count=seen_count,
                                nested_archive_size=nested_archive_size,
                                fit_candidate_size=fit_candidate_size,
                            )
                        )
                    except zipfile.BadZipFile as exc:
                        raise IngestError("nested_archive_invalid") from exc
                elif suffix == ".zip":
                    raise IngestError("nested_archive_depth_limit_exceeded")
            return found
    except zipfile.BadZipFile as exc:
        raise IngestError("invalid_zip_archive") from exc


def stage_fit_archive(
    *,
    source_archive: Path,
    staging_root: Path,
    consent_file: Path,
    staging_request_id: str,
    source_brand: str,
) -> dict[str, Any]:
    """Stage validated activity FIT records into a new immutable private request.

    No import, feature derivation, research action, or prediction action occurs
    here.  A malformed or risky archive fails before a target is created.
    """
    if not isinstance(source_archive, Path) or not source_archive.is_file() or source_archive.suffix.lower() != ".zip":
        raise IngestError("source_archive_must_be_existing_zip")
    if not isinstance(staging_root, Path) or not staging_root.is_dir() or not _is_e_drive(staging_root):
        raise IngestError("staging_root_must_be_existing_private_directory")
    if not isinstance(staging_request_id, str) or not re.fullmatch(r"fit-stage-[A-Za-z0-9-]+", staging_request_id):
        raise IngestError("invalid_staging_request_id")
    if source_brand not in {"garmin", "coros"}:
        raise IngestError("invalid_source_brand")
    if not consent_file.is_file():
        raise IngestError("consent_file_not_found")
    consent, consent_sha256 = _load_consent(consent_file)
    if consent["source_brand"] != source_brand:
        raise IngestError("consent_source_brand_mismatch")

    target = staging_root / "fit-staging" / staging_request_id
    if target.exists():
        raise IngestError("staging_request_target_already_exists")
    archive_sha256 = _sha256_file(source_archive)
    try:
        candidates = _fit_candidates(
            source_archive,
            depth=0,
            seen_count=[0],
            nested_archive_size=[0],
            fit_candidate_size=[0],
        )
    except OSError as exc:
        raise IngestError("source_archive_unreadable") from exc
    if not candidates:
        raise IngestError("archive_contains_no_fit_candidates")

    accepted: list[tuple[str, bytes, str, dict[str, Any]]] = []
    rejected = 0
    seen_hashes: set[str] = set()
    # The temporary candidate is on the explicitly supplied private staging
    # root and is removed before any immutable output is created.
    with tempfile.TemporaryDirectory(dir=staging_root) as temporary:
        temporary_root = Path(temporary)
        for ordinal, (member_name, payload) in enumerate(candidates):
            source_sha256 = _sha256_bytes(payload)
            if source_sha256 in seen_hashes:
                rejected += 1
                continue
            seen_hashes.add(source_sha256)
            candidate = temporary_root / f"candidate-{ordinal}.fit"
            candidate.write_bytes(payload)
            try:
                parsed = parse_garmin_fit(candidate)
            except FitDecodeError:
                rejected += 1
                continue
            accepted.append((member_name, payload, source_sha256, parsed))
    if not accepted:
        raise IngestError("archive_contains_no_valid_activity_fit")

    try:
        target.mkdir(parents=True)
        activities_dir = target / "activities"
        activities_dir.mkdir()
        selected: list[dict[str, Any]] = []
        for ordinal, (member_name, payload, source_sha256, parsed) in enumerate(accepted):
            staged_name = f"activity-{ordinal + 1:04d}-{source_sha256[:16]}.fit"
            (activities_dir / staged_name).write_bytes(payload)
            selected.append({
                "archive_member": member_name,
                "source_sha256": source_sha256,
                "staged_filename": staged_name,
                "parser": "local_fit_activity_aggregate_v1",
                "activity_date": datetime.fromtimestamp(parsed["started_at_unix"], UTC).date().isoformat(),
            })
        receipt = {
            "schema_name": "wearable_fit_staging_receipt",
            "schema_version": "1.0.0",
            "staging_request_id": staging_request_id,
            "created_at": _now(),
            "source_brand": source_brand,
            "source_archive_sha256": archive_sha256,
            "consent_receipt_sha256": consent_sha256,
            "selected_activity_count": len(selected),
            "rejected_fit_candidate_count": rejected,
            "selected_activity_sources": selected,
            "governance": {"allow_model_research": False, "user_facing_prediction_allowed": False},
            "next_step": "dry_run_import_required",
        }
        (target / "staging_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise IngestError("staging_write_failed") from exc
    return {
        "status": "staged",
        "staging_request_id": staging_request_id,
        "staging_dir": str(target),
        "selected_activity_count": len(accepted),
        "rejected_fit_candidate_count": rejected,
        "next_step": "dry_run_import_required",
        "allow_model_research": False,
        "user_facing_prediction_allowed": False,
    }
