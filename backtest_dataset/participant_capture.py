"""Phase 8A.2A-P2 Step 1: pre-disclosed participant capture helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path.name}:expected_json_object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalize_id(value: Any) -> str:
    return str(value or "").strip()


def _participant_slug(participant_reference: str) -> str:
    slug = "".join(ch for ch in str(participant_reference or "").strip() if ch.isalnum())
    return slug or "participant"


def _participant_history_title(participant_reference: str) -> str:
    return f"# {_participant_slug(participant_reference)} 比赛历史待确认"


def _participant_history_filename(participant_reference: str) -> str:
    return f"{_participant_slug(participant_reference)}_比赛历史待确认.md"


def evaluate_identity_match(capture_result: Mapping[str, Any], *, provided_name: str, provided_itra_id: str) -> dict[str, Any]:
    candidates = capture_result.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    runner_id = _normalize_id(provided_itra_id)
    normalized_name = _normalize_name(provided_name)
    exact_id_matches = [item for item in candidates if isinstance(item, Mapping) and _normalize_id(item.get("RunnerId")) == runner_id]
    same_name_candidates = [
        item
        for item in candidates
        if isinstance(item, Mapping) and _normalize_name(f"{item.get('FirstName')} {item.get('LastName')}") == normalized_name
    ]
    page_identity = capture_result.get("identity", {}) if isinstance(capture_result.get("identity", {}), Mapping) else {}
    page_runner_id = _normalize_id(page_identity.get("runner_id"))
    page_name = _normalize_name(page_identity.get("name"))
    if page_runner_id == runner_id:
        return {
            "identity_match_status": "matched_exact_runner_id",
            "runner_id_match": True,
            "name_match": bool(page_name == normalized_name or page_name.replace(" ", "") == normalized_name.replace(" ", "")),
            "candidate_count": len(candidates),
            "same_name_candidate_count": len(same_name_candidates),
            "conflict": len(same_name_candidates) > 1 and len(exact_id_matches) == 0,
        }
    if len(exact_id_matches) == 1:
        return {
            "identity_match_status": "matched_candidate_only",
            "runner_id_match": False,
            "name_match": bool(page_name == normalized_name or page_name.replace(" ", "") == normalized_name.replace(" ", "")),
            "candidate_count": len(candidates),
            "same_name_candidate_count": len(same_name_candidates),
            "conflict": True,
        }
    if len(same_name_candidates) > 1:
        return {
            "identity_match_status": "needs_user_selection",
            "runner_id_match": False,
            "name_match": True,
            "candidate_count": len(candidates),
            "same_name_candidate_count": len(same_name_candidates),
            "conflict": True,
        }
    if len(same_name_candidates) == 1:
        return {
            "identity_match_status": "matched_name_only",
            "runner_id_match": False,
            "name_match": True,
            "candidate_count": len(candidates),
            "same_name_candidate_count": 1,
            "conflict": True,
        }
    if candidates:
        return {
            "identity_match_status": "needs_user_selection",
            "runner_id_match": False,
            "name_match": False,
            "candidate_count": len(candidates),
            "same_name_candidate_count": 0,
            "conflict": True,
        }
    return {
        "identity_match_status": "not_found",
        "runner_id_match": False,
        "name_match": False,
        "candidate_count": 0,
        "same_name_candidate_count": 0,
        "conflict": False,
    }


def build_predisclosed_confirmation_records(capture_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in capture_result.get("race_results", []):
        if not isinstance(item, Mapping):
            continue
        records.append(
            {
                "event_name": item.get("race"),
                "race_date": item.get("date"),
                "race_group": item.get("category"),
                "distance_km": item.get("distance_km"),
                "elevation_gain_m": item.get("elevation_gain_m"),
                "finish_time": item.get("race_time"),
                "result_status": None,
                "source_reference": item.get("race_url") or capture_result.get("identity", {}).get("profile_url"),
                "belongs_to_runner": None,
                "runner_correction": None,
                "evidence_confidence": 0.95 if item.get("race_time") else 0.75,
            }
        )
    return records


def build_capture_status(
    *,
    participant_reference: str,
    identity_match: Mapping[str, Any],
    capture_result: Mapping[str, Any],
    next_action: str,
    assigned_split: str | None = None,
) -> dict[str, Any]:
    race_results = capture_result.get("race_results", [])
    if not isinstance(race_results, list):
        race_results = []
    timed_finish_record_count = sum(1 for item in race_results if isinstance(item, Mapping) and item.get("race_time") not in (None, ""))
    return {
        "schema_name": "participant_capture_status",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_reference": participant_reference,
        "assigned_split": str(assigned_split or ""),
        "acquisition_status": str(capture_result.get("status") or "partial"),
        "identity_match_status": identity_match["identity_match_status"],
        "public_race_record_count": len([item for item in race_results if isinstance(item, Mapping)]),
        "timed_finish_record_count": timed_finish_record_count,
        "confirmation_required": True,
        "imported_to_backtest_pool": False,
        "real_eligible_folds_added": 0,
        "model_prediction_run": False,
        "next_action": next_action,
        "notes": [
            "Public evidence is captured for participant confirmation only.",
            "No record is auto-confirmed before the participant replies.",
        ],
    }


def _participant_intake_payload(participant_reference: str, intake: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": "participant_intake_template",
        "schema_version": "1.0.0",
        "participant_reference": participant_reference,
        "identity_confirmed": bool(intake.get("identity_confirmed")),
        "public_data_lookup_authorized": bool(intake.get("public_data_lookup_authorized")),
        "local_evaluation_authorized": bool(intake.get("local_evaluation_authorized")),
        "anonymized_aggregate_use_authorized": bool(intake.get("anonymized_aggregate_use_authorized")),
        "public_case_study_authorized": bool(intake.get("public_case_study_authorized")),
        "authorization_date": intake.get("authorization_date"),
        "notes": "Phase 8A.2A Step 1 pre-disclosed capture; real identity kept in local-only map.",
    }


def write_predisclosed_participant_capture(
    *,
    participant_reference: str,
    provided_name: str,
    provided_itra_id: str,
    intake: Mapping[str, Any],
    capture_result_path: Path,
    output_dir: Path,
    private_identity_output: Path,
    next_action: str,
    assigned_split: str | None = None,
) -> dict[str, Any]:
    capture_result = _load_json(capture_result_path)
    identity_match = evaluate_identity_match(
        capture_result,
        provided_name=provided_name,
        provided_itra_id=provided_itra_id,
    )
    confirmation_records = build_predisclosed_confirmation_records(capture_result)
    capture_status = build_capture_status(
        participant_reference=participant_reference,
        assigned_split=assigned_split,
        identity_match=identity_match,
        capture_result=capture_result,
        next_action=next_action,
    )
    intake_payload = _participant_intake_payload(participant_reference, intake)
    output_dir.mkdir(parents=True, exist_ok=True)
    private_identity_output.parent.mkdir(parents=True, exist_ok=True)
    private_identity_payload = {
        "schema_name": "participant_identity_map_local_only",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_reference": participant_reference,
        "provided_name": provided_name,
        "provided_itra_id": provided_itra_id,
        "pseudonymous_runner_id": f"participant_{_sha256_text('|'.join([participant_reference, provided_name, provided_itra_id]))[:12]}",
        "capture_source": str(capture_result_path.resolve()),
        "sensitive": True,
        "local_only": True,
    }
    _write_json(output_dir / "participant_intake.json", intake_payload)
    _write_json(output_dir / "runner_history_confirmation.predisclosed.json", confirmation_records)
    _write_json(output_dir / "capture_status.json", capture_status)
    _write_json(private_identity_output, private_identity_payload)

    lines = [
        _participant_history_title(participant_reference),
        "",
        "| 序号 | 日期 | 比赛名称和组别 | 距离 | 爬升 | 完赛时间 | 来源状态 | 是否本人比赛 | 需要修正 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(confirmation_records[:12], start=1):
        lines.append(
            f"| {index} | {row['race_date'] or ''} | {row['event_name'] or ''}（{row['race_group'] or ''}） | "
            f"{'' if row['distance_km'] is None else row['distance_km']} | "
            f"{'' if row['elevation_gain_m'] is None else row['elevation_gain_m']} | "
            f"{row['finish_time'] or ''} | 公共个人页已采集 | 待确认 | 待填写 |"
        )
    (output_dir / _participant_history_filename(participant_reference)).write_text("\n".join(lines), encoding="utf-8")

    return {
        "participant_intake": intake_payload,
        "confirmation_records": confirmation_records,
        "capture_status": capture_status,
        "identity_match": identity_match,
        "private_identity_map": private_identity_payload,
    }

