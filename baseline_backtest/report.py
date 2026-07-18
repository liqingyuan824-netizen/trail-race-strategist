"""Markdown report rendering for Phase 8A baseline backtest."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    return str(value)


def _bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def build_backtest_markdown(report: Mapping[str, Any]) -> str:
    manifest = report["dataset_manifest"]
    model = report["model_spec"]
    metrics = report["metrics"]
    ablations = report["ablations"]
    comparison = report.get("distance_baseline_comparison", {})
    predictions = report["prediction_rows"]
    leak_checks = report["leak_checks"]

    lines: list[str] = []
    lines.append("# Phase 8A Baseline Backtest Report")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- Phase status: `{report['phase_status']}`")
    lines.append(f"- Calibration status: `{report['calibration_status']}`")
    lines.append(f"- Calibrated candidate: `{_bool(report['calibrated_candidate'])}`")
    lines.append(f"- User-facing prediction allowed: `{_bool(report['user_facing_prediction_allowed'])}`")
    lines.append(f"- Evaluated samples: `{metrics['valid_sample_count']}`")
    lines.append(f"- Insufficient personal sample: `{_bool(report['insufficient_personal_sample'])}`")
    lines.append("")
    lines.append("## Frozen Model")
    lines.append(f"- Model name: `{model['model_name']}`")
    lines.append(f"- Code version: `{model['code_version']}`")
    lines.append(f"- Formula version: `{model['formula_version']}`")
    lines.append(f"- Parameters: `{model['parameter_summary']}`")
    lines.append(f"- Frozen candidate: `{model['frozen_candidate']}`")
    lines.append("")
    lines.append("## Dataset")
    lines.append(f"- Source file: `{manifest['sources'][0]['source_uri']}`")
    lines.append(f"- File hash: `{manifest['sources'][0]['file_hash']}`")
    lines.append(f"- Acquisition basis: `{manifest['sources'][0]['use_basis']}`")
    lines.append(f"- Auto access allowed: `{_bool(manifest['sources'][0]['auto_access_allowed'])}`")
    lines.append(f"- Effective backtest samples: `{manifest['dataset']['effective_valid_sample_count']}`")
    lines.append(f"- Timed historical rows: `{manifest['dataset']['timed_race_count']}`")
    lines.append(f"- Skipped rows: `{manifest['dataset']['skipped_count']}`")
    lines.append("")
    lines.append("## Leak Checks")
    for item in leak_checks:
        lines.append(f"- {item['check']}: `{_bool(item['passed'])}` - {item['note']}")
    lines.append("")
    lines.append("## Metrics")
    lines.append(f"- MdAPE: `{_fmt(metrics['mdape_pct'])}`")
    lines.append(f"- MAE (min): `{_fmt(metrics['mae_minutes'])}`")
    lines.append(f"- Bias (min): `{_fmt(metrics['bias_minutes'])}`")
    lines.append(f"- Optimistic coverage: `{_fmt(metrics['coverage']['optimistic'])}`")
    lines.append(f"- Baseline coverage: `{_fmt(metrics['coverage']['baseline'])}`")
    lines.append(f"- Conservative coverage: `{_fmt(metrics['coverage']['conservative'])}`")
    lines.append("")
    lines.append("## Stratification")
    for group_name, group in metrics["distance_groups"].items():
        lines.append(
            f"- {group_name}: n={group['count']}, MdAPE={_fmt(group['mdape_pct'])}, MAE={_fmt(group['mae_minutes'])}, Bias={_fmt(group['bias_minutes'])}"
        )
    for group_name, group in metrics["route_data_groups"].items():
        lines.append(
            f"- {group_name}: n={group['count']}, MdAPE={_fmt(group['mdape_pct'])}, MAE={_fmt(group['mae_minutes'])}, Bias={_fmt(group['bias_minutes'])}"
        )
    lines.append("")
    lines.append("## Ablation Summary")
    for name, block in ablations.items():
        lines.append(
            f"- {name}: MdAPE={_fmt(block['mdape_pct'])}, MAE={_fmt(block['mae_minutes'])}, Bias={_fmt(block['bias_minutes'])}"
        )
    lines.append("")
    lines.append("## Baseline Comparison")
    lines.append(f"- Full model MdAPE: `{_fmt(comparison.get('full_mdape_pct'))}`")
    lines.append(f"- Distance-only MdAPE: `{_fmt(comparison.get('distance_only_mdape_pct'))}`")
    lines.append(f"- Full model not worse than distance-only: `{_bool(comparison.get('full_not_worse_than_distance_only'))}`")
    lines.append("")
    lines.append("## Predictions")
    lines.append("| Date | Race | Prior races | Prediction | Actual | Abs err min | APE | Status |")
    lines.append("| --- | --- | ---: | --- | --- | ---: | ---: | --- |")
    for row in predictions:
        lines.append(
            f"| {_fmt(row['target_date'])} | {row['race_name']} | {row['prior_valid_history_count']} | {row['prediction_hhmmss']} | {row['actual_hhmmss']} | "
            f"{_fmt(row['abs_error_minutes'])} | {_fmt(row['ape_pct'])} | {', '.join(row['anomaly_tags']) or 'normal'} |"
        )
    lines.append("")
    lines.append("## Decision")
    lines.append("- The runner history is too small for a calibrated candidate claim.")
    lines.append("- Phase 8A therefore remains partial and descriptive only.")
    lines.append("- The next gating step requires a compliant 30-50 sample evaluation set.")
    lines.append("")
    return "\n".join(lines)
