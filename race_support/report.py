"""Human-readable Phase 10 report."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from reporting_contract import technical_appendix


def build_markdown_report(plan: Mapping[str, Any]) -> str:
    lines = [
        "# 越野跑规划准备报告",
        "",
        "> Internal research only. Quantities remain unknown unless explicitly verified in training.",
        "",
        "## 先看结论",
        "",
        f"- selected model: `{plan['governance']['selected_model']}`",
        f"- user_facing_prediction_allowed: `{str(plan['governance']['user_facing_prediction_allowed']).lower()}`",
        f"- status: `{plan['plan_status']}`",
        "",
        "## 安全与使用边界",
        "",
    ]
    for key, value in plan["intake_plan"].items():
        lines.append(f"- {key}: `{value['status']}` / {value.get('range')}")
    lines.extend(["", "## Checkpoint plan", "", "| CP | Official supply | Private support | Drop bag | Action |", "|---|---|---|---|---|"])
    for cp in plan["checkpoints"]:
        lines.append(
            f"| {cp['name']} | {cp['official_supply']['status']} | {cp['private_support']['status']} | "
            f"{cp['drop_bag']['status']} | {'; '.join(cp['behavior_checklist'])} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Never trial a new food or product during the race.",
            "- Missing official or private-support facts remain unknown, not assumed.",
            "- Persistent vomiting, confusion, severe dehydration, heat illness, or hypothermia stops performance planning.",
        ]
    )
    lines.extend(technical_appendix(plan))
    return "\n".join(lines) + "\n"
