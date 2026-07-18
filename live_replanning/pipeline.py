"""Phase 12 event normalization, delayed replay, and conservative replanning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import CACHE_POLICY_VERSION, GENERATOR_VERSION, RED_FLAGS, SAFETY_NOTICE, SCHEMA_VERSION, SOURCE_POLICY_VERSION
from .report import build_markdown_report
from .validation import LiveReplanningValidationError, parse_datetime, validate_inputs
from reporting_contract import apply_output_contract


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(event: Mapping[str, Any]) -> str:
    stable = {key: event.get(key) for key in ("event_type", "observed_at", "source", "payload")}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _normalize_events(events: list[Mapping[str, Any]], as_of_dt: datetime) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], bool]:
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    accepted: list[dict[str, Any]] = []
    duplicates: list[str] = []
    input_times = [parse_datetime(event["observed_at"]) for event in events]
    out_of_order = input_times != sorted(input_times)
    for event in events:
        fingerprint = _fingerprint(event)
        if event["event_id"] in seen_ids or fingerprint in seen_fingerprints:
            duplicates.append(str(event["event_id"]))
            continue
        seen_ids.add(str(event["event_id"]))
        seen_fingerprints.add(fingerprint)
        row = deepcopy(dict(event))
        observed = parse_datetime(row["observed_at"])
        received = parse_datetime(row["received_at"])
        assert observed is not None and received is not None
        delay = (received - observed).total_seconds() / 60.0
        age = max((as_of_dt - observed).total_seconds() / 60.0, 0.0)
        source_type = row["source"]["source_type"]
        if source_type == "official_timing" and row["event_type"] == "checkpoint":
            effective_confidence = float(row["confidence"])
        else:
            effective_confidence = float(row["confidence"]) * max(0.15, 1.0 - age / 240.0)
        row.update(
            {
                "event_delay_minutes": round(delay, 3),
                "information_age_minutes": round(age, 3),
                "effective_confidence": round(effective_confidence, 6),
                "event_fingerprint": fingerprint,
            }
        )
        accepted.append(row)
    accepted.sort(key=lambda item: (item["observed_at"], item["received_at"], item["event_id"]))

    conflicts: list[dict[str, Any]] = []
    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for row in accepted:
        if row["event_type"] == "checkpoint":
            key = (row["payload"].get("checkpoint_sequence"), row["payload"].get("timing_kind", "manual"))
            groups.setdefault(key, []).append(row)
    for key, rows in groups.items():
        elapsed = {row["payload"].get("elapsed_minutes") for row in rows}
        if len(elapsed) > 1:
            winner = max(rows, key=lambda row: (row["source"]["source_type"] == "official_timing", row["effective_confidence"], row["received_at"]))
            conflicts.append({"checkpoint_sequence": key[0], "timing_kind": key[1], "event_ids": [row["event_id"] for row in rows], "selected_event_id": winner["event_id"], "resolution": "official_then_confidence_then_received_time"})
    return accepted, duplicates, conflicts, out_of_order


def _strategy(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    recommended = plan.get("recommended_strategy") or "stable"
    strategies = plan.get("strategies", {})
    return strategies.get(recommended) or strategies.get("stable") or strategies.get("safe_finish") or {}


def _checkpoint_rows(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    strategy = _strategy(plan)
    return list(strategy.get("checkpoints", []))


def _stop_reason(events: list[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for event in events:
        payload = event["payload"]
        flags = set(payload.get("red_flags") or [])
        reasons.extend(sorted(flags & RED_FLAGS))
        source_type = event["source"]["source_type"]
        instruction = str(payload.get("instruction") or "").lower()
        if source_type in {"race_staff", "medical_staff"} and instruction in {"stop", "withdraw", "dnf", "seek_medical_help"}:
            reasons.append(f"{source_type}:{instruction}")
    return bool(reasons), sorted(set(reasons))


def _yellow_concerns(events: list[Mapping[str, Any]]) -> list[str]:
    concerns: list[str] = []
    for event in events:
        payload = event["payload"]
        if payload.get("risk_level") == "yellow":
            concerns.append("reported_yellow_risk")
        state = str(payload.get("state") or "").lower()
        if state in {"struggling", "nausea", "pain", "fatigued", "cold", "overheated"}:
            concerns.append(f"runner_state:{state}")
        for key in ("fueling_failure", "equipment_failure", "weather_hazard", "course_hazard"):
            if payload.get(key) is True:
                concerns.append(key)
    return sorted(set(concerns))


def build_live_replan(*, race_plan: Mapping[str, Any], events: list[Mapping[str, Any]], as_of: str, processing_mode: str = "near_real_time", case_reference: str = "anonymous_internal_case", validation_context: str = "synthetic") -> dict[str, Any]:
    errors = validate_inputs(race_plan, events, as_of, processing_mode)
    if errors:
        raise LiveReplanningValidationError("; ".join(errors))
    as_of_dt = parse_datetime(as_of)
    assert as_of_dt is not None
    normalized, duplicates, conflicts, out_of_order = _normalize_events(events, as_of_dt)
    red_stop, stop_reasons = _stop_reason(normalized)
    yellow_concerns = _yellow_concerns(normalized)
    conflicting_losers = {
        event_id
        for conflict in conflicts
        for event_id in conflict["event_ids"]
        if event_id != conflict["selected_event_id"]
    }
    checkpoint_events = [
        row
        for row in normalized
        if row["event_type"] == "checkpoint"
        and row["payload"].get("checkpoint_sequence") is not None
        and row["event_id"] not in conflicting_losers
        and row["source"]["source_type"] != "system_estimate"
    ]
    latest = max(checkpoint_events, key=lambda row: (int(row["payload"]["checkpoint_sequence"]), row["observed_at"])) if checkpoint_events else None
    timing_mode = "no_live"
    if latest:
        kind = latest["payload"].get("timing_kind", "manual")
        timing_mode = kind if kind in {"entry", "exit", "manual"} else "manual"
    cp_rows = _checkpoint_rows(race_plan)
    by_sequence = {int(row.get("sequence")): row for row in cp_rows if row.get("sequence") is not None}
    current_sequence = int(latest["payload"]["checkpoint_sequence"]) if latest else None
    current_plan = by_sequence.get(current_sequence) if current_sequence else None
    next_plan = next((by_sequence[key] for key in sorted(by_sequence) if current_sequence is not None and key > current_sequence), None)
    observed_elapsed = float(latest["payload"]["elapsed_minutes"]) if latest and latest["payload"].get("elapsed_minutes") is not None else None
    planned_elapsed = ((current_plan or {}).get("arrival_elapsed_range_minutes") or {}).get("midpoint")
    schedule_delay = round(observed_elapsed - float(planned_elapsed), 2) if observed_elapsed is not None and planned_elapsed is not None else None
    explicit_components: dict[str, float] = {}
    for row in normalized:
        for key, value in (row["payload"].get("delay_components_minutes") or {}).items():
            if isinstance(value, (int, float)):
                explicit_components[key] = round(explicit_components.get(key, 0.0) + float(value), 2)
    explained = round(sum(explicit_components.values()), 2)
    delay_decomposition = {
        "observed_schedule_delay_minutes": schedule_delay,
        "explicit_components_minutes": explicit_components,
        "unexplained_minutes": round(schedule_delay - explained, 2) if schedule_delay is not None else None,
        "causal_claim_allowed": False,
    }
    strategy = _strategy(race_plan)
    original_finish = strategy.get("finish_range") or {}
    finish_range = None
    if not red_stop and schedule_delay is not None and all(original_finish.get(key) is not None for key in ("lower_minutes", "midpoint_minutes", "upper_minutes")):
        stale_width = max((latest or {}).get("information_age_minutes", 0.0) * 0.15, 0.0)
        finish_range = {
            "lower": round(float(original_finish["lower_minutes"]) + schedule_delay - stale_width, 2),
            "midpoint": round(float(original_finish["midpoint_minutes"]) + schedule_delay, 2),
            "upper": round(float(original_finish["upper_minutes"]) + schedule_delay + stale_width, 2),
            "status": "derived_internal_replan_not_user_facing",
        }
    next_checkpoint = None
    if next_plan is not None and observed_elapsed is not None and current_plan is not None and not red_stop:
        current_mid = float(current_plan["arrival_elapsed_range_minutes"]["midpoint"])
        delta = float(next_plan["arrival_elapsed_range_minutes"]["midpoint"]) - current_mid
        age = float((latest or {}).get("information_age_minutes", 0.0))
        width = max(10.0, age * 0.2)
        midpoint = observed_elapsed + delta
        cutoff = next_plan.get("official_cutoff_elapsed_minutes")
        margin = round(float(cutoff) - (midpoint + width), 2) if cutoff is not None else None
        risk = "not_yet_verified" if margin is None else ("high" if margin < 0 else ("watch" if margin < 30 else "low"))
        next_checkpoint = {
            "sequence": next_plan.get("sequence"),
            "name": next_plan.get("name"),
            "arrival_elapsed_range_minutes": {"lower": round(midpoint - width, 2), "midpoint": round(midpoint, 2), "upper": round(midpoint + width, 2)},
            "official_cutoff_elapsed_minutes": cutoff,
            "minimum_cutoff_margin_minutes": margin,
            "cutoff_risk": risk,
            "based_on_information_age_minutes": age,
        }
    stale_state = [row for row in normalized if row["event_type"] == "runner_state" and row["information_age_minutes"] >= 60]
    if red_stop:
        action = "stop_performance_planning_follow_race_or_medical_staff"
    elif next_checkpoint and next_checkpoint["cutoff_risk"] == "high":
        action = "downgrade_goal_do_not_chase_lost_time"
    elif yellow_concerns:
        action = "switch_to_safe_finish_due_to_reported_condition"
    elif stale_state or (latest and latest["information_age_minutes"] >= 120):
        action = "conservative_due_to_stale_information"
    elif schedule_delay is not None and schedule_delay > 20:
        action = "switch_to_safe_finish"
    else:
        action = "maintain_conservative_plan"
    latest_age = min((row["information_age_minutes"] for row in normalized), default=None)
    warnings = []
    if not normalized:
        warnings.append("No timing or state evidence is available; current checkpoint and runner state remain unknown.")
    if stale_state:
        warnings.append("One or more state observations are stale and must not be described as current runner status.")
    if latest and latest["information_age_minutes"] >= 120:
        warnings.append("The latest checkpoint information is at least two hours old; uncertainty was widened.")
    if conflicts:
        warnings.append("Conflicting checkpoint events were preserved and resolved by the declared source priority.")
    actual_live = "pending_future_event" if validation_context == "future_event" else ("not_claimed_historical_replay" if validation_context == "historical_replay" else "not_claimed_synthetic")
    prior_sequences = [key for key in sorted(by_sequence) if current_sequence is not None and 1 < key < current_sequence]
    observed_sequences = {int(row["payload"]["checkpoint_sequence"]) for row in checkpoint_events}
    unobserved_prior = [key for key in prior_sequences if key not in observed_sequences]
    return {
        "schema_name": "live_replanning_snapshot",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "case_reference": case_reference,
        "privacy": {"identity_included": False, "local_internal_validation_only": True, "public_export_allowed": False},
        "governance": {"phase8a_validation_decision": "retain_distance_only", "selected_model": "distance_only", "full_model_status": "rejected", "holdout_evaluation_run": False, "holdout_status": "permanently_not_entered", "user_facing_prediction_allowed": False, "output_scope": "internal_research_live_replanning_only"},
        "processing_mode": processing_mode,
        "as_of": as_of,
        "validation_status": {"context": validation_context, "actual_live_validation": actual_live, "historical_or_synthetic_replay_is_not_live_validation": True},
        "events": normalized,
        "event_conflicts": conflicts,
        "timing_state": {"timing_mode": timing_mode, "latest_checkpoint_sequence": current_sequence, "latest_checkpoint": (current_plan or {}).get("name"), "observed_elapsed_minutes": observed_elapsed, "entry_and_exit_not_inferred_from_single_ping": True},
        "freshness": {"latest_information_age_minutes": latest_age, "state_confidence_decays_with_delay": True, "official_timing_fact_persists": True},
        "delay_decomposition": delay_decomposition,
        "updated_finish_range_minutes": finish_range,
        "next_checkpoint": next_checkpoint,
        "decision": {"action": action, "red_flag_stop": red_stop, "stop_reasons": stop_reasons, "yellow_concerns": yellow_concerns, "recover_all_lost_time_at_once_allowed": False, "official_and_medical_instructions_override": True},
        "warnings": warnings,
        "unavailable_fields": [key for key, value in {"current_checkpoint": current_sequence, "observed_elapsed_minutes": observed_elapsed, "next_checkpoint": next_checkpoint}.items() if value is None],
        "diagnostics": {"input_event_count": len(events), "accepted_event_count": len(normalized), "duplicate_event_count": len(duplicates), "duplicate_event_ids": duplicates, "conflict_count": len(conflicts), "out_of_order_input": out_of_order, "unobserved_prior_checkpoint_sequences": unobserved_prior, "missing_timing_never_inferred": True, "system_estimate_checkpoint_count_excluded_from_observed_timing": sum(1 for row in normalized if row["event_type"] == "checkpoint" and row["source"]["source_type"] == "system_estimate")},
    }


def replay_live_replan(*, race_plan_path: Path, events_path: Path, as_of: str, processing_mode: str, case_reference: str, validation_context: str) -> dict[str, Any]:
    return build_live_replan(race_plan=json.loads(race_plan_path.read_text(encoding="utf-8")), events=json.loads(events_path.read_text(encoding="utf-8")), as_of=as_of, processing_mode=processing_mode, case_reference=case_reference, validation_context=validation_context)


def write_live_replan(snapshot: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    artifact = apply_output_contract(snapshot, report_type="live_update", workflow_stage="phase12", report_status=str(snapshot.get("processing_mode")))
    (output_dir / "live_replanning_snapshot.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "live_replanning_snapshot.md").write_text(build_markdown_report(artifact), encoding="utf-8")
