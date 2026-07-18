"""Immutable request-scoped runner capture contracts.

New requests never discover local evidence.  A saved HTML file is accepted only
when the caller explicitly selects replay mode.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .pipeline import replay_capture
from .browser import run_acquire


class RequestBindingError(ValueError):
    """Machine-readable fail-closed request identity error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _url_runner_id(profile_url: Any) -> str | None:
    match = re.search(r"/(\d+)/?$", str(profile_url or ""))
    return match.group(1) if match else None


def _error(code: str) -> None:
    raise RequestBindingError(code)


def validate_request_binding(manifest: Mapping[str, Any], profile: Mapping[str, Any], profile_html: Path) -> None:
    """Require one name/ID/hash chain before any downstream use."""
    request_id = str(manifest.get("request_id") or "")
    provided_id = str(manifest.get("provided_runner_id") or "")
    provided_name = normalize_name(manifest.get("provided_name"))
    query = profile.get("query") if isinstance(profile.get("query"), Mapping) else {}
    identity = profile.get("identity") if isinstance(profile.get("identity"), Mapping) else {}
    binding = profile.get("request_binding") if isinstance(profile.get("request_binding"), Mapping) else {}
    if not request_id or binding.get("request_id") != request_id:
        _error("REQUEST_ID_MISMATCH")
    if binding.get("profile_html_sha256") != manifest.get("profile_html_sha256"):
        _error("PROFILE_BINDING_HASH_MISMATCH")
    if not profile_html.is_file() or sha256_file(profile_html) != manifest.get("profile_html_sha256"):
        _error("PROFILE_HTML_HASH_MISMATCH")
    ids = [provided_id, str(query.get("runner_id") or ""), str(identity.get("runner_id") or ""), str(_url_runner_id(identity.get("profile_url")) or "")]
    if not provided_id or any(value != provided_id for value in ids):
        _error("RUNNER_ID_CHAIN_MISMATCH")
    names = [provided_name, normalize_name(query.get("runner_name")), normalize_name(identity.get("name"))]
    if not provided_name or any(value != provided_name for value in names):
        _error("RUNNER_NAME_CHAIN_MISMATCH")


def create_replay_request(*, name: str, runner_id: str, profile_html: Path, output_root: Path) -> dict[str, Any]:
    """Create one immutable explicit-replay request from a caller-selected HTML file."""
    if not profile_html.is_file():
        _error("REPLAY_PROFILE_HTML_NOT_FOUND")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"req-{stamp}-{uuid.uuid4().hex}"
    session_dir = output_root / request_id
    session_dir.mkdir(parents=True, exist_ok=False)
    copied_html = session_dir / "profile.html"
    shutil.copyfile(profile_html, copied_html)
    profile = replay_capture(copied_html, name=name, runner_id=runner_id)
    profile_url = profile.get("identity", {}).get("profile_url")
    manifest = {
        "schema_name": "runner_request_manifest",
        "schema_version": "1.0.0",
        "request_id": request_id,
        "provided_name": name,
        "provided_runner_id": str(runner_id),
        "source_mode": "explicit_replay",
        "created_at": _utc_now(),
        "profile_html_sha256": sha256_file(copied_html),
        "profile_url": profile_url,
        "legacy_auto_reuse_allowed": False,
        "notes": ["Replay is caller-selected only; no local evidence, participant file, or report was searched or reused automatically."],
    }
    profile["request_binding"] = {
        "request_id": request_id,
        "source_mode": manifest["source_mode"],
        "profile_html_sha256": manifest["profile_html_sha256"],
        "profile_html": "profile.html",
    }
    validate_request_binding(manifest, profile, copied_html)
    (session_dir / "runner_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    (session_dir / "request_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"request_id": request_id, "session_dir": session_dir, "manifest": manifest, "runner_profile": profile}


def create_live_request(*, name: str, runner_id: str, output_root: Path) -> dict[str, Any]:
    """Capture a fresh headed public profile into a brand-new request session."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"req-{stamp}-{uuid.uuid4().hex}"
    session_dir = output_root / request_id
    trace = run_acquire(name, runner_id, session_dir)
    if trace.get("status") != "profile_captured":
        _error(f"FRESH_LIVE_CAPTURE_{str(trace.get('status') or 'FAILED').upper()}")
    profile_html = session_dir / "profile.html"
    profile = replay_capture(profile_html, name=name, runner_id=runner_id)
    manifest = {
        "schema_name": "runner_request_manifest",
        "schema_version": "1.0.0",
        "request_id": request_id,
        "provided_name": name,
        "provided_runner_id": str(runner_id),
        "source_mode": "fresh_live_capture",
        "created_at": _utc_now(),
        "profile_html_sha256": sha256_file(profile_html),
        "profile_url": profile.get("identity", {}).get("profile_url"),
        "legacy_auto_reuse_allowed": False,
    }
    profile["request_binding"] = {"request_id": request_id, "source_mode": manifest["source_mode"], "profile_html_sha256": manifest["profile_html_sha256"], "profile_html": "profile.html"}
    validate_request_binding(manifest, profile, profile_html)
    (session_dir / "runner_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    (session_dir / "request_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"request_id": request_id, "session_dir": session_dir, "manifest": manifest, "runner_profile": profile}


def load_bound_request(*, request_manifest_path: Path, runner_profile_path: Path) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Load a request only when its profile is from that exact session and hash."""
    try:
        manifest = json.loads(request_manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RequestBindingError("REQUEST_MANIFEST_JSON_INVALID") from exc
    try:
        profile = json.loads(runner_profile_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RequestBindingError("RUNNER_PROFILE_JSON_INVALID") from exc
    if not isinstance(manifest, Mapping) or not isinstance(profile, Mapping):
        _error("REQUEST_OR_PROFILE_JSON_OBJECT_REQUIRED")
    session_dir = request_manifest_path.resolve().parent
    if runner_profile_path.resolve().parent != session_dir or runner_profile_path.name != "runner_profile.json":
        _error("RUNNER_PROFILE_OUTSIDE_REQUEST_SESSION")
    validate_request_binding(manifest, profile, session_dir / "profile.html")
    return manifest, profile
