"""Human-readable Phase 13 report."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from reporting_contract import technical_appendix


def build_markdown_report(retro: Mapping[str, Any]) -> str:
    finish = retro["analysis"]["finish_error"]
    lines = [
        "# 赛后复盘",
        "",
        "> Local-only research artifact. Facts, inferences, and recommendations are separated.",
        "",
        "## 结果摘要",
        "",
        f"- selected model: `{retro['governance']['selected_model']}`",
        f"- actual live validation: `{retro['validation_status']['actual_live_validation']}`",
        f"- immutable snapshot id: `{retro['immutability']['snapshot_id']}`",
        f"- general model contribution allowed: `{str(retro['general_model']['contribution_allowed']).lower()}`",
        "",
        "## 已确认事实",
        "",
        f"- result status: `{retro['facts']['result_status']}`",
        f"- finish time: `{retro['facts']['finish_time_minutes']}` minutes",
        f"- verified checkpoint rows: `{len(retro['facts']['checkpoints'])}`",
        "",
        "## Derived analysis",
        "",
        f"- finish error: `{finish}`",
        f"- checkpoint error rows: `{len(retro['analysis']['checkpoint_errors'])}`",
        f"- movement/stopped decomposition: `{retro['analysis']['movement_and_stopped']}`",
        "",
        "## Recommendations",
        "",
    ]
    lines.extend(f"- {item['recommendation']}" for item in retro["recommendations"])
    lines.extend(["", "## Limits", "", "- A single race cannot permanently redefine ability.", "- Conditions are not treated as causal unless independently established.", "- Validation or holdout results are never used to tune this personal model."])
    lines.extend(technical_appendix(retro))
    return "\n".join(lines) + "\n"
