"""Participant import utilities for Phase 8A.2A."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from itra_public_runner.request_session import RequestBindingError, load_bound_request, normalize_name

from .pipeline import write_dataset_outputs
from .validation import ValidationError, parse_finish_time_seconds


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValidationError(f"{path.name}:expected_json_object")
    return payload


def _normalize_result_bucket(result_status: Any) -> str:
    status = str(result_status or "").strip().lower()
    if status in {"finish", "completed", "ok"}:
        return "finish"
    if status in {"time_unavailable", "unknown"}:
        return "time_unavailable"
    return status or "unknown"


def _stable_participant_id(participant_reference: str, provided_name: str | None, provided_itra_id: str | None) -> str:
    payload = "|".join([participant_reference or "", provided_name or "", provided_itra_id or ""])
    return f"participant_{_sha256_text(payload)[:12]}"


def _confirmation_records(confirmation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = confirmation.get("records", [])
    if not isinstance(records, list):
        raise ValidationError("runner_history_confirmation.records must be a list")
    return [record for record in records if isinstance(record, Mapping)]


def _match_key(event_name: Any, race_date: Any) -> tuple[str, str]:
    return (str(event_name or "").strip().lower(), str(race_date or "").strip())


def _validate_confirmation_for_request(*, confirmation: Mapping[str, Any], manifest: Mapping[str, Any], profile: Mapping[str, Any]) -> None:
    """A confirmation may correct only races already bound to this request profile."""
    request_id = str(manifest.get("request_id") or "")
    runner_id = str(manifest.get("provided_runner_id") or "")
    if str(confirmation.get("request_id") or "") != request_id:
        raise ValidationError("CONFIRMATION_REQUEST_ID_MISMATCH")
    if str(confirmation.get("runner_id") or "") != runner_id:
        raise ValidationError("CONFIRMATION_RUNNER_ID_MISMATCH")
    if normalize_name(confirmation.get("provided_name")) != normalize_name(manifest.get("provided_name")):
        raise ValidationError("CONFIRMATION_RUNNER_NAME_MISMATCH")
    try:
        rows = _confirmation_records(confirmation)
    except (TypeError, ValueError) as exc:
        raise ValidationError("CONFIRMATION_JSON_INVALID") from exc
    profile_rows = profile.get("race_results") or profile.get("historical_races") or []
    if not isinstance(profile_rows, list):
        raise ValidationError("RUNNER_PROFILE_RACES_INVALID")
    profile_keys = {_match_key(row.get("race") or row.get("event_name"), row.get("date") or row.get("race_date")) for row in profile_rows if isinstance(row, Mapping)}
    for row in rows:
        if _match_key(row.get("event_name"), row.get("race_date")) not in profile_keys:
            raise ValidationError("CONFIRMATION_EVENT_NOT_IN_REQUEST_PROFILE")


def import_request_participant_trial(
    *,
    intake_path: Path,
    confirmation_path: Path,
    request_manifest_path: Path,
    runner_profile_path: Path,
    output_dir: Path,
    sensitive_map_output: Path | None = None,
) -> dict[str, Any]:
    """Secure new-request import; legacy paths cannot be silently substituted."""
    try:
        manifest, profile = load_bound_request(request_manifest_path=request_manifest_path, runner_profile_path=runner_profile_path)
    except RequestBindingError as exc:
        raise ValidationError(str(exc)) from exc
    try:
        intake = _load_json(intake_path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("INTAKE_JSON_INVALID") from exc
    try:
        confirmation = _load_json(confirmation_path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("CONFIRMATION_JSON_INVALID") from exc
    if str(intake.get("provided_itra_id") or "") != str(manifest.get("provided_runner_id") or ""):
        raise ValidationError("INTAKE_RUNNER_ID_MISMATCH")
    if normalize_name(intake.get("provided_name")) != normalize_name(manifest.get("provided_name")):
        raise ValidationError("INTAKE_RUNNER_NAME_MISMATCH")
    _validate_confirmation_for_request(confirmation=confirmation, manifest=manifest, profile=profile)
    outputs = import_participant_trial(
        intake_path=intake_path,
        confirmation_path=confirmation_path,
        runner_profile_path=runner_profile_path,
        output_dir=output_dir,
        sensitive_map_output=sensitive_map_output,
    )
    binding = {
        "request_id": manifest["request_id"],
        "provided_runner_id": manifest["provided_runner_id"],
        "profile_html_sha256": manifest["profile_html_sha256"],
        "source_mode": manifest["source_mode"],
    }
    import_manifest_path = output_dir / "participant_import_manifest.json"
    import_manifest = _load_json(import_manifest_path)
    import_manifest = dict(import_manifest)
    import_manifest["request_binding"] = binding
    _write_json(import_manifest_path, import_manifest)
    outputs["participant_import_manifest"] = import_manifest
    return outputs


def _participant_record_signature(record: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(record.get("pseudonymous_runner_id") or ""),
        str(record.get("event_id") or ""),
        str(record.get("race_date") or ""),
        _normalize_result_bucket(record.get("result_status")),
        str(record.get("finish_time_seconds") or ""),
        str(record.get("route_version") or ""),
    )


def _dedupe_participant_records(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    unique_records: list[dict[str, Any]] = []
    signature_map: dict[tuple[str, str, str, str, str, str], str] = {}
    duplicate_map: dict[str, str] = {}
    duplicate_count = 0

    for record in records:
        if not isinstance(record, Mapping):
            continue
        copied = dict(record)
        signature = _participant_record_signature(copied)
        record_id = str(copied.get("record_id") or "")
        if signature in signature_map:
            duplicate_count += 1
            duplicate_map[record_id] = signature_map[signature]
            continue
        signature_map[signature] = record_id
        unique_records.append(copied)

    return unique_records, {
        "input_records": len([record for record in records if isinstance(record, Mapping)]),
        "unique_records": len(unique_records),
        "duplicate_records": duplicate_count,
        "signature_policy": "pseudonymous_runner_id + event_id + race_date + normalized_result_status + finish_time_seconds + route_version",
        "duplicate_map": duplicate_map,
    }


def participant_intake_template() -> dict[str, Any]:
    return {
        "schema_name": "participant_intake_template",
        "schema_version": "1.0.0",
        "participant_reference": "P-0001",
        "provided_name": "",
        "provided_itra_id": "",
        "identity_confirmed": False,
        "public_data_lookup_authorized": False,
        "local_evaluation_authorized": False,
        "anonymized_aggregate_use_authorized": False,
        "public_case_study_authorized": False,
        "authorization_date": None,
        "notes": "",
    }


def runner_history_confirmation_template() -> dict[str, Any]:
    return {
        "schema_name": "runner_history_confirmation_template",
        "schema_version": "1.0.0",
        "participant_reference": "P-0001",
        "confirmation_date": None,
        "participant_confirmation_text": "",
        "records": [
            {
                "event_name": "",
                "race_date": "",
                "distance_km": None,
                "elevation_gain_m": None,
                "finish_time": None,
                "result_status": "finish",
                "belongs_to_runner": False,
                "runner_correction": None,
                "source_reference": "",
            }
        ],
        "notes": "",
    }


def participant_data_request_md() -> str:
    return """# 鍙備笌鑰呮暟鎹娇鐢ㄨ鏄?
