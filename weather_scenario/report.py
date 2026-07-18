"""Human-readable Phase 11 report."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from reporting_contract import technical_appendix


def build_markdown_report(bundle: Mapping[str, Any]) -> str:
    lines = [
        "# 越野跑规划准备报告",
        "",
        "> Internal research only. Climate baselines are not race-day forecasts.",
        "",
        "## 先看结论",
        "",
        f"- phase: `{bundle['forecast_phase']}`",
        f"- active layer: `{bundle['active_layer']}`",
        f"- user_facing_prediction_allowed: `{str(bundle['governance']['user_facing_prediction_allowed']).lower()}`",
        "",
        "## Evidence layers",
        "",
    ]
    for name, layer in bundle["layers"].items():
        lines.append(f"- {name}: `{layer['status']}`; freshness `{layer['freshness_status']}`")
    lines.extend(["", "## Scenario playbook", ""])
    for scenario in bundle["scenarios"]:
        lines.append(f"### {scenario['scenario_id']} ({scenario['severity']})")
        lines.append("")
        lines.append(f"- Strategy: {scenario['strategy_action']}")
        lines.append(f"- Equipment: {scenario['equipment_action']}")
        lines.append("")
    lines.extend(["## Safety", "", "Thunderstorm, hypothermia, heat illness, or official stop instructions remove performance targets."])
    lines.extend(technical_appendix(bundle))
    return "\n".join(lines) + "\n"
