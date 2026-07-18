"""Human-readable Phase 12 report."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from reporting_contract import technical_appendix


def build_markdown_report(snapshot: Mapping[str, Any]) -> str:
    decision = snapshot["decision"]
    lines = [
        "# 比赛中状态更新",
        "",
        "> Internal research only. This is not a validated user-facing prediction.",
        "",
    ]
    if decision.get("red_flag_stop"):
        stop_reasons = decision.get("stop_reasons") or []
        lines.extend(
            [
                "## 安全停止\n\n## SAFETY STOP",
                "",
                f"- action: `{decision['action']}`",
                f"- stop reasons: `{', '.join(str(reason) for reason in stop_reasons)}`",
                "- Stop performance planning and follow race staff or medical staff immediately.",
                "- Catch-up pacing is not allowed.",
                "- Finish-time and next-checkpoint time targets are unavailable（不可用）.",
                "",
            ]
        )
    lines.extend([
        "## 安全状态\n\n## Status",
        "",
        f"- mode: `{snapshot['processing_mode']}`",
        f"- timing mode: `{snapshot['timing_state']['timing_mode']}`",
        f"- actual live validation: `{snapshot['validation_status']['actual_live_validation']}`",
        f"- strategy action: `{decision['action']}`",
        f"- latest information age: `{snapshot['freshness']['latest_information_age_minutes']}` minutes",
        "",
        "## Evidence processing",
        "",
        f"- accepted: {snapshot['diagnostics']['accepted_event_count']}",
        f"- duplicates removed: {snapshot['diagnostics']['duplicate_event_count']}",
        f"- conflicts: {snapshot['diagnostics']['conflict_count']}",
        f"- out of order input: `{str(snapshot['diagnostics']['out_of_order_input']).lower()}`",
        "",
        "## 更新后的行动\n\n## Derived update",
        "",
        f"- observed checkpoint: `{snapshot['timing_state']['latest_checkpoint']}`",
        f"- next checkpoint: `{(snapshot.get('next_checkpoint') or {}).get('name')}`",
        f"- cutoff risk: `{(snapshot.get('next_checkpoint') or {}).get('cutoff_risk')}`",
        f"- updated finish range: `{snapshot.get('updated_finish_range_minutes')}`",
        "",
        "## Safety",
        "",
        "- Red flags and official race or medical stop instructions override all time targets.",
        "- Stale observations are not described as the runner's current state.",
        "- Missing or delayed timing is never filled with a guessed checkpoint.",
    ])
    lines.extend(technical_appendix(snapshot))
    return "\n".join(lines) + "\n"