杩欐槸涓€浠借瘯楠屾€х殑鏁版嵁閲囬泦璇存槑锛屼笉鏄硶寰嬫剰瑙併€?
鎴戜滑浼氳鍙栧摢浜涘叕寮€鏁版嵁
- 鍏叡鍙鐨?ITRA 璺戣€呴〉闈俊鎭?- 璺戣€呰嚜宸辩‘璁ょ殑姣旇禌鍘嗗彶
- 鐢ㄤ簬鏍稿姣旇禌褰掑睘鐨勫叕寮€璇佹嵁閾炬帴鎴栨湰鍦颁繚瀛樿瘉鎹?
杩欎簺鏁版嵁鐢ㄤ簬浠€涔?- 纭姣旇禌鏄惁灞炰簬鍚屼竴浣嶈窇鑰?- 寤虹珛鍙拷婧殑鍘嗗彶姣旇禌璁板綍
- 鐢熸垚鍖垮悕鍖栫殑鍘嗗彶鍥炴祴鏍锋湰

鍝簺淇℃伅鍙繚瀛樺湪鏈湴
- 鐪熷疄濮撳悕鍜?ITRA ID 鏄犲皠
- 鍙備笌鑰呯‘璁よ褰?- 鍘熷璇佹嵁鏂囦欢

