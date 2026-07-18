"""No-overwrite writers and compact audit reports."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any


def _report(graph: Mapping[str, Any], prediction: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 7B / 8B Internal Research Report",
        "",
        f"- Status: `{prediction['status']}`",
        "- Phase 8A decision: `retain_distance_only`",
        "- Complex candidate validated: `false`",
        "- User-facing prediction allowed: `false`",
        "- Validation or holdout evaluation performed: `false`",
        f"- Reference paths: `{prediction['diagnostics']['numeric_reference_path_count']}`",
        f"- Independent groups: `{prediction['diagnostics']['independent_reference_group_count']}`",
        f"- Conflict: `{str(prediction['conflict_analysis']['conflict']).lower()}`",
        "",
        "## Paths",
        "",
    ]
    for path in prediction["paths"]:
        lines.append(
            f"- `{path['path_id']}`: available={str(path.get('available')).lower()}, "
            f"directional_only={str(path.get('directional_only')).lower()}, "
            f"weight={path.get('final_dynamic_weight', 0)}"
        )
    lines.extend([
        "",
        "## Boundary",
        "",
        "This artifact is internal-only, uncalibrated, and cannot replace the retained distance-only baseline.",
        "Elite anchors are directional only. Missing references degrade to distance_only.",
        "No Phase 10 work is included.",
    ])
    return "\n".join(lines) + "\n"


def write_reference_outputs(*, graph: Mapping[str, Any], prediction: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    files: dict[str, Any] = {
        "reference_graph.json": graph,
        "multipath_prediction.json": prediction,
        "phase7b8b_report.md": _report(graph, prediction),
    }
    for name, value in files.items():
        path = output_dir / name
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
