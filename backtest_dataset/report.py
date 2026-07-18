"""Report builders for the dataset layer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _fmt(value: Any) -> str:
    return "null" if value is None else str(value)


def build_validation_markdown(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Dataset Validation Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Overall status: `{report['overall_status']}`")
    lines.append(f"- Records imported: `{report['summary']['total_records']}`")
    lines.append(f"- Real records: `{report['summary'].get('real_records', 0)}`")
    lines.append(f"- Synthetic records: `{report['summary'].get('synthetic_records', 0)}`")
    lines.append(f"- Real usable records: `{report['summary']['real_usable_records']}`")
    lines.append(f"- Synthetic usable records: `{report['summary']['synthetic_usable_records']}`")
    lines.append(f"- Total eligible folds: `{report['summary'].get('total_eligible_folds', report['summary']['eligible_folds'])}`")
    lines.append(f"- Real eligible folds: `{report['summary'].get('real_eligible_folds', report['summary']['eligible_folds'])}`")
    lines.append(f"- Synthetic eligible folds: `{report['summary'].get('synthetic_eligible_folds', 0)}`")
    lines.append(f"- Formal gate basis: `{report.get('formal_gate_basis', 'real_eligible_folds')}`")
    lines.append(f"- Calibration allowed: `{report.get('calibration_allowed', False)}`")
    lines.append(f"- User-facing prediction allowed: `{report.get('user_facing_prediction_allowed', False)}`")
    lines.append("")
    lines.append("## Compliance")
    for status, count in report["summary"]["compliance_counts"].items():
        lines.append(f"- {status}: `{count}`")
    lines.append("")
    lines.append("## Fold Depth")
    for depth, count in report["summary"]["fold_depth_counts"].items():
        lines.append(f"- {depth}: `{count}`")
    lines.append("")
    lines.append("## Runner Coverage")
    for runner_id, stats in report["runner_summary"].items():
        lines.append(
            f"- {runner_id}: records={stats['record_count']}, real_usable={stats.get('real_usable_record_count', 0)}, synthetic_usable={stats.get('synthetic_usable_record_count', 0)}, "
            f"real_folds={stats.get('real_eligible_fold_count', stats['eligible_fold_count'])}, synthetic_folds={stats.get('synthetic_eligible_fold_count', 0)}"
        )
    lines.append("")
    lines.append("## Missing Materials")
    for item in report["missing_materials"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Notes")
    for item in report["notes"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def build_missing_materials_markdown(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 合规与缺失资料清单")
    lines.append("")
    lines.append("## 不足与限制")
    for item in report["missing_materials"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 可保留但不可进入正式回测的资料")
    for item in report["restricted_materials"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 证据与模板")
    for item in report["evidence_materials"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)
