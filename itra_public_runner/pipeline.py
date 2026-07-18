"""Orchestration layer for offline replay and live headed acquisition."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .mapper import map_profile
from .parser import parse_profile


def replay_capture(profile_html: Path, *, name: str, runner_id: str, output_json: Path | None = None) -> dict:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    parsed = parse_profile(profile_html.read_text(encoding="utf-8"))
    result = map_profile(
        parsed,
        name=name,
        runner_id=runner_id,
        retrieved_at=retrieved_at,
        evidence=[str(profile_html)],
    )
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
