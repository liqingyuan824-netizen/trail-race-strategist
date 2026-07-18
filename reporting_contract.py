"""Shared public-report contract for Phases 9--13.

The contract deliberately keeps machine fields out of the runner-facing body.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

CONTRACT_VERSION = "2.0.0"
COMMON_TITLES = {
    "intake_confirmation": "越野跑规划资料确认",
    "planning_preparation": "越野跑规划准备报告",
    "race_strategy": "比赛策略与情景规划",
    "live_update": "比赛中状态更新",
    "race_retro": "赛后复盘",
}
REQUIRED = ("schema_name", "schema_version", "generated_at", "case_reference", "report_type", "workflow_stage", "report_status", "participant_reference", "target_event", "executive_summary", "received_information", "verified_facts", "unverified_information", "derived_results", "recommendations", "scenario_switches", "safety", "next_actions", "evaluation_boundary", "privacy", "provenance")

def apply_output_contract(payload: Mapping[str, Any], *, report_type: str, workflow_stage: str, report_status: str, case_reference: str = "anonymous_internal_case") -> dict[str, Any]:
    out = deepcopy(dict(payload))
    out.setdefault("schema_version", CONTRACT_VERSION)
    out.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    out.update({"case_reference": case_reference, "report_type": report_type, "workflow_stage": workflow_stage, "report_status": report_status})
    defaults: dict[str, Any] = {"participant_reference": None, "target_event": None, "executive_summary": {}, "received_information": {}, "verified_facts": {}, "unverified_information": [], "derived_results": {}, "recommendations": [], "scenario_switches": [], "safety": {}, "next_actions": [], "evaluation_boundary": {}, "privacy": {}, "provenance": []}
    for key, value in defaults.items(): out.setdefault(key, value)
    return out

def technical_appendix(payload: Mapping[str, Any]) -> list[str]:
    return ["## 技术附录", "", "- 本报告为基于已获取资料的参考估算，不构成完赛承诺；缺失训练、状态或路线资料会降低把握并扩大区间。", "- 详细机器字段、来源哈希与审计状态仅保存在 JSON 和内部日志，不在跑者正文展示。", "- 隐私保护：报告默认使用代号，不展示完整身份信息。", "- 未知信息在 JSON 中为 `null`，本文显示为“未知”或“尚未核验”。", ""]

def public_header(report_type: str, summary: str, *, red_stop: bool = False) -> list[str]:
    title = COMMON_TITLES[report_type]
    lines = [f"# {title}", ""]
    if red_stop:
        lines += ["## 安全停止", "", "请停止成绩规划，优先遵从赛方、救援或医疗人员指令。完赛时间、下一 CP 时间和追赶建议当前不可用。", "", "## 先看结论", "", summary, ""]
    else:
        lines += ["## 先看结论", "", summary, ""]
    return lines
