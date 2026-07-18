"""Pure rule evaluators for the Phase 8A evaluation protocol draft."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Any


def standard_median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _runner_key(row: Mapping[str, Any]) -> str:
    return str(
        row.get("runner_reference")
        or row.get("participant_reference")
        or row.get("pseudonymous_runner_id")
        or row.get("runner_id")
        or "unknown"
    )


def _participant_key(row: Mapping[str, Any]) -> str:
    return str(row.get("participant_reference") or row.get("runner_reference") or "")


def _split_key(row: Mapping[str, Any]) -> str:
    return str(row.get("split") or row.get("assigned_split") or row.get("target_split") or "")


def _fold_id(row: Mapping[str, Any]) -> str:
    return str(row.get("fold_id") or "").strip()


def _interval_block(row: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    intervals = row.get("intervals")
    if not isinstance(intervals, Mapping):
        return None
    block = intervals.get(name)
    return block if isinstance(block, Mapping) else None


def _covered(row: Mapping[str, Any], name: str) -> bool:
    prediction_minutes = _coerce_float(row.get("prediction_minutes"))
    actual_minutes = _coerce_float(row.get("actual_minutes"))
    if prediction_minutes is None or actual_minutes is None:
        return False
    block = _interval_block(row, name)
    if block is None:
        return False
    lower = _coerce_float(block.get("lower_minutes"))
    upper = _coerce_float(block.get("upper_minutes"))
    if lower is None or upper is None:
        return False
    return lower <= actual_minutes <= upper


def _distance_bucket(distance_km: Any) -> str:
    distance = _coerce_float(distance_km)
    if distance is None:
        return "unknown"
    if distance < 25:
        return "short_under_25_km"
    if distance <= 42:
        return "mid_25_to_42_km"
    return "long_over_42_km"


def _history_bucket(prior_history_count: Any) -> str:
    history = int(prior_history_count or 0)
    if history <= 0:
        return "no_history"
    if history == 1:
        return "1_history"
    if history == 2:
        return "2_history"
    return "3plus_history"


def _expected_assignment_map(expected_fold_assignments: Mapping[str, Any] | None) -> dict[str, dict[str, str]]:
    if not expected_fold_assignments:
        return {}
    result: dict[str, dict[str, str]] = {}
    for fold_id, payload in expected_fold_assignments.items():
        if not isinstance(payload, Mapping):
            continue
        result[str(fold_id)] = {
            "participant_reference": str(payload.get("participant_reference") or payload.get("runner_reference") or ""),
            "split": str(payload.get("split") or payload.get("assigned_split") or ""),
        }
    return result


def _row_meets_expected_assignment(
    row: Mapping[str, Any],
    *,
    expected_assignment: Mapping[str, str] | None,
) -> bool:
    if not expected_assignment:
        return True
    expected_participant = str(expected_assignment.get("participant_reference") or "")
    expected_split = str(expected_assignment.get("split") or "")
    actual_participant = _participant_key(row)
    actual_split = _split_key(row)
    if expected_participant and actual_participant != expected_participant:
        return False
    if expected_split and actual_split != expected_split:
        return False
    return True


def build_metric_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_fold_ids: Sequence[str],
    expected_fold_assignments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [row for row in rows if isinstance(row, Mapping)]
    expected_fold_ids = [str(fold_id) for fold_id in expected_fold_ids]
    expected_fold_count = len(expected_fold_ids)
    expected_fold_set = set(expected_fold_ids)
    expected_assignments = _expected_assignment_map(expected_fold_assignments)

    rows_by_fold_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    observed_fold_ids_in_order: list[str] = []
    blank_fold_rows = 0
    for row in rows:
        fold_id = _fold_id(row)
        if not fold_id:
            blank_fold_rows += 1
            continue
        rows_by_fold_id[fold_id].append(row)
        if fold_id not in observed_fold_ids_in_order:
            observed_fold_ids_in_order.append(fold_id)

    observed_unique_fold_ids = list(observed_fold_ids_in_order)
    observed_unique_fold_count = len(observed_unique_fold_ids)
    missing_fold_ids = [fold_id for fold_id in expected_fold_ids if fold_id not in rows_by_fold_id]
    unexpected_fold_ids = [fold_id for fold_id in observed_fold_ids_in_order if fold_id not in expected_fold_set]
    duplicate_fold_ids = [fold_id for fold_id, fold_rows in rows_by_fold_id.items() if len(fold_rows) > 1]

    fold_identity_mismatches: list[str] = []
    usable_fold_rows: list[Mapping[str, Any]] = []
    for fold_id in expected_fold_ids:
        fold_rows = rows_by_fold_id.get(fold_id, [])
        if len(fold_rows) != 1:
            continue
        row = fold_rows[0]
        if not _row_meets_expected_assignment(row, expected_assignment=expected_assignments.get(fold_id)):
            fold_identity_mismatches.append(fold_id)
            continue
        prediction_minutes = _coerce_float(row.get("prediction_minutes"))
        actual_minutes = _coerce_float(row.get("actual_minutes"))
        if prediction_minutes is None or actual_minutes is None or actual_minutes == 0.0:
            continue
        usable_fold_rows.append(row)

    fold_identity_gate_passed = not blank_fold_rows and not missing_fold_ids and not unexpected_fold_ids and not duplicate_fold_ids and not fold_identity_mismatches

    runner_apes: dict[str, list[float]] = defaultdict(list)
    runner_abs_errors: dict[str, list[float]] = defaultdict(list)
    runner_signed_errors: dict[str, list[float]] = defaultdict(list)
    for row in usable_fold_rows:
        runner = _runner_key(row)
        prediction_minutes = float(row["prediction_minutes"])
        actual_minutes = float(row["actual_minutes"])
        error = prediction_minutes - actual_minutes
        ape = abs(error) / actual_minutes * 100.0
        runner_apes[runner].append(ape)
        runner_abs_errors[runner].append(abs(error))
        runner_signed_errors[runner].append(error)

    runner_metrics = {
        runner: {
            "count": len(apes),
            "mdape_pct": standard_median(apes),
            "mae_minutes": mean(abs_errors) if abs_errors else None,
            "bias_minutes": mean(signed_errors) if signed_errors else None,
        }
        for runner, apes, abs_errors, signed_errors in (
            (runner, runner_apes[runner], runner_abs_errors[runner], runner_signed_errors[runner])
            for runner in sorted(runner_apes)
        )
    }

    runner_mdapes = [metric["mdape_pct"] for metric in runner_metrics.values() if metric["mdape_pct"] is not None]
    valid_errors = [float(row["prediction_minutes"]) - float(row["actual_minutes"]) for row in usable_fold_rows]
    valid_abs_errors = [abs(error) for error in valid_errors]
    valid_apes = [
        abs(float(row["prediction_minutes"]) - float(row["actual_minutes"])) / float(row["actual_minutes"]) * 100.0
        for row in usable_fold_rows
    ]

    prediction_count = len(usable_fold_rows)
    prediction_completeness = round(prediction_count / expected_fold_count, 6) if expected_fold_count else None
    completeness_gate_passed = fold_identity_gate_passed and prediction_count == expected_fold_count

    return {
        "expected_fold_count": expected_fold_count,
        "observed_unique_fold_count": observed_unique_fold_count,
        "expected_fold_ids": list(expected_fold_ids),
        "observed_unique_fold_ids": observed_unique_fold_ids,
        "missing_fold_ids": missing_fold_ids,
        "unexpected_fold_ids": unexpected_fold_ids,
        "duplicate_fold_ids": duplicate_fold_ids,
        "fold_identity_mismatches": fold_identity_mismatches,
        "fold_identity_gate_passed": fold_identity_gate_passed,
        "prediction_count": prediction_count,
        "prediction_completeness": prediction_completeness,
        "completeness_gate_passed": completeness_gate_passed,
        "runner_macro_mdape": mean(runner_mdapes) if runner_mdapes else None,
        "pooled_mdape": standard_median(valid_apes),
        "mae_minutes": mean(valid_abs_errors) if valid_abs_errors else None,
        "signed_bias_minutes": mean(valid_errors) if valid_errors else None,
        "coverage": {
            "optimistic": round(sum(1 for row in usable_fold_rows if _covered(row, "optimistic")) / expected_fold_count, 6)
            if expected_fold_count
            else None,
            "baseline": round(sum(1 for row in usable_fold_rows if _covered(row, "baseline")) / expected_fold_count, 6)
            if expected_fold_count
            else None,
            "conservative": round(sum(1 for row in usable_fold_rows if _covered(row, "conservative")) / expected_fold_count, 6)
            if expected_fold_count
            else None,
        },
        "runner_metrics": runner_metrics,
        "distance_buckets": _bucket_metrics(
            usable_fold_rows,
            bucket_fn=_distance_bucket,
            bucket_field="target_distance_km",
        ),
        "prior_history_buckets": _bucket_metrics(
            usable_fold_rows,
            bucket_fn=_history_bucket,
            bucket_field="prior_history_count",
        ),
    }


def _bucket_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    bucket_fn,
    bucket_field: str,
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        bucket = bucket_fn(row.get(bucket_field))
        grouped[bucket].append(row)

    result: dict[str, Any] = {}
    for bucket, bucket_rows in grouped.items():
        errors: list[float] = []
        apes: list[float] = []
        for row in bucket_rows:
            prediction_minutes = _coerce_float(row.get("prediction_minutes"))
            actual_minutes = _coerce_float(row.get("actual_minutes"))
            if prediction_minutes is None or actual_minutes is None or actual_minutes == 0.0:
                continue
            error = prediction_minutes - actual_minutes
            errors.append(error)
            apes.append(abs(error) / actual_minutes * 100.0)
        result[bucket] = {
            "count": len(bucket_rows),
            "valid_count": len(errors),
            "mdape_pct": standard_median(apes),
            "mae_minutes": mean(abs(error) for error in errors) if errors else None,
            "bias_minutes": mean(errors) if errors else None,
        }
    return result


def _fold_identity_input_passes(
    *,
    metrics: Mapping[str, Any],
    frozen_fold_ids: Sequence[str],
) -> tuple[bool, list[str], list[str], list[str]]:
    expected_fold_ids = [str(fold_id) for fold_id in frozen_fold_ids]
    expected_fold_set = set(expected_fold_ids)
    observed_fold_ids = [str(fold_id) for fold_id in metrics.get("observed_unique_fold_ids", [])]
    observed_fold_set = set(observed_fold_ids)
    missing = [fold_id for fold_id in expected_fold_ids if fold_id not in observed_fold_set]
    unexpected = [fold_id for fold_id in observed_fold_ids if fold_id not in expected_fold_set]
    duplicates = [str(fold_id) for fold_id in metrics.get("duplicate_fold_ids", [])]
    identity_passed = (
        bool(metrics.get("fold_identity_gate_passed"))
        and not missing
        and not unexpected
        and not duplicates
        and observed_fold_set == expected_fold_set
    )
    return identity_passed, missing, unexpected, duplicates


def _metrics_input_passes(
    metrics: Mapping[str, Any],
    *,
    frozen_fold_ids: Sequence[str],
) -> tuple[bool, bool, list[str], list[str], list[str]]:
    identity_passed, missing, unexpected, duplicates = _fold_identity_input_passes(
        metrics=metrics,
        frozen_fold_ids=frozen_fold_ids,
    )
    completeness_passed = bool(metrics.get("completeness_gate_passed"))
    leak_passed = bool(metrics.get("leak_checks_passed"))
    return identity_passed and completeness_passed and leak_passed, identity_passed, missing, unexpected, duplicates


def evaluate_validation_gate(
    *,
    full_metrics: Mapping[str, Any],
    distance_only_metrics: Mapping[str, Any],
    frozen_validation_fold_ids: Sequence[str],
    validation_runner_references: Sequence[str] = ("P-0004", "P-0008"),
) -> dict[str, Any]:
    full_input_passed, full_identity_passed, full_missing, full_unexpected, full_duplicates = _metrics_input_passes(
        full_metrics,
        frozen_fold_ids=frozen_validation_fold_ids,
    )
    distance_input_passed, distance_identity_passed, distance_missing, distance_unexpected, distance_duplicates = _metrics_input_passes(
        distance_only_metrics,
        frozen_fold_ids=frozen_validation_fold_ids,
    )
    full_fold_ids = list(full_metrics.get("observed_unique_fold_ids", []))
    distance_fold_ids = list(distance_only_metrics.get("observed_unique_fold_ids", []))
    expected_fold_ids = [str(fold_id) for fold_id in frozen_validation_fold_ids]

    input_gate_passed = (
        full_input_passed
        and distance_input_passed
        and set(full_fold_ids) == set(expected_fold_ids)
        and set(distance_fold_ids) == set(expected_fold_ids)
        and set(full_fold_ids) == set(distance_fold_ids)
    )
    if not input_gate_passed:
        return {
            "stage": "validation",
            "passed": False,
            "decision": "blocked_invalid_evaluation_input",
            "checks": [
                {"check": "full_validation_fold_identity", "passed": full_identity_passed},
                {"check": "distance_only_validation_fold_identity", "passed": distance_identity_passed},
                {"check": "full_validation_completeness_gate", "passed": bool(full_metrics.get("completeness_gate_passed"))},
                {"check": "distance_only_validation_completeness_gate", "passed": bool(distance_only_metrics.get("completeness_gate_passed"))},
                {"check": "full_validation_leak_checks", "passed": bool(full_metrics.get("leak_checks_passed"))},
                {"check": "distance_only_validation_leak_checks", "passed": bool(distance_only_metrics.get("leak_checks_passed"))},
                {"check": "full_fold_ids_match_frozen_validation", "passed": set(full_fold_ids) == set(expected_fold_ids)},
                {"check": "distance_only_fold_ids_match_frozen_validation", "passed": set(distance_fold_ids) == set(expected_fold_ids)},
                {"check": "full_and_distance_only_fold_sets_match", "passed": set(full_fold_ids) == set(distance_fold_ids)},
            ],
            "validation_runner_checks": [],
            "full_fold_ids": full_fold_ids,
            "distance_only_fold_ids": distance_fold_ids,
            "frozen_validation_fold_ids": expected_fold_ids,
            "input_gate_passed": False,
            "full_missing_fold_ids": full_missing,
            "full_unexpected_fold_ids": full_unexpected,
            "full_duplicate_fold_ids": full_duplicates,
            "distance_only_missing_fold_ids": distance_missing,
            "distance_only_unexpected_fold_ids": distance_unexpected,
            "distance_only_duplicate_fold_ids": distance_duplicates,
        }

    checks = []
    completeness_ok = full_metrics.get("prediction_count") == len(expected_fold_ids) and full_metrics.get("completeness_gate_passed") is True
    checks.append({"check": "prediction_completeness_9_of_9", "passed": completeness_ok})

    leak_checks_ok = bool(full_metrics.get("leak_checks_passed")) and bool(distance_only_metrics.get("leak_checks_passed"))
    checks.append({"check": "all_leak_checks_passed", "passed": leak_checks_ok})

    full_runner_macro = _coerce_float(full_metrics.get("runner_macro_mdape"))
    distance_runner_macro = _coerce_float(distance_only_metrics.get("runner_macro_mdape"))
    runner_macro_abs_improvement_ok = (
        full_runner_macro is not None and distance_runner_macro is not None and (distance_runner_macro - full_runner_macro) >= 1.0
    )
    checks.append({"check": "runner_macro_improves_by_1_point", "passed": runner_macro_abs_improvement_ok})

    runner_macro_rel_improvement_ok = (
        full_runner_macro is not None
        and distance_runner_macro is not None
        and distance_runner_macro > 0
        and ((distance_runner_macro - full_runner_macro) / distance_runner_macro) >= 0.05
    )
    checks.append({"check": "runner_macro_improves_by_5_percent", "passed": runner_macro_rel_improvement_ok})

    runner_metrics = full_metrics.get("runner_metrics", {})
    distance_runner_metrics = distance_only_metrics.get("runner_metrics", {})
    validation_runner_checks = []
    for runner_reference in validation_runner_references:
        full_runner = _coerce_float((runner_metrics.get(runner_reference) or {}).get("mdape_pct"))
        distance_runner = _coerce_float((distance_runner_metrics.get(runner_reference) or {}).get("mdape_pct"))
        runner_ok = full_runner is not None and distance_runner is not None and full_runner <= distance_runner
        validation_runner_checks.append({"runner_reference": runner_reference, "passed": runner_ok})
    checks.append({"check": "validation_runner_mdape_not_worse", "passed": all(item["passed"] for item in validation_runner_checks)})

    pooled_full = _coerce_float(full_metrics.get("pooled_mdape"))
    pooled_distance = _coerce_float(distance_only_metrics.get("pooled_mdape"))
    pooled_ok = pooled_full is not None and pooled_distance is not None and pooled_full <= pooled_distance
    checks.append({"check": "pooled_mdape_not_worse", "passed": pooled_ok})

    full_mae = _coerce_float(full_metrics.get("mae_minutes"))
    distance_mae = _coerce_float(distance_only_metrics.get("mae_minutes"))
    mae_ok = full_mae is not None and distance_mae is not None and full_mae <= distance_mae * 1.05
    checks.append({"check": "mae_within_105_percent", "passed": mae_ok})

    full_bias = _coerce_float(full_metrics.get("signed_bias_minutes"))
    distance_bias = _coerce_float(distance_only_metrics.get("signed_bias_minutes"))
    bias_ok = (
        full_bias is not None
        and distance_bias is not None
        and abs(full_bias) <= abs(distance_bias) + 10.0
    )
    checks.append({"check": "bias_within_allowed_range", "passed": bias_ok})

    full_conservative = _coerce_float((full_metrics.get("coverage") or {}).get("conservative"))
    distance_conservative = _coerce_float((distance_only_metrics.get("coverage") or {}).get("conservative"))
    coverage_ok = (
        full_conservative is not None
        and distance_conservative is not None
        and full_conservative >= distance_conservative - (1.0 / 9.0)
    )
    checks.append({"check": "conservative_coverage_within_one_fold", "passed": coverage_ok})

    passed = all(item["passed"] for item in checks)
    return {
        "stage": "validation",
        "passed": passed,
        "decision": "promote_full" if passed else "retain_distance_only",
        "checks": checks,
        "validation_runner_checks": validation_runner_checks,
        "full_fold_ids": full_fold_ids,
        "distance_only_fold_ids": distance_fold_ids,
        "frozen_validation_fold_ids": expected_fold_ids,
        "input_gate_passed": True,
    }


def evaluate_holdout_gate(
    *,
    metrics: Mapping[str, Any],
    holdout_unlocked: bool,
    holdout_finish_time_median_minutes: float | None,
    frozen_holdout_fold_ids: Sequence[str],
) -> dict[str, Any]:
    if not holdout_unlocked:
        return {
            "stage": "holdout",
            "passed": False,
            "decision": "blocked",
            "checks": [{"check": "holdout_unlocked", "passed": False}],
        }

    input_passed, identity_passed, missing, unexpected, duplicates = _metrics_input_passes(
        metrics,
        frozen_fold_ids=frozen_holdout_fold_ids,
    )
    observed_fold_ids = list(metrics.get("observed_unique_fold_ids", []))
    expected_fold_ids = [str(fold_id) for fold_id in frozen_holdout_fold_ids]
    if not input_passed or set(observed_fold_ids) != set(expected_fold_ids):
        return {
            "stage": "holdout",
            "passed": False,
            "decision": "blocked_invalid_evaluation_input",
            "checks": [
                {"check": "holdout_fold_identity", "passed": identity_passed},
                {"check": "holdout_fold_ids_match_frozen", "passed": set(observed_fold_ids) == set(expected_fold_ids)},
                {"check": "holdout_completeness_gate", "passed": bool(metrics.get("completeness_gate_passed"))},
                {"check": "holdout_leak_checks", "passed": bool(metrics.get("leak_checks_passed"))},
            ],
            "full_fold_ids": observed_fold_ids,
            "frozen_holdout_fold_ids": expected_fold_ids,
            "missing_fold_ids": missing,
            "unexpected_fold_ids": unexpected,
            "duplicate_fold_ids": duplicates,
            "input_gate_passed": False,
        }

    checks = []
    completeness_ok = metrics.get("prediction_count") == len(expected_fold_ids) and metrics.get("completeness_gate_passed") is True
    checks.append({"check": "prediction_completeness_10_of_10", "passed": completeness_ok})
    checks.append({"check": "all_leak_checks_passed", "passed": bool(metrics.get("leak_checks_passed"))})
    runner_macro = _coerce_float(metrics.get("runner_macro_mdape"))
    pooled = _coerce_float(metrics.get("pooled_mdape"))
    checks.append({"check": "runner_macro_mdape_le_20", "passed": runner_macro is not None and runner_macro <= 20.0})
    checks.append({"check": "pooled_mdape_le_20", "passed": pooled is not None and pooled <= 20.0})
    runner_metrics = metrics.get("runner_metrics", {})
    p2_ok = _coerce_float((runner_metrics.get("P-0002") or {}).get("mdape_pct")) is not None and _coerce_float((runner_metrics.get("P-0002") or {}).get("mdape_pct")) <= 25.0
    p6_ok = _coerce_float((runner_metrics.get("P-0006") or {}).get("mdape_pct")) is not None and _coerce_float((runner_metrics.get("P-0006") or {}).get("mdape_pct")) <= 25.0
    checks.append({"check": "p0002_mdape_le_25", "passed": p2_ok})
    checks.append({"check": "p0006_mdape_le_25", "passed": p6_ok})
    bias = _coerce_float(metrics.get("signed_bias_minutes"))
    if holdout_finish_time_median_minutes is None:
        bias_ok = False
    else:
        bias_ok = bias is not None and abs(bias) <= abs(holdout_finish_time_median_minutes) * 0.10
    checks.append({"check": "bias_within_ten_percent_of_median_time", "passed": bias_ok})
    passed = all(item["passed"] for item in checks)
    return {
        "stage": "holdout",
        "passed": passed,
        "decision": "accept_internal_point_prediction" if passed else "reject",
        "checks": checks,
        "frozen_holdout_fold_ids": expected_fold_ids,
        "input_gate_passed": True,
    }


def _sequence_identity_matches(current: Sequence[str] | None, frozen: Sequence[str] | None) -> bool:
    if current is None or frozen is None:
        return False
    current_values = [str(item).strip() for item in current]
    frozen_values = [str(item).strip() for item in frozen]
    if not current_values or not frozen_values:
        return False
    if any(not value for value in current_values) or any(not value for value in frozen_values):
        return False
    if len(current_values) != len(set(current_values)):
        return False
    if len(frozen_values) != len(set(frozen_values)):
        return False
    return set(current_values) == set(frozen_values)


def _text_identity_matches(current: str | None, frozen: str | None) -> bool:
    if current is None or frozen is None:
        return False
    current_text = str(current).strip()
    frozen_text = str(frozen).strip()
    return bool(current_text) and bool(frozen_text) and current_text == frozen_text


def can_execute_split(
    *,
    protocol_status: Mapping[str, Any],
    split_name: str,
    current_protocol_sha256: str | None = None,
    frozen_protocol_sha256: str | None = None,
    current_pool_manifest_sha256: str | None = None,
    frozen_pool_manifest_sha256: str | None = None,
    current_registry_sha256: str | None = None,
    frozen_registry_sha256: str | None = None,
    current_eligibility_report_sha256: str | None = None,
    frozen_eligibility_report_sha256: str | None = None,
    current_model_source_sha256s: Sequence[str] | None = None,
    frozen_model_source_sha256s: Sequence[str] | None = None,
    current_protocol_rules_sha256: str | None = None,
    frozen_protocol_rules_sha256: str | None = None,
    current_evaluator_source_sha256: str | None = None,
    frozen_evaluator_source_sha256: str | None = None,
    current_real_executor_source_sha256: str | None = None,
    frozen_real_executor_source_sha256: str | None = None,
    current_cli_source_sha256: str | None = None,
    frozen_cli_source_sha256: str | None = None,
    current_fold_ids: Sequence[str] | None = None,
    frozen_fold_ids: Sequence[str] | None = None,
    previous_stage_ready: bool | None = None,
    development_unlock_approved: bool | None = None,
    development_completed: bool | None = None,
    development_decision_frozen: bool | None = None,
    validation_unlock_approved: bool | None = None,
    validation_executed_once: bool | None = None,
    validation_completed: bool | None = None,
    unique_candidate_frozen: bool | None = None,
    holdout_unlock_approved: bool | None = None,
    holdout_executed_once: bool | None = None,
    holdout_completed: bool | None = None,
) -> bool:
    if str(protocol_status.get("evaluation_protocol_status") or "").lower() != "frozen":
        return False

    stage = {"development": "stage_d", "validation": "stage_v", "holdout": "stage_h"}.get(split_name)
    if stage is None:
        return False

    stage_allowed = bool((protocol_status.get("stage_boundaries") or {}).get(stage, {}).get("allowed"))
    if not stage_allowed:
        return False

    if not _text_identity_matches(current_protocol_sha256, frozen_protocol_sha256):
        return False
    if not _text_identity_matches(current_pool_manifest_sha256, frozen_pool_manifest_sha256):
        return False
    if not _text_identity_matches(current_registry_sha256, frozen_registry_sha256):
        return False
    if not _text_identity_matches(current_eligibility_report_sha256, frozen_eligibility_report_sha256):
        return False
    if not _text_identity_matches(current_protocol_rules_sha256, frozen_protocol_rules_sha256):
        return False
    if not _text_identity_matches(current_evaluator_source_sha256, frozen_evaluator_source_sha256):
        return False
    if not _text_identity_matches(current_real_executor_source_sha256, frozen_real_executor_source_sha256):
        return False
    if not _text_identity_matches(current_cli_source_sha256, frozen_cli_source_sha256):
        return False
    if not _sequence_identity_matches(current_model_source_sha256s, frozen_model_source_sha256s):
        return False
    if not _sequence_identity_matches(current_fold_ids, frozen_fold_ids):
        return False

    if split_name == "development":
        if development_unlock_approved is not True:
            return False
    elif split_name == "validation":
        if previous_stage_ready is not True:
            return False
        if development_completed is not True:
            return False
        if development_decision_frozen is not True:
            return False
        if validation_unlock_approved is not True:
            return False
        if validation_executed_once is not False:
            return False
    elif split_name == "holdout":
        if validation_completed is not True:
            return False
        if unique_candidate_frozen is not True:
            return False
        if holdout_unlock_approved is not True:
            return False
        if holdout_executed_once is not False:
            return False
    else:
        return False

    return True
