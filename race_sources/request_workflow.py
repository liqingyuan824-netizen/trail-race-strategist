"""Immutable three-input initializer for a complete runner-report workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any

from .acquisition import parse_target_event


def create_workflow_request(*, name: str, runner_id: str, target_event: str, output_root: Path) -> dict[str, Any]:
    """Create only the request boundary; downstream completion is not implied."""
    if not str(name).strip(): raise ValueError("NAME_REQUIRED")
    if not str(runner_id).strip().isdigit(): raise ValueError("EXACT_ITRA_RUNNER_ID_REQUIRED")
    if not str(target_event).strip(): raise ValueError("TARGET_EVENT_REQUIRED")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"req-{stamp}-{uuid.uuid4().hex}"
    request_dir = output_root / request_id
    request_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_name": "trail_race_report_request", "schema_version": "1.0.0", "request_id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "provided_name": str(name).strip(),
        "provided_runner_id": str(runner_id).strip(), "target_event_request": parse_target_event(target_event),
        "source_mode": "fresh_live_capture", "legacy_auto_reuse_allowed": False,
        "historical_evidence_mode": "explicit_replay_only",
        "required_requester_inputs": ["name", "itra_runner_id", "target_event"], "requester_materials_required": [],
        "next_agent_actions": ["fresh_itra_public_profile_capture", "resolve_target_year_and_group_from_public_sources",
            "execute_required_public_source_search_lanes", "capture_and_parse_all_discovered_attachments",
            "build_course_strategy_and_complete_report"],
    }
    (request_dir / "request_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"request_id": request_id, "request_dir": request_dir, "manifest": manifest}
