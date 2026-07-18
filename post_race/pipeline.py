"""Phase 13 evidence-layered retro, personal calibration, export, and deletion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import CACHE_POLICY_VERSION, GENERATOR_VERSION, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION
from .report import build_markdown_report
from .validation import PostRaceValidationError, validate_inputs
from reporting_contract import apply_output_contract


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strategy(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    recommended = plan.get("recommended_strategy") or "stable"
    strategies = plan.get("strategies", {})
    return strategies.get(recommended) or strategies.get("stable") or strategies.get("safe_finish") or {}


def _snapshot_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _confidence_label(source_type: str) -> str:
    return "high" if source_type in {"official_result", "official_timing"} else ("medium" if source_type in {"participant_confirmation", "device_export"} else "low")


def build_race_retro(*, race_plan: Mapping[str, Any], actual_result: Mapping[str, Any], conditions: Mapping[str, Any], participant_consent: Mapping[str, Any], prior_personal_model: Mapping[str, Any] | None = None, case_reference: str = "anonymous_internal_case", validation_context: str = "synthetic") -> dict[str, Any]:
    errors = validate_inputs(race_plan, actual_result, conditions, validation_context)
    if errors:
        raise PostRaceValidationError("; ".join(errors))
    strategy = _strategy(race_plan)
    planned_rows = {int(row["sequence"]): row for row in strategy.get("checkpoints", []) if row.get("sequence") is not None}
    actual_rows = deepcopy(actual_result.get("checkpoints", []))
    cp_errors: list[dict[str, Any]] = []
    for row in actual_rows:
        sequence = int(row["sequence"])
        planned = planned_rows.get(sequence)
        planned_mid = ((planned or {}).get("arrival_elapsed_range_minutes") or {}).get("midpoint")
        actual_elapsed = row.get("elapsed_minutes")
        cp_errors.append({
            "sequence": sequence,
            "checkpoint_reference": row.get("checkpoint_reference"),
            "planned_midpoint_minutes": planned_mid,
            "actual_elapsed_minutes": actual_elapsed,
            "signed_error_minutes": round(float(actual_elapsed) - float(planned_mid), 2) if actual_elapsed is not None and planned_mid is not None else None,
            "source_type": row.get("source_type"),
            "confidence": _confidence_label(str(row.get("source_type"))),
        })
    finish_time = actual_result.get("finish_time_minutes")
    finish_range = strategy.get("finish_range") or {}
    finish_mid = finish_range.get("midpoint_minutes")
    finish_error = {
        "planned_midpoint_minutes": finish_mid,
        "actual_minutes": finish_time,
        "signed_error_minutes": round(float(finish_time) - float(finish_mid), 2) if finish_time is not None and finish_mid is not None else None,
        "absolute_percentage_error": round(abs(float(finish_time) - float(finish_mid)) / float(finish_time) * 100, 6) if finish_time not in (None, 0) and finish_mid is not None else None,
    }
    moving = actual_result.get("moving_time_minutes")
    stopped = actual_result.get("stopped_time_minutes")
    planned_stopped = round(sum(float(row.get("planned_stop_minutes") or 0) for row in strategy.get("checkpoints", [])), 2)
    planned_moving = round(float(finish_mid) - planned_stopped, 2) if finish_mid is not None else None
    if moving is not None and stopped is not None and finish_time is not None:
        reconciliation = round(float(finish_time) - float(moving) - float(stopped), 2)
        status = "reconciled" if abs(reconciliation) <= 1 else "does_not_reconcile"
    else:
        reconciliation = None
        status = "not_available_not_guessed"
    sectors = []
    for label, rows in (("early", cp_errors[: max(1, len(cp_errors) // 3)]), ("middle", cp_errors[max(1, len(cp_errors) // 3): max(2, 2 * len(cp_errors) // 3)]), ("late", cp_errors[max(2, 2 * len(cp_errors) // 3):])):
        values = [row["signed_error_minutes"] for row in rows if row["signed_error_minutes"] is not None]
        sectors.append({"sector": label, "mean_signed_error_minutes": round(sum(values) / len(values), 2) if values else None, "status": "derived_from_checkpoint_rows" if values else "not_available"})
    observed_factors = []
    for family in ("weather", "surface", "fueling", "equipment", "private_support"):
        value = conditions.get(family)
        if value is not None:
            observed_factors.append({"factor": family, "observation": deepcopy(value), "layer": "fact_or_participant_report", "causal_effect_proven": False})
    prior = deepcopy(dict(prior_personal_model or {}))
    prior_multiplier = float(prior.get("finish_multiplier", 1.0))
    prior_count = int(prior.get("completed_race_count", 0))
    eligible_update = actual_result.get("result_status") == "finish" and finish_time is not None and finish_mid not in (None, 0)
    raw_ratio = float(finish_time) / float(finish_mid) if eligible_update else None
    change = max(-0.10, min(0.10, 0.25 * (raw_ratio - 1.0))) if raw_ratio is not None else 0.0
    updated_multiplier = round(prior_multiplier * (1.0 + change), 6)
    personal_model = {
        "schema_name": "local_personal_race_model",
        "schema_version": SCHEMA_VERSION,
        "owner_reference": case_reference,
        "storage_classification": "sensitive_local_only",
        "serves_owner_only": True,
        "public_export_allowed": False,
        "finish_multiplier": updated_multiplier,
        "completed_race_count": prior_count + (1 if eligible_update else 0),
        "update_applied": eligible_update,
        "single_race_update_cap_fraction": 0.10,
        "single_race_cannot_permanently_redefine_ability": True,
        "prior": {"finish_multiplier": prior_multiplier, "completed_race_count": prior_count},
        "evidence": {"race_snapshot_pending_digest": True, "raw_finish_ratio": round(raw_ratio, 6) if raw_ratio is not None else None, "shrunken_change_fraction": round(change, 6)},
        "tuning_boundaries": {"validation_used": False, "holdout_used": False, "full_model_used": False},
    }
    explicit_general_consent = participant_consent.get("anonymous_general_model_contribution") is True
    facts = {
        "result_status": actual_result["result_status"],
        "finish_time_minutes": finish_time,
        "moving_time_minutes": moving,
        "stopped_time_minutes": stopped,
        "checkpoints": actual_rows,
        "result_source": deepcopy(actual_result.get("source")),
        "conditions": observed_factors,
    }
    analysis = {
        "finish_error": finish_error,
        "checkpoint_errors": cp_errors,
        "movement_and_stopped": {"planned_moving_minutes": planned_moving, "actual_moving_minutes": moving, "moving_signed_error_minutes": round(float(moving) - planned_moving, 2) if moving is not None and planned_moving is not None else None, "planned_stopped_minutes": planned_stopped, "actual_stopped_minutes": stopped, "stopped_signed_error_minutes": round(float(stopped) - planned_stopped, 2) if stopped is not None else None, "reconciliation_difference_minutes": reconciliation, "status": status},
        "race_sectors": sectors,
        "night_segment": deepcopy(actual_result.get("night_segment")) if actual_result.get("night_segment") is not None else {"status": "not_available_not_guessed", "planned_minutes": None, "actual_minutes": None, "signed_error_minutes": None},
        "factor_interpretation": [{"factor": row["factor"], "inference": "may_have_contributed_but_not_causally_established", "confidence": "low"} for row in observed_factors],
        "reference_path_reliability": {"selected_model": "distance_only", "full_model": "rejected_in_phase8a_validation", "claim_beyond_available_evidence": False},
    }
    recommendations = [
        {"recommendation": "Use the shrunken personal multiplier as a local hypothesis for the next internal plan, not as a permanent ability label.", "evidence": "finish_error", "confidence": "medium" if eligible_update else "low"},
        {"recommendation": "Review checkpoint rows with the largest verified error before changing movement or stop assumptions.", "evidence": "checkpoint_errors", "confidence": "medium" if cp_errors else "low"},
    ]
    digest_payload = {"case_reference": case_reference, "actual_result": actual_result, "conditions": conditions, "facts": facts, "analysis": analysis, "personal_model": personal_model}
    digest = _snapshot_digest(digest_payload)
    personal_model["evidence"]["race_snapshot_digest"] = digest
    personal_model["evidence"].pop("race_snapshot_pending_digest")
    actual_live = "pending_future_event" if validation_context == "future_event" else ("not_claimed_historical_replay" if validation_context == "historical_replay" else "not_claimed_synthetic")
    return {
        "schema_name": "race_retro",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "case_reference": case_reference,
        "privacy": {"identity_included": False, "storage_classification": "sensitive_local_only", "public_export_allowed": False},
        "governance": {"phase8a_validation_decision": "retain_distance_only", "selected_model": "distance_only", "full_model_status": "rejected", "holdout_evaluation_run": False, "holdout_status": "permanently_not_entered", "user_facing_prediction_allowed": False, "output_scope": "internal_research_post_race_only"},
        "validation_status": {"context": validation_context, "actual_live_validation": actual_live, "historical_or_synthetic_replay_is_not_live_validation": True},
        "immutability": {"snapshot_id": f"retro-{digest[:16]}", "content_sha256": digest, "digest_scope": "normalized_input_facts_analysis_and_personal_model_before_digest_binding", "immutable": True, "write_policy": "new_directory_no_overwrite"},
        "facts": facts,
        "analysis": analysis,
        "recommendations": recommendations,
        "personal_model": personal_model,
        "general_model": {"contribution_allowed": explicit_general_consent, "consent_basis": "explicit_participant_consent" if explicit_general_consent else "not_authorized", "identity_mapping_included": False, "health_details_included": False, "row_level_public_export_allowed": False},
        "unavailable_fields": [key for key, value in {"finish_time_minutes": finish_time, "moving_time_minutes": moving, "stopped_time_minutes": stopped}.items() if value is None],
        "warnings": ["Facts, inferences, and recommendations are separate layers.", "A condition report does not by itself prove a causal performance effect.", "This local personal model is not tuned on validation or holdout data."],
    }


def build_general_model_contribution(retro: Mapping[str, Any], participant_consent: Mapping[str, Any]) -> dict[str, Any]:
    if participant_consent.get("anonymous_general_model_contribution") is not True or retro.get("general_model", {}).get("contribution_allowed") is not True:
        return {"schema_name": "anonymous_general_model_contribution", "schema_version": SCHEMA_VERSION, "allowed": False, "reason": "explicit_participant_consent_required", "payload": None}
    finish_error = retro["analysis"]["finish_error"]
    payload = {
        "result_status": retro["facts"]["result_status"],
        "finish_ape": finish_error.get("absolute_percentage_error"),
        "checkpoint_count": len(retro["analysis"]["checkpoint_errors"]),
        "movement_decomposition_available": retro["analysis"]["movement_and_stopped"]["status"] == "reconciled",
        "validation_context": retro["validation_status"]["context"],
    }
    return {"schema_name": "anonymous_general_model_contribution", "schema_version": SCHEMA_VERSION, "allowed": True, "classification": "internal_research_anonymous_aggregate", "identity_mapping_included": False, "health_details_included": False, "row_level_public_export_allowed": False, "payload": payload}


def replay_race_retro(*, race_plan_path: Path, actual_result_path: Path, conditions_path: Path, consent_path: Path, prior_model_path: Path | None, case_reference: str, validation_context: str) -> dict[str, Any]:
    return build_race_retro(race_plan=json.loads(race_plan_path.read_text(encoding="utf-8")), actual_result=json.loads(actual_result_path.read_text(encoding="utf-8")), conditions=json.loads(conditions_path.read_text(encoding="utf-8")), participant_consent=json.loads(consent_path.read_text(encoding="utf-8")), prior_personal_model=json.loads(prior_model_path.read_text(encoding="utf-8")) if prior_model_path else None, case_reference=case_reference, validation_context=validation_context)


def write_race_retro(retro: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    artifact = apply_output_contract(retro, report_type="race_retro", workflow_stage="phase13", report_status=str(retro.get("validation_status", {}).get("actual_live_validation", "unknown")))
    (output_dir / "race_retro.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "race_retro.md").write_text(build_markdown_report(artifact), encoding="utf-8")
    (output_dir / "personal_model.local.json").write_text(json.dumps(retro["personal_model"], ensure_ascii=False, indent=2), encoding="utf-8")


def export_personal_model(model: Mapping[str, Any], output_dir: Path) -> None:
    if model.get("storage_classification") != "sensitive_local_only" or model.get("serves_owner_only") is not True:
        raise PostRaceValidationError("local_owner_only_personal_model_required")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "personal_model_export.local.json").write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")


def migrate_personal_model(model: Mapping[str, Any], new_owner_reference: str) -> dict[str, Any]:
    if model.get("schema_name") != "local_personal_race_model" or model.get("storage_classification") != "sensitive_local_only" or model.get("serves_owner_only") is not True:
        raise PostRaceValidationError("local_owner_only_personal_model_required")
    if not new_owner_reference:
        raise PostRaceValidationError("new_owner_reference_required")
    migrated = deepcopy(dict(model))
    prior_owner = migrated.get("owner_reference")
    migrated["owner_reference"] = new_owner_reference
    migrated["migration"] = {"migrated_at": _utc_now(), "from_owner_reference_sha256": hashlib.sha256(str(prior_owner).encode("utf-8")).hexdigest(), "identity_mapping_included": False, "preserved_schema_version": migrated.get("schema_version")}
    return migrated


def delete_personal_model(path: Path, confirmation: str) -> bool:
    if confirmation != "DELETE_LOCAL_PERSONAL_MODEL":
        raise PostRaceValidationError("explicit_delete_confirmation_required")
    if path.name not in {"personal_model.local.json", "personal_model_export.local.json"}:
        raise PostRaceValidationError("refuse_delete_non_personal_model_path")
    if not path.exists():
        return False
    path.unlink()
    return True
