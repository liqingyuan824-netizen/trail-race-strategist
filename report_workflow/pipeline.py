"""Terminally-audited orchestration for a complete trail-race report.

Public search and visual transcription remain agent operations. This module
owns the deterministic request boundary after those captures are saved: it
rejects incomplete search/attachment states, builds downstream artifacts, and
refuses to call a preparation note a completed strategy report.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from course_model import build_course_model
from itra_public_runner.browser import run_acquire
from itra_public_runner.pipeline import replay_capture
from race_sources.request_workflow import create_workflow_request
from race_strategy import build_race_plan, write_race_plan
from race_strategy.validation import full_cp_evidence_errors, is_historical_reference_cp_set
from race_strategy.baseline_adapter import build_internal_distance_only_baseline
from runner_readiness import build_public_only_readiness


REQUIRED_REPORT_MARKERS = (
    "# 比赛策略与情景规划",
    "### 6.1 全段总览表",
    "### 6.2 逐段战术详解",
)
TERMINAL_ARTIFACTS = (
    "race/search_receipt.json",
    "race/race_source_bundle.json",
    "course/course_model.json",
    "readiness/current_readiness.json",
)

# These ASCII anchors make the terminal validation resilient to display
# encoding differences while still enforcing the complete runner-facing shape.
FORMAL_REPORT_MARKERS = ("# ", "### 6.1", "### 6.2", "### 6.3")


class ReportWorkflowError(ValueError):
    """Machine-readable workflow completion failure."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportWorkflowError(f"INVALID_JSON:{path}") from exc
    if not isinstance(value, dict):
        raise ReportWorkflowError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_new(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ReportWorkflowError(f"NO_OVERWRITE:{path}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _request(request_dir: Path) -> tuple[dict[str, Any], str]:
    manifest = _load(request_dir / "request_manifest.json")
    request_id = str(manifest.get("request_id") or "")
    if not request_id or request_dir.name != request_id:
        raise ReportWorkflowError("REQUEST_DIRECTORY_BINDING_MISMATCH")
    return manifest, request_id


def _binding(request_id: str) -> dict[str, Any]:
    return {"request_id": request_id, "source_mode": "fresh_live_capture"}


def start_report_request(*, name: str, runner_id: str, target_event: str, output_root: Path) -> dict[str, Any]:
    created = create_workflow_request(name=name, runner_id=runner_id, target_event=target_event, output_root=output_root)
    request_dir = Path(created["request_dir"])
    for relative in ("runner/evidence", "race/evidence", "course", "readiness", "baseline", "reports"):
        (request_dir / relative).mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema_name": "trail_race_report_workflow_receipt",
        "schema_version": "1.0.0",
        "request_id": created["request_id"],
        "created_at": _now(),
        "workflow_status": "in_progress",
        "terminal_report_allowed": False,
        "required_stages": ["runner_capture", "race_search_and_attachment_parse", "course_model", "readiness", "baseline_or_explicit_unavailable", "race_strategy"],
        "required_terminal_artifacts": list(TERMINAL_ARTIFACTS),
        "next_actions": list(created["manifest"]["next_agent_actions"]),
        "completion_errors": ["DOWNSTREAM_STAGES_NOT_EXECUTED"],
    }
    _write_new(request_dir / "workflow_receipt.json", receipt)
    return {
        "request_id": created["request_id"],
        "request_dir": str(request_dir),
        "workflow_status": "in_progress",
        "terminal_report_allowed": False,
        "agent_must_continue": True,
        "next_command_after_evidence": f"report finalize --request-dir {request_dir}",
    }


def _strategy_reports(request_dir: Path) -> list[Path]:
    return sorted(request_dir.glob("reports/strategy-*/race_plan.md"))


def _runner_facing_reports(request_dir: Path) -> list[Path]:
    """Return optional secondary runner-facing files for the same contract audit."""
    return sorted(request_dir.glob("reports/strategy-*/race_plan_runner_facing.md"))


def _report_text_errors(text: str, *, artifact: str) -> list[str]:
    """Reject a visually plausible summary that is not the formal report."""
    errors: list[str] = []
    for marker in FORMAL_REPORT_MARKERS:
        if marker not in text:
            errors.append(f"FINAL_REPORT_MARKER_MISSING:{artifact}:{marker}")
    if text.count("\n## ") < 8:
        errors.append(f"FINAL_REPORT_SECTION_SKELETON_INCOMPLETE:{artifact}")
    overview = next((line for line in text.splitlines() if line.startswith("| # |")), None)
    if overview is None or overview.count("|") < 15:
        errors.append(f"FINAL_CP_OVERVIEW_SCHEMA_INVALID:{artifact}")
    if "### 6.2" in text and "#### S" not in text:
        errors.append(f"FINAL_SEGMENT_TACTICS_EMPTY:{artifact}")
    if "???" in text:
        errors.append(f"FINAL_REPORT_ENCODING_CORRUPTED:{artifact}")
    if "\ufffd" in text:
        errors.append(f"FINAL_REPORT_ENCODING_REPLACEMENT_CHARACTER:{artifact}")
    return errors


def _historical_reference_consent(request_dir: Path, request_id: str) -> bool:
    path = request_dir / "historical_reference_consent.json"
    if not path.is_file():
        return False
    payload = _load(path)
    return (
        payload.get("request_id") == request_id
        and payload.get("decision") == "user_confirmed_historical_reference"
    )


def _completion_errors(request_dir: Path) -> list[str]:
    errors: list[str] = []
    _, request_id = _request(request_dir)
    historical_reference_consent = _historical_reference_consent(request_dir, request_id)
    for relative in TERMINAL_ARTIFACTS:
        if not (request_dir / relative).is_file():
            errors.append(f"MISSING_ARTIFACT:{relative}")
    receipt_path = request_dir / "race/search_receipt.json"
    if receipt_path.is_file():
        receipt = _load(receipt_path)
        if receipt.get("capture_attempt_status") != "completed":
            errors.append("RACE_SEARCH_OR_ATTACHMENT_PIPELINE_INCOMPLETE")
        if int(receipt.get("pending_attachment_count", 0) or 0):
            errors.append("PENDING_ROUTE_ATTACHMENT")
        if receipt.get("missing_coverage"):
            errors.append("REQUIRED_SEARCH_LANES_MISSING")
        attachment_rows = receipt.get("attachments", [])
        if any(isinstance(row, Mapping) and row.get("status") in {"attachment_discovered", "attachment_not_acquired", "attachment_parse_failed"} for row in attachment_rows):
            errors.append("ROUTE_ATTACHMENT_UNACQUIRED_OR_UNPARSED")
    course_path = request_dir / "course/course_model.json"
    if course_path.is_file():
        course = _load(course_path)
        event = course.get("event", {})
        cp_points = event.get("course", {}).get("cp_model", {}).get("cp_points", []) if isinstance(event, Mapping) else []
        cp_errors = full_cp_evidence_errors(
            cp_points, year=event.get("year") if isinstance(event, Mapping) else None,
            group_code=event.get("group_code") if isinstance(event, Mapping) else None,
            group_name=event.get("group_name") if isinstance(event, Mapping) else None,
            visual_candidates=(event.get("visual_evidence_attempts") or event.get("visual_evidence")) if isinstance(event, Mapping) else None,
            allow_historical_reference=historical_reference_consent,
        )
        errors.extend(f"FULL_CP_EVIDENCE_REQUIRED:{error}" for error in cp_errors)
    reports = _strategy_reports(request_dir)
    if not reports:
        errors.append("FINAL_RACE_PLAN_MISSING")
    else:
        report = reports[-1]
        text = report.read_text(encoding="utf-8")
        errors.extend(_report_text_errors(text, artifact=report.name))
        if "CP 表不可生成" in text or "结构化赛段不可生成" in text:
            errors.append("FINAL_CP_TABLE_EMPTY")
    for report in _runner_facing_reports(request_dir):
        errors.extend(_report_text_errors(report.read_text(encoding="utf-8"), artifact=report.name))
    return errors


def inspect_report_request(request_dir: Path) -> dict[str, Any]:
    _, request_id = _request(request_dir)
    errors = _completion_errors(request_dir)
    return {
        "schema_name": "trail_race_report_workflow_status",
        "schema_version": "1.0.0",
        "request_id": request_id,
        "checked_at": _now(),
        "workflow_status": "completed" if not errors else "in_progress",
        "terminal_report_allowed": not errors,
        "completion_errors": errors,
        "strategy_reports": [str(path) for path in _strategy_reports(request_dir)],
        "runner_facing_reports": [str(path) for path in _runner_facing_reports(request_dir)],
    }


def capture_runner_for_request(request_dir: Path) -> dict[str, Any]:
    """Run a fresh public ITRA capture without creating a second request ID."""

    manifest, request_id = _request(request_dir)
    profile_path = request_dir / "runner/runner_profile.json"
    if profile_path.exists():
        raise ReportWorkflowError(f"NO_OVERWRITE:{profile_path}")
    evidence_dir = request_dir / "runner/evidence" / f"live-{_stamp()}"
    try:
        trace = run_acquire(str(manifest["provided_name"]), str(manifest["provided_runner_id"]), evidence_dir)
    except Exception as exc:
        trace = {"status": "capture_failed", "error_code": type(exc).__name__.upper(), "error": str(exc), "retrieved_at": _now()}
    receipt = {
        "schema_name": "report_runner_capture_receipt", "schema_version": "1.0.0",
        "request_id": request_id, "retrieved_at": trace.get("retrieved_at", _now()),
        "capture_status": trace.get("status"), "error_code": trace.get("error_code") or trace.get("blocker"),
        "evidence_dir": str(evidence_dir), "next_action": None,
    }
    if trace.get("status") != "profile_captured":
        receipt["next_action"] = "continue_race_search_and_retry_normal_public_itra_later"
        _write_new(request_dir / f"runner/capture_receipt-{_stamp()}.json", receipt)
        return {**receipt, "workflow_status": "in_progress", "terminal_report_allowed": False}
    html_path = evidence_dir / "profile.html"
    profile = replay_capture(html_path, name=str(manifest["provided_name"]), runner_id=str(manifest["provided_runner_id"]))
    identity = profile.get("identity", {})
    if str(identity.get("runner_id") or "") != str(manifest["provided_runner_id"]):
        raise ReportWorkflowError("RUNNER_ID_CHAIN_MISMATCH")
    profile["request_binding"] = {
        "request_id": request_id, "source_mode": "fresh_live_capture",
        "profile_html_sha256": sha256(html_path.read_bytes()).hexdigest(), "profile_html": str(html_path),
    }
    _write_new(profile_path, profile)
    receipt.update(capture_status="profile_captured", profile_path=str(profile_path), profile_html_sha256=profile["request_binding"]["profile_html_sha256"])
    _write_new(request_dir / f"runner/capture_receipt-{_stamp()}.json", receipt)
    return {**receipt, "workflow_status": "in_progress", "terminal_report_allowed": False}


def _field(value: Any) -> Any:
    return value.get("value") if isinstance(value, Mapping) else value


def _course_only_plan(
    course: Mapping[str, Any], readiness: Mapping[str, Any], *, reason: str,
    historical_reference_consent: bool = False,
) -> dict[str, Any]:
    event = course["event"]
    course_data = event["course"]
    cp_rows = list(course_data.get("cp_model", {}).get("cp_points", []))
    checkpoints: list[dict[str, Any]] = []
    historical = any(row.get("evidence_tier") == "official_historical_reference" for row in cp_rows)
    for index, row in enumerate(cp_rows):
        item = dict(row)
        item["previous_cp"] = cp_rows[index - 1].get("name") if index else None
        item.setdefault("source_layer", item.get("evidence_tier") or ("official_historical_reference" if historical else "current_year_official"))
        item.setdefault("planned_stop_minutes", 0 if index in {0, len(cp_rows) - 1} else None)
        item.setdefault("movement_actions", {
            "run_walk": "按分段爬升与当日状态保守切换跑走",
            "technical_descent": "技术下坡小步高频，不为追回时间冒险",
            "night": "夜间缩短步幅并优先保证照明与保暖",
        })
        item.setdefault("equipment_notes", [])
        item.setdefault("risk_notes", [])
        checkpoints.append(item)
    mode = "historical_route_reference" if historical else "course_only_not_allowed"
    return {
        "schema_name": "race_plan", "schema_version": "1.0.0", "generated_at": _now(),
        "plan_status": "course_strategy_without_personal_time_windows",
        "request_binding": dict(readiness["request_binding"]),
        "facts": {
            "event": {
                "official_name": event.get("official_name"), "year": event.get("year"),
                "group_name": event.get("group_name"), "group_code": event.get("group_code"),
                "distance_km": _field(course_data.get("total_distance_km")),
                "elevation_gain_m": _field(course_data.get("total_elevation_gain_m")),
                "start_time": _field(course_data.get("start_time")), "cutoff_time": _field(course_data.get("cutoff_time")),
            },
            "readiness_safety_cap": readiness["assessment"], "unknown_inputs": {},
        },
        "recommended_strategy": "safe_finish",
        "strategies": {"safe_finish": {"available": True, "checkpoints": checkpoints}},
        "conditional_time_plan": {
            "display_allowed": False, "mode": mode, "blocked_reason": reason,
            "target_group_capture": event.get("target_group_capture", {}),
        },
        "historical_reference": {
            "user_confirmed": bool(historical and historical_reference_consent),
            "reference_only": historical,
            "current_year_cp_confirmed": False,
            "required_pre_race_action": "赛前按当年官方公告复核 CP、补给、关门与路线版本" if historical else None,
        },
        "governance": {"model_validated": False, "user_facing_prediction_allowed": False, "retained_reference_model": "distance_only"},
        "diagnostics": {"personal_time_windows_not_generated": True, "reason": reason},
    }


def _target(course: Mapping[str, Any]) -> tuple[str, float, float]:
    event = course["event"]
    values = event["course"]
    start = _field(values.get("start_time")) or f"{event.get('year')}-01-01T00:00:00+00:00"
    distance = _field(values.get("total_distance_km"))
    gain = _field(values.get("total_elevation_gain_m"))
    if distance is None or gain is None:
        raise ReportWorkflowError("TARGET_DISTANCE_OR_GAIN_MISSING")
    return str(start), float(distance), float(gain)


def finalize_report_request(request_dir: Path, *, historical_reference_consent: bool = False) -> dict[str, Any]:
    _, request_id = _request(request_dir)
    bundle_path = request_dir / "race/race_source_bundle.json"
    receipt_path = request_dir / "race/search_receipt.json"
    if not bundle_path.is_file() or not receipt_path.is_file():
        raise ReportWorkflowError("RACE_BUNDLE_AND_SEARCH_RECEIPT_REQUIRED")
    receipt = _load(receipt_path)
    if receipt.get("request_id") != request_id:
        raise ReportWorkflowError("REQUEST_ID_MISMATCH_RACE_RECEIPT")
    if receipt.get("capture_attempt_status") != "completed" or receipt.get("missing_coverage") or int(receipt.get("pending_attachment_count", 0) or 0):
        raise ReportWorkflowError("RACE_SEARCH_OR_ATTACHMENT_PIPELINE_INCOMPLETE")
    bundle = _load(bundle_path)
    if bundle.get("request_binding", {}).get("request_id") != request_id:
        raise ReportWorkflowError("REQUEST_ID_MISMATCH_RACE_BUNDLE")

    course = build_course_model(bundle)
    cp_rows = course.get("event", {}).get("course", {}).get("cp_model", {}).get("cp_points", [])
    event = course.get("event", {})
    historical_reference_only = is_historical_reference_cp_set(cp_rows)
    cp_errors = full_cp_evidence_errors(
        cp_rows, year=event.get("year"), group_code=event.get("group_code"), group_name=event.get("group_name"),
        visual_candidates=event.get("visual_evidence_attempts") or event.get("visual_evidence"),
        allow_historical_reference=historical_reference_consent,
    )
    if cp_errors:
        if historical_reference_only:
            raise ReportWorkflowError("HISTORICAL_REFERENCE_CONSENT_REQUIRED")
        raise ReportWorkflowError("FULL_CP_EVIDENCE_REQUIRED:" + "|".join(cp_errors))
    if historical_reference_consent:
        _write_new(request_dir / "historical_reference_consent.json", {
            "schema_name": "historical_reference_consent",
            "schema_version": "1.0.0",
            "request_id": request_id,
            "recorded_at": _now(),
            "decision": "user_confirmed_historical_reference",
            "scope": "previous_year_same_event_same_group_official_route_reference",
            "current_year_cp_status": "not_confirmed",
            "required_pre_race_action": "赛前按当年官方公告复核 CP、补给、关门与路线版本",
        })
    course_path = request_dir / "course/course_model.json"
    _write_new(course_path, course)

    binding = _binding(request_id)
    readiness = build_public_only_readiness(request_binding=binding)
    readiness_path = request_dir / "readiness/current_readiness.json"
    _write_new(readiness_path, readiness)

    runner_path = request_dir / "runner/runner_profile.json"
    plan: dict[str, Any]
    baseline_path: Path | None = None
    if runner_path.is_file():
        runner = _load(runner_path)
        if runner.get("request_binding", {}).get("request_id") != request_id:
            raise ReportWorkflowError("REQUEST_ID_MISMATCH_RUNNER_PROFILE")
        try:
            target_date, distance, gain = _target(course)
            baseline = build_internal_distance_only_baseline(
                runner_profile=runner, target_date=target_date, target_distance_km=distance,
                target_elevation_gain_m=gain, source_reference=f"request:{request_id}:fresh_itra_public_profile",
            )
            baseline["request_binding"] = binding
            baseline_path = request_dir / "baseline/internal_distance_only_baseline.json"
            _write_new(baseline_path, baseline)
            plan = build_race_plan(
                course_model=course, current_readiness=readiness, distance_only_baseline=baseline,
                case_reference=request_id, historical_reference_consent=historical_reference_consent,
            )
        except ValueError as exc:
            plan = _course_only_plan(
                course, readiness, reason=f"RUNNER_BASELINE_UNAVAILABLE:{exc}",
                historical_reference_consent=historical_reference_consent,
            )
    else:
        plan = _course_only_plan(
            course, readiness, reason="FRESH_ITRA_CAPTURE_BLOCKED_OR_UNAVAILABLE",
            historical_reference_consent=historical_reference_consent,
        )

    report_dir = request_dir / "reports" / f"strategy-{_stamp()}"
    write_race_plan(plan, report_dir)
    report_path = report_dir / "race_plan.md"
    errors = _completion_errors(request_dir)
    if errors:
        raise ReportWorkflowError("FINAL_COMPLETION_GATE_FAILED:" + "|".join(errors))
    status = {
        "schema_name": "trail_race_report_workflow_receipt", "schema_version": "1.0.0",
        "request_id": request_id, "completed_at": _now(), "workflow_status": "completed",
        "terminal_report_allowed": True, "completion_errors": [],
        "artifacts": {
            "search_receipt": str(receipt_path), "race_source_bundle": str(bundle_path),
            "course_model": str(course_path), "readiness": str(readiness_path),
            "baseline": str(baseline_path) if baseline_path else None,
            "race_plan_json": str(report_dir / "race_plan.json"), "race_plan_markdown": str(report_path),
            "race_plan_sha256": sha256(report_path.read_bytes()).hexdigest(),
            "historical_reference_consent": historical_reference_consent,
        },
    }
    _write_new(request_dir / f"workflow_completion-{_stamp()}.json", status)
    return status
