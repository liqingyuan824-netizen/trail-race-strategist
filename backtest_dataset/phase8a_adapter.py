"""Adapt Phase 8A evidence reports into the Phase 8A.1 dataset schema."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pipeline import write_dataset_outputs
from .validation import parse_finish_time_seconds


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            return datetime.fromisoformat(f"{text}T00:00:00+00:00").date().isoformat()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return None


def _stable_runner_id(report: Mapping[str, Any], source_path: Path) -> str:
    dataset = report.get("dataset_manifest", {}).get("dataset", {})
    runner_id = dataset.get("runner_id")
    if runner_id not in (None, ""):
        return f"runner_{runner_id}"
    runner_name = dataset.get("runner_name")
    if runner_name not in (None, ""):
        return f"runner_{_sha256_text(str(runner_name))[:12]}"
    return f"runner_{_sha256_text(str(source_path.resolve()))[:12]}"


def _coerce_confidence(sample: Mapping[str, Any]) -> float:
    return 0.95 if sample.get("has_finish_time") else 0.6


def convert_phase8a_samples(report_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = report.get("dataset_manifest", {})
    samples = manifest.get("samples", [])
    if not isinstance(samples, Sequence):
        raise ValueError("dataset_manifest.samples must be a sequence")

    runner_id = _stable_runner_id(report, report_path)
    access_date = _parse_date(report.get("generated_at")) or datetime.now(timezone.utc).date().isoformat()
    source_url = str(report_path.resolve())
    source_policy_basis = None
    sources = manifest.get("sources")
    if isinstance(sources, list) and sources:
        first_source = sources[0]
        if isinstance(first_source, Mapping):
            source_policy_basis = first_source.get("use_basis")

    records: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            continue
        raw_race_time = sample.get("race_time")
        finish_time_seconds = parse_finish_time_seconds({"finish_time_seconds": raw_race_time})
        has_finish_time = bool(sample.get("has_finish_time")) and finish_time_seconds is not None
        record = {
            "record_id": f"phase8a_{index}",
            "pseudonymous_runner_id": runner_id,
            "event_id": sample.get("history_id"),
            "event_name": sample.get("race_name"),
            "race_date": _parse_date(sample.get("date")),
            "race_group": sample.get("race_group"),
            "distance_km": sample.get("distance_km"),
            "elevation_gain_m": sample.get("elevation_gain_m"),
            "finish_time_seconds": finish_time_seconds,
            "result_status": "finish" if has_finish_time else "time_unavailable",
            "source_kind": "local_evidence",
            "source_url": source_url,
            "source_file": source_url,
            "access_date": access_date,
            "usage_basis": sample.get("source_policy_basis") or source_policy_basis or "user_supplied_local_evidence",
            "license_status": "allowed",
            "route_version": sample.get("route_data_level"),
            "data_confidence": _coerce_confidence(sample),
            "raw_race_time": raw_race_time,
            "route_data_level": sample.get("route_data_level"),
            "source_policy_basis": sample.get("source_policy_basis"),
            "include_in_rolling_backtest": sample.get("include_in_rolling_backtest"),
            "has_finish_time": sample.get("has_finish_time"),
            "synthetic": False,
            "adapter_source_report": source_url,
        }
        records.append(record)

    summary = {
        "schema_name": "phase8a_adapter_summary",
        "generated_at": _utc_now(),
        "source_report": source_url,
        "converted_records": len(records),
        "timed_samples": sum(1 for record in records if record["finish_time_seconds"] is not None),
        "untimed_samples": sum(1 for record in records if record["finish_time_seconds"] is None),
    }
    return records, summary


def adapt_phase8a_evidence(*, report_path: Path, output_dir: Path) -> dict[str, Any]:
    records, summary = convert_phase8a_samples(report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "phase8a_adapter_source.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "phase8a_adapter_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    outputs = write_dataset_outputs(records=records, output_dir=output_dir, source_files=[report_path])
    (output_dir / "合规与缺失资料清单.md").write_text(
        outputs["eligibility_report"]["missing_materials_markdown"],
        encoding="utf-8",
    )
    return {
        "records": records,
        "summary": summary,
        "manifest": outputs["manifest"],
        "eligibility_report": outputs["eligibility_report"],
        "outputs": outputs,
    }