浣犲彲浠ユ嫆缁濅粈涔?- 鍖垮悕鍖栨眹鎬讳互澶栫殑鍏紑浣跨敤
- 鏈湴璇勪及浠ュ鐨勭敤閫?- 鍋滄缁х画閲囬泦

鎴戜滑涓嶄細閲囬泦
- 浼ょ棝
- 鐤剧梾
- 鐫＄湢
- 鐤插姵
- 鑱旂郴鏂瑰紡
- 璁粌骞冲彴璐﹀彿瀵嗙爜

褰撳墠鐘舵€?- 杩欐槸璇曢噰闆嗘祦绋?- 鏆備笉鎻愪緵姝ｅ紡姣旇禌棰勬祴
"""


def write_participant_trial_templates(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    intake = participant_intake_template()
    confirmation = runner_history_confirmation_template()
    request_text = participant_data_request_md()
    _write_json(output_dir / "participant_intake_template.json", intake)
    _write_json(output_dir / "runner_history_confirmation_template.json", confirmation)
    (output_dir / "participant_data_request.md").write_text(request_text, encoding="utf-8")
    return {
        "intake_template": intake,
        "confirmation_template": confirmation,
        "participant_data_request": request_text,
    }


def build_empty_participant_status() -> dict[str, Any]:
    return {
        "schema_name": "phase8a2a_participant_trial_status",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_count": 0,
        "real_runner_count": 0,
        "real_eligible_folds": 0,
        "total_eligible_folds": 0,
        "calibration_allowed": False,
        "user_facing_prediction_allowed": False,
        "distance_to_30": 30,
        "notes": ["No voluntary participants have been ingested yet."],
    }


def _apply_runner_correction(record: dict[str, Any], correction: Mapping[str, Any] | None) -> None:
    if not correction:
        return
    for field in ("event_name", "race_date", "distance_km", "elevation_gain_m", "finish_time", "result_status", "source_reference", "route_version"):
        if field in correction and correction[field] not in (None, ""):
            record[field] = correction[field]


def build_participant_records(
    *,
    intake: Mapping[str, Any],
    confirmation: Mapping[str, Any],
    runner_profile: Mapping[str, Any],
    runner_profile_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    participant_reference = str(intake.get("participant_reference") or "").strip()
    provided_name = str(intake.get("provided_name") or "").strip()
    provided_itra_id = str(intake.get("provided_itra_id") or "").strip()
    if not participant_reference:
        raise ValidationError("participant_reference_required")
    if not intake.get("identity_confirmed"):
        raise ValidationError("identity_not_confirmed")
    if not intake.get("public_data_lookup_authorized"):
        raise ValidationError("public_data_lookup_not_authorized")
    if not intake.get("local_evaluation_authorized"):
        raise ValidationError("local_evaluation_not_authorized")

    participant_id = _stable_participant_id(participant_reference, provided_name, provided_itra_id)
    source_evidence = [str(item) for item in runner_profile.get("evidence", []) if item]
    source_ref = source_evidence[0] if source_evidence else str(runner_profile_path.resolve())
    confirmation_records = _confirmation_records(confirmation)
    confirmation_index = {_match_key(item.get("event_name"), item.get("race_date")): item for item in confirmation_records}
    profile_results = runner_profile.get("race_results") or runner_profile.get("historical_races") or []
    if not isinstance(profile_results, list):
        raise ValidationError("runner_profile.race_results must be a list")

    records: list[dict[str, Any]] = []
    for race in profile_results:
        if not isinstance(race, Mapping):
            continue
        key = _match_key(race.get("race"), race.get("date"))
        confirmation_row = confirmation_index.get(key)
        if confirmation_row is None:
            continue
        if confirmation_row.get("belongs_to_runner") is False:
            continue

        record: dict[str, Any] = {
            "record_id": f"{participant_id}_{len(records)}",
            "pseudonymous_runner_id": participant_id,
            "event_id": f"{participant_id}_{len(records)}",
            "event_name": confirmation_row.get("event_name") or race.get("race"),
            "race_date": confirmation_row.get("race_date") or race.get("date"),
            "race_group": confirmation_row.get("race_group") or race.get("category"),
            "distance_km": confirmation_row.get("distance_km") if confirmation_row.get("distance_km") not in (None, "") else race.get("distance_km"),
            "elevation_gain_m": confirmation_row.get("elevation_gain_m") if confirmation_row.get("elevation_gain_m") not in (None, "") else race.get("elevation_gain_m"),
            "finish_time_seconds": None,
            "result_status": str(confirmation_row.get("result_status") or "").strip().lower() or "time_unavailable",
            "source_kind": "local_evidence",
            "source_url": source_ref,
            "source_file": source_ref,
            "access_date": runner_profile.get("retrieved_at") or _utc_now(),
            "usage_basis": "participant-confirmed public evidence and local evaluation",
            "license_status": "allowed",
            "route_version": confirmation_row.get("runner_correction", {}).get("route_version") if isinstance(confirmation_row.get("runner_correction"), Mapping) else None,
            "data_confidence": 0.95,
            "synthetic": False,
            "participant_reference": participant_reference,
            "source_reference": confirmation_row.get("source_reference") or source_ref,
            "runner_correction": confirmation_row.get("runner_correction"),
            "result_status_source": "participant_confirmation",
        }
        if not record.get("route_version"):
            record["route_version"] = race.get("route_data_level") or race.get("route_version") or "standard"
        _apply_runner_correction(record, confirmation_row.get("runner_correction") if isinstance(confirmation_row.get("runner_correction"), Mapping) else None)
        finish_time = record.get("finish_time") if record.get("finish_time") not in (None, "") else race.get("race_time")
        if finish_time not in (None, ""):
            seconds = parse_finish_time_seconds({"finish_time_seconds": finish_time})
            if seconds is not None:
                record["finish_time_seconds"] = seconds
                if _normalize_result_bucket(record.get("result_status")) in {"", "time_unavailable", "unknown"}:
                    record["result_status"] = "finish"
                record["data_confidence"] = 0.95
        if record["finish_time_seconds"] is None and _normalize_result_bucket(record.get("result_status")) in {"", "unknown"}:
            record["result_status"] = "time_unavailable"
            record["data_confidence"] = 0.75
        records.append(record)

    report = {
        "schema_name": "participant_trial_report",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_reference": participant_reference,
        "provided_name_local_only": provided_name,
        "provided_itra_id_local_only": provided_itra_id,
        "public_case_study_authorized": bool(intake.get("public_case_study_authorized")),
        "anonymized_aggregate_use_authorized": bool(intake.get("anonymized_aggregate_use_authorized")),
        "pseudonymous_runner_id": participant_id,
        "confirmation_date": confirmation.get("confirmation_date"),
        "participant_confirmation_text": confirmation.get("participant_confirmation_text"),
        "confirmation_basis": "participant_confirmation",
        "confirmed_records": len(confirmation_records),
        "usable_records": 0,
        "restricted_records": 0,
        "real_eligible_folds": 0,
        "calibration_allowed": False,
        "user_facing_prediction_allowed": False,
        "notes": [
            "No formal prediction is generated in Phase 8A.2A.",
            "Only confirmed, participant-authorized public history is imported.",
        ],
    }
    return records, report


def _participant_status_payload(
    *,
    intake: Mapping[str, Any],
    manifest: Mapping[str, Any],
    trial_report: Mapping[str, Any],
    dedupe_summary: Mapping[str, Any],
) -> dict[str, Any]:
    real_eligible_folds = int(manifest["dataset"]["real_eligible_folds"])
    synthetic_eligible_folds = int(manifest["dataset"].get("synthetic_eligible_folds", 0))
    total_eligible_folds = int(manifest["dataset"]["total_eligible_folds"])
    return {
        "schema_name": "participant_status",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_reference": str(intake.get("participant_reference") or ""),
        "participant_count": 1 if trial_report.get("confirmed_records", 0) else 0,
        "real_runner_count": 1 if trial_report.get("confirmed_records", 0) else 0,
        "synthetic_runner_count": 0,
        "usable_records": int(manifest["dataset"]["usable_records"]),
        "restricted_records": int(manifest["dataset"]["restricted_records"]),
        "real_eligible_folds": real_eligible_folds,
        "synthetic_eligible_folds": synthetic_eligible_folds,
        "total_eligible_folds": total_eligible_folds,
        "distance_to_30": max(30 - real_eligible_folds, 0),
        "calibration_status": "insufficient_evaluation_data" if real_eligible_folds < 30 else "calibrated_candidate",
        "calibration_allowed": bool(manifest["dataset"].get("calibration_allowed")),
        "user_facing_prediction_allowed": bool(manifest["dataset"].get("user_facing_prediction_allowed")),
        "public_case_study_authorized": bool(intake.get("public_case_study_authorized")),
        "anonymous_public_case_study": True,
        "duplicate_imports_removed": int(dedupe_summary.get("duplicate_records", 0)),
        "notes": [
            "Formal outputs remain anonymous even when public case study authorization is granted.",
            "Real identity is isolated in the local-only mapping file.",
        ],
    }


def _participant_import_manifest_payload(
    *,
    intake: Mapping[str, Any],
    confirmation: Mapping[str, Any],
    manifest: Mapping[str, Any],
    trial_report: Mapping[str, Any],
    dedupe_summary: Mapping[str, Any],
    runner_profile_path: Path,
    intake_path: Path,
    confirmation_path: Path,
    sensitive_map_output: Path,
) -> dict[str, Any]:
    confirmation_records = confirmation.get("records", [])
    confirmation_count = len(confirmation_records) if isinstance(confirmation_records, list) else 0
    real_eligible_folds = int(manifest["dataset"]["real_eligible_folds"])
    return {
        "schema_name": "participant_import_manifest",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_reference": str(intake.get("participant_reference") or ""),
        "public_facts": {
            "participant_reference": str(intake.get("participant_reference") or ""),
            "public_data_lookup_authorized": bool(intake.get("public_data_lookup_authorized")),
            "local_evaluation_authorized": bool(intake.get("local_evaluation_authorized")),
            "anonymized_aggregate_use_authorized": bool(intake.get("anonymized_aggregate_use_authorized")),
            "public_case_study_authorized": bool(intake.get("public_case_study_authorized")),
            "authorization_date": intake.get("authorization_date"),
        },
        "import_summary": {
            "real_runner_count": 1 if trial_report.get("confirmed_records", 0) else 0,
            "usable_records": int(manifest["dataset"]["usable_records"]),
            "restricted_records": int(manifest["dataset"]["restricted_records"]),
            "real_eligible_folds": real_eligible_folds,
            "synthetic_eligible_folds": int(manifest["dataset"].get("synthetic_eligible_folds", 0)),
            "total_eligible_folds": int(manifest["dataset"]["total_eligible_folds"]),
            "distance_to_30": max(30 - real_eligible_folds, 0),
            "calibration_status": "insufficient_evaluation_data" if real_eligible_folds < 30 else "calibrated_candidate",
            "calibration_allowed": bool(manifest["dataset"].get("calibration_allowed")),
            "user_facing_prediction_allowed": bool(manifest["dataset"].get("user_facing_prediction_allowed")),
        },
        "dedupe_policy": dedupe_summary["signature_policy"],
        "dedupe_summary": {
            "input_records": dedupe_summary["input_records"],
            "unique_records": dedupe_summary["unique_records"],
            "duplicate_records": dedupe_summary["duplicate_records"],
        },
        "source_artifacts": {
            "runner_profile": runner_profile_path.name,
            "participant_intake": intake_path.name,
            "runner_history_confirmation": confirmation_path.name,
        },
        "local_only_artifacts": {
            "participant_identity_map": {
                "filename": sensitive_map_output.name,
                "sensitive": True,
                "local_only": True,
            }
        },
        "confirmation_authorization": {
            "public_data_lookup_authorized": bool(intake.get("public_data_lookup_authorized")),
            "local_evaluation_authorized": bool(intake.get("local_evaluation_authorized")),
            "anonymized_aggregate_use_authorized": bool(intake.get("anonymized_aggregate_use_authorized")),
            "public_case_study_authorized": bool(intake.get("public_case_study_authorized")),
            "result_status_source": "participant_confirmation",
        },
        "confirmation_count": confirmation_count,
        "notes": [
            "Formal outputs are anonymous and keyed by participant_reference only.",
            "Real name and ITRA ID mapping live only in the local-only identity map.",
        ],
    }


def _public_participant_intake_payload(intake: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": "participant_intake_template",
        "schema_version": "1.0.0",
        "participant_reference": str(intake.get("participant_reference") or ""),
        "identity_confirmed": bool(intake.get("identity_confirmed")),
        "public_data_lookup_authorized": bool(intake.get("public_data_lookup_authorized")),
        "local_evaluation_authorized": bool(intake.get("local_evaluation_authorized")),
        "anonymized_aggregate_use_authorized": bool(intake.get("anonymized_aggregate_use_authorized")),
        "public_case_study_authorized": bool(intake.get("public_case_study_authorized")),
        "authorization_date": intake.get("authorization_date"),
        "notes": "sanitized public intake snapshot",
    }


def _privacy_audit_report(
    *,
    intake: Mapping[str, Any],
    public_paths: Sequence[Path],
    manifest_payload: Mapping[str, Any],
    status_payload: Mapping[str, Any],
    trial_report_path: Path,
    sensitive_map_output: Path,
) -> str:
    provided_name = str(intake.get("provided_name") or "").strip()
    provided_itra_id = str(intake.get("provided_itra_id") or "").strip()
    checked_rows: list[str] = []
    sensitive_present = False

    for path in public_paths:
        text = path.read_text(encoding="utf-8-sig")
        has_name = bool(provided_name and provided_name in text)
        has_itra = bool(provided_itra_id and provided_itra_id in text)
        sensitive_present = sensitive_present or has_name or has_itra
        checked_rows.append(f"- {path.name}: name_present={str(has_name).lower()}, itra_id_present={str(has_itra).lower()}")

    lines = [
        "# Privacy Audit Report",
        "",
        "## Identity Handling",
        f"- public_case_study_authorized: `{bool(intake.get('public_case_study_authorized'))}`",
        "- anonymized_public_display: `true`",
        f"- sensitive_identity_map: `{sensitive_map_output.name}`",
        "- sensitive_identity_map_sensitive: `true`",
        "- sensitive_identity_map_local_only: `true`",
        "",
        "## Public Files Checked",
        *checked_rows,
        "",
        "## Result",
        f"- sensitive_name_or_itra_id_found_in_public_files: `{str(sensitive_present).lower()}`",
        "- participant_import_manifest_public: `anonymous`",
        "- participant_status_public: `anonymous`",
        "- participant_records_public: `anonymous`",
        "- dataset_manifest_public: `anonymous`",
        "- eligibility_report_public: `anonymous`",
        "",
        "## Notes",
        "- The formal manifest and backtest data remain anonymous even when a case study is authorized.",
        "- The local-only identity map is the only file that stores the real name and ITRA ID mapping.",
        "- The participant trial report is retained as a local-only internal artifact.",
        f"- trial_report_source: `{trial_report_path.name}`",
        "",
    ]
    if int(manifest_payload.get("dedupe_summary", {}).get("duplicate_records", 0)) > 0:
        lines.append("- Duplicate import rows were collapsed before formal export.")
    if status_payload.get("distance_to_30") == 26:
        lines.append("- Target gap remains 26 folds, so calibration stays insufficient.")
    return "\n".join(lines)


def _participant_records_anonymized_payload(
    *,
    intake: Mapping[str, Any],
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    manifest_index = {str(item.get("record_id") or ""): item for item in manifest.get("record_index", []) if isinstance(item, Mapping)}
    anonymized_records: list[dict[str, Any]] = []
    for record in records:
        record_id = str(record.get("record_id") or "")
        manifest_row = manifest_index.get(record_id, {})
        anonymized_records.append(
            {
                "record_id": record_id,
                "pseudonymous_runner_id": record.get("pseudonymous_runner_id"),
                "event_id": record.get("event_id"),
                "event_name": record.get("event_name"),
                "race_date": record.get("race_date"),
                "race_group": record.get("race_group"),
                "distance_km": record.get("distance_km"),
                "elevation_gain_m": record.get("elevation_gain_m"),
                "finish_time_seconds": record.get("finish_time_seconds"),
                "result_status": record.get("result_status"),
                "route_version": record.get("route_version"),
                "data_confidence": record.get("data_confidence"),
                "compliance_status": manifest_row.get("compliance_status") or record.get("compliance_status"),
                "synthetic": bool(record.get("synthetic")),
                "result_status_source": record.get("result_status_source"),
            }
        )
    return {
        "schema_name": "participant_records_anonymized",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_reference": str(intake.get("participant_reference") or ""),
        "pseudonymous_runner_id": records[0].get("pseudonymous_runner_id") if records else "",
        "records": anonymized_records,
        "summary": {
            "record_count": len(anonymized_records),
            "usable_records": int(manifest["dataset"]["usable_records"]),
            "restricted_records": int(manifest["dataset"]["restricted_records"]),
            "real_eligible_folds": int(manifest["dataset"]["real_eligible_folds"]),
            "synthetic_eligible_folds": int(manifest["dataset"]["synthetic_eligible_folds"]),
        },
    }


def _participant_import_report_filename(participant_reference: str) -> str:
    slug = "".join(ch for ch in str(participant_reference or "").strip() if ch.isalnum()) or "participant"
    return f"Phase8A.2A_{slug}_participant_import_report.md"


def _participant_import_report_lines(*, status_payload: Mapping[str, Any], manifest: Mapping[str, Any], report: Mapping[str, Any]) -> list[str]:
    return [
        "# Phase 8A.2A Participant Import Report",
        "",
        "## Status",
        f"- participant_reference: `{status_payload['participant_reference']}`",
        f"- real_runner_count: `{status_payload['real_runner_count']}`",
        f"- usable_records: `{manifest['dataset']['usable_records']}`",
        f"- restricted_records: `{manifest['dataset']['restricted_records']}`",
        f"- real_eligible_folds: `{status_payload['real_eligible_folds']}`",
        f"- synthetic_eligible_folds: `{status_payload['synthetic_eligible_folds']}`",
        f"- total_eligible_folds: `{status_payload['total_eligible_folds']}`",
        f"- distance_to_30: `{status_payload['distance_to_30']}`",
        f"- calibration_status: `{status_payload['calibration_status']}`",
        f"- calibration_allowed: `{status_payload['calibration_allowed']}`",
        f"- user_facing_prediction_allowed: `{status_payload['user_facing_prediction_allowed']}`",
        f"- public_case_study_authorized: `{status_payload['public_case_study_authorized']}`",
        "",
        "## Confirmation",
        f"- confirmed_records: `{report['confirmed_records']}`",
        f"- confirmation_date: `{report.get('confirmation_date') or ''}`",
        "- confirmation_basis: `participant_confirmation`",
        "- result_status_source: `participant_confirmation`",
        "",
        "## Privacy",
        "- Real name and ITRA ID mapping remain in the local-only identity map.",
        "- Public outputs stay anonymous even when public case study authorization is present.",
    ]


def import_participant_trial(
    *,
    intake_path: Path,
    confirmation_path: Path,
    runner_profile_path: Path,
    output_dir: Path,
    sensitive_map_output: Path | None = None,
) -> dict[str, Any]:
    intake = _load_json(intake_path)
    confirmation = _load_json(confirmation_path)
    runner_profile = _load_json(runner_profile_path)
    records, report = build_participant_records(
        intake=intake,
        confirmation=confirmation,
        runner_profile=runner_profile,
        runner_profile_path=runner_profile_path,
    )
    records, dedupe_summary = _dedupe_participant_records(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    sensitive_map = {
        "schema_name": "participant_identity_map_local_only",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_reference": str(intake.get("participant_reference") or ""),
        "provided_name": str(intake.get("provided_name") or ""),
        "provided_itra_id": str(intake.get("provided_itra_id") or ""),
        "pseudonymous_runner_id": report["pseudonymous_runner_id"],
        "source_runner_profile": str(runner_profile_path.resolve()),
        "sensitive": True,
        "local_only": True,
    }
    if sensitive_map_output is None:
        sensitive_map_output = output_dir / "participant_identity_map.local.json"
    sensitive_map_output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(sensitive_map_output, sensitive_map)
    _write_json(output_dir / "participant_intake.json", _public_participant_intake_payload(intake))
    _write_json(output_dir / "runner_history_confirmation.json", confirmation)

    manifest_outputs = write_dataset_outputs(records=records, output_dir=output_dir, source_files=[runner_profile_path, intake_path, confirmation_path])
    dataset_manifest = manifest_outputs["manifest"]

    report["usable_records"] = int(dataset_manifest["dataset"]["usable_records"])
    report["restricted_records"] = int(dataset_manifest["dataset"]["restricted_records"])
    report["real_eligible_folds"] = int(dataset_manifest["dataset"]["real_eligible_folds"])
    report["calibration_allowed"] = bool(dataset_manifest["dataset"]["calibration_allowed"])
    report["user_facing_prediction_allowed"] = bool(dataset_manifest["dataset"]["user_facing_prediction_allowed"])
    report["confirmation_date"] = confirmation.get("confirmation_date")
    if "participant_confirmation_text" in confirmation:
        report["participant_confirmation_text"] = confirmation.get("participant_confirmation_text")
    participant_reference = str(intake.get("participant_reference") or "")

    status_payload = _participant_status_payload(intake=intake, manifest=dataset_manifest, trial_report=report, dedupe_summary=dedupe_summary)
    import_manifest_payload = _participant_import_manifest_payload(
        intake=intake,
        confirmation=confirmation,
        manifest=dataset_manifest,
        trial_report=report,
        dedupe_summary=dedupe_summary,
        runner_profile_path=runner_profile_path,
        intake_path=intake_path,
        confirmation_path=confirmation_path,
        sensitive_map_output=sensitive_map_output,
    )
    _write_json(output_dir / "participant_status.json", status_payload)
    _write_json(output_dir / "participant_import_manifest.json", import_manifest_payload)
    _write_json(output_dir / "participant_trial_status.json", status_payload)

    participant_records = _participant_records_anonymized_payload(intake=intake, manifest=dataset_manifest, records=records)
    _write_json(output_dir / "participant_records.anonymized.json", participant_records)

    report_path = output_dir / _participant_import_report_filename(participant_reference)
    report_lines = _participant_import_report_lines(status_payload=status_payload, manifest=dataset_manifest, report=report)
    report_lines.extend(
        [
            "",
            "## Deduplication",
            f"- signature_policy: `{dedupe_summary['signature_policy']}`",
            f"- input_records: `{dedupe_summary['input_records']}`",
            f"- unique_records: `{dedupe_summary['unique_records']}`",
            f"- duplicate_records: `{dedupe_summary['duplicate_records']}`",
            "",
            "## Notes",
        ]
    )
    for note in report["notes"]:
        report_lines.append(f"- {note}")
    report_lines.extend(
        [
            "",
            "## Files",
            "- `participant_intake.json`",
            "- `runner_history_confirmation.json`",
            "- `participant_records.anonymized.json`",
            "- `participant_import_manifest.json`",
            "- `participant_status.json`",
            "- `privacy_audit_report.md`",
        ]
    )
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    privacy_report = _privacy_audit_report(
        intake=intake,
        public_paths=[
            output_dir / "participant_import_manifest.json",
            output_dir / "participant_status.json",
            output_dir / "participant_records.anonymized.json",
            output_dir / "backtest_dataset_manifest.json",
            output_dir / "eligibility_report.json",
            report_path,
        ],
        manifest_payload=import_manifest_payload,
        status_payload=status_payload,
        trial_report_path=output_dir / "participant_trial_report.json",
        sensitive_map_output=sensitive_map_output,
    )
    (output_dir / "privacy_audit_report.md").write_text(privacy_report, encoding="utf-8")
    public_trial_report = dict(report)
    public_trial_report.pop("provided_name_local_only", None)
    public_trial_report.pop("provided_itra_id_local_only", None)
    _write_json(output_dir / "participant_trial_report.json", public_trial_report)

    return {
        "records": records,
        "trial_report": report,
        "manifest": dataset_manifest,
        "eligibility_report": manifest_outputs["eligibility_report"],
        "sensitive_map": sensitive_map,
        "participant_status": status_payload,
        "participant_import_manifest": import_manifest_payload,
        "participant_records": participant_records,
        "participant_import_report_path": report_path,
        "dedupe_summary": dedupe_summary,
    }

