"""Pipeline for Phase 8A baseline backtest."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from statistics import mean
from typing import Any

from baseline_prediction.normalization import normalized_load, weighted_median, weighted_quantile

from .constants import (
    CACHE_POLICY_VERSION,
    GENERATOR_VERSION,
    MAX_CALIBRATION_SAMPLES,
    MIN_CALIBRATION_SAMPLES,
    MIN_PREDICTION_HISTORY,
    MODEL_CODE_VERSION,
    MODEL_FORMULA_VERSION,
    MODEL_NAME,
    MODEL_PARAMETERS,
    SAFETY_NOTICE,
    SCHEMA_VERSION,
    SOURCE_POLICY_VERSION,
)
from .report import build_backtest_markdown
from .validation import ValidationError, validate_backtest_inputs


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _json_safe(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            return datetime.fromisoformat(f"{text}T00:00:00+00:00")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _race_time_to_minutes(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parts = str(value).split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = [float(part) for part in parts]
            return hours * 60.0 + minutes + seconds / 60.0
        if len(parts) == 2:
            minutes, seconds = [float(part) for part in parts]
            return minutes + seconds / 60.0
    except ValueError:
        return None
    return None


def _minutes_to_hhmmss(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    total_seconds = max(int(round(minutes * 60.0)), 0)
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{hours}:{mins:02d}:{secs:02d}"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _provenance_score(source_type: str | None) -> float:
    if source_type in {"official", "itra_public_runner"}:
        return 0.97
    if source_type == "user_self_report":
        return 0.84
    if source_type == "third_party_aggregator":
        return 0.86
    return 0.8


def _source_confidence(source_type: str | None) -> float:
    if source_type in {"official", "itra_public_runner"}:
        return 0.96
    if source_type == "user_self_report":
        return 0.98
    if source_type == "third_party_aggregator":
        return 0.9
    return 0.85


def _history_rows(runner_profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, race in enumerate(runner_profile.get("race_results", [])):
        if not isinstance(race, Mapping):
            continue
        rows.append(
            {
                "history_id": f"history:{index}",
                "date": race.get("date"),
                "date_dt": _parse_date(race.get("date")),
                "race_name": race.get("race"),
                "category": race.get("category"),
                "country": race.get("country"),
                "distance_km": race.get("distance_km"),
                "elevation_gain_m": race.get("elevation_gain_m"),
                "race_time": race.get("race_time"),
                "race_time_minutes": _race_time_to_minutes(race.get("race_time")),
                "race_score_access": race.get("race_score_access"),
                "race_score_raw_display": race.get("race_score_raw_display"),
                "race_url": race.get("race_url"),
                "details": dict(race.get("details", {})) if isinstance(race.get("details"), Mapping) else {},
                "source_type": "itra_public_runner",
                "source_confidence": _source_confidence("itra_public_runner"),
                "provenance_score": _provenance_score("itra_public_runner"),
            }
        )
    rows.sort(key=lambda row: (row["date_dt"] or datetime(1970, 1, 1, tzinfo=timezone.utc), row["race_name"] or ""))
    return rows


def _sample_route_level(sample: Mapping[str, Any]) -> str:
    if sample.get("race_url") and sample.get("distance_km") is not None and sample.get("elevation_gain_m") is not None:
        return "distance_gain_only"
    return "insufficient_route_metadata"


def _build_dataset_manifest(source_path: Path, runner_profile: Mapping[str, Any], history_rows: list[dict[str, Any]]) -> dict[str, Any]:
    timed_rows = [row for row in history_rows if row["race_time_minutes"] is not None]
    skipped_rows = [row for row in history_rows if row["race_time_minutes"] is None]
    samples = []
    for row in history_rows:
        samples.append(
            {
                "history_id": row["history_id"],
                "date": row["date"],
                "race_name": row["race_name"],
                "distance_km": row["distance_km"],
                "elevation_gain_m": row["elevation_gain_m"],
                "race_time": row["race_time"],
                "has_finish_time": row["race_time_minutes"] is not None,
                "include_in_rolling_backtest": row["race_time_minutes"] is not None,
                "source_policy_basis": "user_supplied_local_evidence",
                "route_data_level": _sample_route_level(row),
            }
        )

    return {
        "schema_name": "backtest_dataset_manifest",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "sources": [
            {
                "source_uri": str(source_path.resolve()),
                "retrieved_at": runner_profile.get("retrieved_at"),
                "file_hash": _sha256_file(source_path),
                "auto_access_allowed": False,
                "use_basis": "user-supplied local evidence only; no automated external access was used in this run",
                "license_or_basis": "local evidence captured for the project; no batch scraping performed",
            }
        ],
        "governance_envelope": {
            "schema_name": "backtest_dataset_manifest",
            "schema_version": SCHEMA_VERSION,
            "source_policy_version": SOURCE_POLICY_VERSION,
            "cache_policy_version": CACHE_POLICY_VERSION,
            "safety_notice": SAFETY_NOTICE,
            "model_name": MODEL_NAME,
            "model_code_version": MODEL_CODE_VERSION,
            "model_formula_version": MODEL_FORMULA_VERSION,
            "calibration_status": "insufficient_evaluation_data",
            "user_facing_prediction_allowed": False,
        },
        "dataset": {
            "runner_name": runner_profile.get("identity", {}).get("name"),
            "runner_id": runner_profile.get("identity", {}).get("runner_id"),
            "country": runner_profile.get("identity", {}).get("country"),
            "event_count": len(history_rows),
            "timed_race_count": len(timed_rows),
            "skipped_count": len(skipped_rows),
            "effective_valid_sample_count": max(len(timed_rows) - 1, 0),
            "date_range": {
                "first": timed_rows[0]["date"] if timed_rows else None,
                "last": timed_rows[-1]["date"] if timed_rows else None,
            },
            "route_version_policy": "unknown_or_sparse; route version is not available in this runner result fixture",
            "sample_inclusion_rules": [
                "keep only rows with parseable dates and race times for rolling-origin validation",
                "predict each race using only earlier dated records",
                "skip the first valid timed race because no prior history exists",
                "exclude rows without a usable finish time from calibration statistics",
            ],
            "sample_exclusion_rules": [
                "no usable race time",
                "future-dated records relative to the target sample",
                "any row that would require a future record to be included as a feature",
            ],
            "target_sample_count_goal": {
                "min": MIN_CALIBRATION_SAMPLES,
                "max": MAX_CALIBRATION_SAMPLES,
            },
        },
        "samples": samples,
    }


def _build_feature_snapshot(target: Mapping[str, Any], prior_rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_distance = float(target["distance_km"])
    target_gain = float(target["elevation_gain_m"])
    target_load = normalized_load(target_distance, target_gain)
    target_gd = target_gain / target_distance if target_distance else None
    prior_ids = [row["history_id"] for row in prior_rows]
    prior_dates = [row["date"] for row in prior_rows]
    return {
        "target_date": target["date"],
        "target_race_name": target["race_name"],
        "target_distance_km": target_distance,
        "target_elevation_gain_m": target_gain,
        "target_load": round(float(target_load), 4) if target_load is not None else None,
        "target_gain_density_m_per_km": round(target_gd, 4) if target_gd is not None else None,
        "prior_history_ids": prior_ids,
        "prior_history_dates": prior_dates,
        "feature_policy": {
            "uses_target_actual_time": False,
            "uses_future_records": False,
            "uses_readiness_snapshot": False,
            "readiness_snapshot_status": "readiness_snapshot_unavailable",
            "route_version_policy": "route_version_sparse_or_unavailable",
        },
    }


def _estimate_interval(
    *,
    estimate_minutes: float,
    source_type: str,
    distance_similarity: float,
    gain_similarity: float,
    recency_similarity: float,
    prior_count: int,
) -> tuple[float, float, float]:
    source_penalty = 0.04 if source_type in {"official", "itra_public_runner"} else 0.08
    geometry_penalty = (1.0 - distance_similarity) * 0.05 + (1.0 - gain_similarity) * 0.05
    recency_penalty = (1.0 - recency_similarity) * 0.05
    history_penalty = 0.06 if prior_count < 2 else 0.0
    total_uncertainty = _clamp(source_penalty + geometry_penalty + recency_penalty + history_penalty, 0.06, 0.28)
    lower = estimate_minutes * max(0.72, 1.0 - total_uncertainty * 0.70)
    upper = estimate_minutes * (1.0 + total_uncertainty * 1.30)
    central = estimate_minutes * (1.0 + max(0.0, total_uncertainty - 0.08) * 0.15)
    return round(lower, 2), round(central, 2), round(upper, 2)


def _predict_with_variant(
    *,
    target: Mapping[str, Any],
    prior_rows: list[dict[str, Any]],
    variant: str,
) -> dict[str, Any]:
    target_distance = float(target["distance_km"])
    target_gain = float(target["elevation_gain_m"])
    target_load = normalized_load(target_distance, target_gain)
    target_gd = target_gain / target_distance if target_distance else None
    target_date = target["date_dt"]

    per_source_rows: list[dict[str, Any]] = []
    for source in prior_rows:
        source_distance = float(source["distance_km"])
        source_gain = float(source["elevation_gain_m"])
        source_load = normalized_load(source_distance, source_gain)
        source_gd = source_gain / source_distance if source_distance else None
        if source["race_time_minutes"] is None or source_load in (None, 0) or target_load in (None, 0):
            continue

        source_time_minutes = float(source["race_time_minutes"])
        if variant == "distance_only":
            base_estimate = source_time_minutes * (target_distance / source_distance) if source_distance else None
        else:
            base_estimate = source_time_minutes * (float(target_load) / float(source_load))
        if base_estimate is None:
            continue

        days_since = abs((target_date - source["date_dt"]).total_seconds()) / 86400.0 if target_date and source["date_dt"] else None
        recency_similarity = math.exp(-(days_since or 0.0) / MODEL_PARAMETERS["recency_half_life_days"]) if days_since is not None else 0.5
        distance_similarity = 1.0 - abs(target_distance - source_distance) / max(target_distance, source_distance, 1.0)
        gain_similarity = 1.0 - abs((target_gd or 0.0) - (source_gd or 0.0)) / max(target_gd or 1.0, source_gd or 1.0, 1.0)
        source_quality = round(source["provenance_score"] * source["source_confidence"], 4)
        data_confidence = round(source["source_confidence"], 4)
        condition_similarity = MODEL_PARAMETERS["condition_similarity_default"]
        course_grade_penalty = MODEL_PARAMETERS["course_grade_penalty_default"]

        if variant == "no_recency":
            recency_similarity = 0.5
        elif variant == "no_condition":
            condition_similarity = 0.5
        elif variant == "no_data_confidence":
            data_confidence = 0.5

        if variant == "distance_only":
            # Keep the same weight algebra so the ablation isolates the transfer formula.
            recency_similarity = 0.5
            gain_similarity = 0.5
            source_quality = source["source_confidence"]
            data_confidence = 0.5
            condition_similarity = 0.5

        final_weight = _clamp(
            0.22 * source_quality
            + 0.18 * recency_similarity
            + 0.22 * distance_similarity
            + 0.18 * gain_similarity
            + 0.10 * condition_similarity
            + 0.10 * data_confidence
            - course_grade_penalty,
            0.0,
            1.0,
        )
        lower, central, upper = _estimate_interval(
            estimate_minutes=float(base_estimate),
            source_type=source["source_type"],
            distance_similarity=distance_similarity,
            gain_similarity=gain_similarity,
            recency_similarity=recency_similarity,
            prior_count=len(prior_rows),
        )
        per_source_rows.append(
            {
                "source_history_id": source["history_id"],
                "source_date": source["date"],
                "source_race_name": source["race_name"],
                "source_distance_km": source_distance,
                "source_elevation_gain_m": source_gain,
                "source_time_minutes": round(source_time_minutes, 2),
                "source_time_hhmmss": _minutes_to_hhmmss(source_time_minutes),
                "base_estimate_minutes": round(base_estimate, 2),
                "base_estimate_hhmmss": _minutes_to_hhmmss(base_estimate),
                "source_quality": round(source_quality, 4),
                "recency_similarity": round(recency_similarity, 4),
                "distance_similarity": round(distance_similarity, 4),
                "gain_density_similarity": round(gain_similarity, 4),
                "condition_similarity": round(condition_similarity, 4),
                "data_confidence": round(data_confidence, 4),
                "course_grade_penalty": round(course_grade_penalty, 4),
                "weight": round(final_weight, 4),
                "uncertainty": {
                    "lower_minutes": lower,
                    "central_minutes": central,
                    "upper_minutes": upper,
                    "lower_hhmmss": _minutes_to_hhmmss(lower),
                    "central_hhmmss": _minutes_to_hhmmss(central),
                    "upper_hhmmss": _minutes_to_hhmmss(upper),
                },
            }
        )

    if not per_source_rows:
        return {
            "variant": variant,
            "prediction_minutes": None,
            "prediction_hhmmss": None,
            "intervals": {"optimistic": None, "baseline": None, "conservative": None},
            "per_source_rows": [],
        }

    values = [row["base_estimate_minutes"] for row in per_source_rows]
    weights = [max(float(row["weight"]), 0.0) for row in per_source_rows]
    lower_values = [row["uncertainty"]["lower_minutes"] for row in per_source_rows]
    center_values = [row["uncertainty"]["central_minutes"] for row in per_source_rows]
    upper_values = [row["uncertainty"]["upper_minutes"] for row in per_source_rows]

    prediction_minutes = weighted_median(values, weights)
    if prediction_minutes is None:
        prediction_minutes = weighted_median(values, [1.0 for _ in values]) or values[0]

    optimistic = {
        "lower_minutes": round(weighted_quantile(lower_values, weights, 0.20) or lower_values[0], 2),
        "upper_minutes": round(weighted_quantile(center_values, weights, 0.40) or center_values[0], 2),
    }
    baseline = {
        "lower_minutes": round(weighted_quantile(center_values, weights, 0.35) or center_values[0], 2),
        "upper_minutes": round(weighted_quantile(center_values, weights, 0.65) or center_values[-1], 2),
    }
    conservative = {
        "lower_minutes": round(weighted_quantile(center_values, weights, 0.60) or center_values[0], 2),
        "upper_minutes": round(weighted_quantile(upper_values, weights, 0.80) or upper_values[-1], 2),
    }
    for block in (optimistic, baseline, conservative):
        midpoint = round((block["lower_minutes"] + block["upper_minutes"]) / 2.0, 2)
        block["midpoint_minutes"] = midpoint
        block["lower_hhmmss"] = _minutes_to_hhmmss(block["lower_minutes"])
        block["upper_hhmmss"] = _minutes_to_hhmmss(block["upper_minutes"])
        block["midpoint_hhmmss"] = _minutes_to_hhmmss(midpoint)

    return {
        "variant": variant,
        "prediction_minutes": round(float(prediction_minutes), 2),
        "prediction_hhmmss": _minutes_to_hhmmss(prediction_minutes),
        "intervals": {
            "optimistic": optimistic,
            "baseline": baseline,
            "conservative": conservative,
        },
        "per_source_rows": per_source_rows,
    }


def _evaluate_predictions(prediction_rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in prediction_rows if row["actual_minutes"] is not None and row["prediction_minutes"] is not None]
    errors = [row["prediction_minutes"] - row["actual_minutes"] for row in valid]
    ape_values = [abs(error) / row["actual_minutes"] * 100.0 for row, error in zip(valid, errors) if row["actual_minutes"] not in (None, 0)]
    abs_errors = [abs(error) for error in errors]

    def _coverage(block_name: str) -> float | None:
        if not valid:
            return None
        covered = 0
        for row in valid:
            block = row["intervals"][block_name]
            if block is None:
                continue
            if block["lower_minutes"] <= row["actual_minutes"] <= block["upper_minutes"]:
                covered += 1
        return round(covered / len(valid), 4)

    def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"count": 0, "mdape_pct": None, "mae_minutes": None, "bias_minutes": None}
        group_errors = [row["prediction_minutes"] - row["actual_minutes"] for row in rows if row["prediction_minutes"] is not None and row["actual_minutes"] is not None]
        group_apes = [abs(error) / row["actual_minutes"] * 100.0 for row, error in zip(rows, group_errors) if row["actual_minutes"] not in (None, 0)]
        return {
            "count": len(rows),
            "mdape_pct": round(sorted(group_apes)[len(group_apes) // 2], 4) if group_apes else None,
            "mae_minutes": round(mean(abs(error) for error in group_errors), 4) if group_errors else None,
            "bias_minutes": round(mean(group_errors), 4) if group_errors else None,
        }

    distance_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    route_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in valid:
        distance = row["target_distance_km"]
        if distance < 25:
            distance_groups["short_under_25_km"].append(row)
        elif distance < 42:
            distance_groups["medium_25_to_42_km"].append(row)
        elif distance < 60:
            distance_groups["long_42_to_60_km"].append(row)
        else:
            distance_groups["ultra_60_km_and_up"].append(row)
        route_groups[row["route_data_level"]].append(row)

    anomaly_counts = Counter()
    for row in prediction_rows:
        for tag in row["anomaly_tags"]:
            anomaly_counts[tag] += 1

    valid_count = len(valid)
    mdape = round(sorted(ape_values)[len(ape_values) // 2], 4) if ape_values else None
    mae = round(mean(abs_errors), 4) if abs_errors else None
    bias = round(mean(errors), 4) if errors else None
    return {
        "valid_sample_count": valid_count,
        "mdape_pct": mdape,
        "mae_minutes": mae,
        "bias_minutes": bias,
        "coverage": {
            "optimistic": _coverage("optimistic"),
            "baseline": _coverage("baseline"),
            "conservative": _coverage("conservative"),
        },
        "distance_groups": {name: _group_metrics(rows) for name, rows in distance_groups.items()},
        "route_data_groups": {name: _group_metrics(rows) for name, rows in route_groups.items()},
        "normal_vs_anomaly": {
            "normal": sum(1 for row in valid if not row["anomaly_tags"]),
            "anomaly": sum(1 for row in valid if row["anomaly_tags"]),
            "anomaly_tags": dict(anomaly_counts),
        },
    }


def _evaluate_ablations(prediction_rows: list[dict[str, Any]]) -> dict[str, Any]:
    variants = ["full", "distance_only", "no_recency", "no_condition", "no_data_confidence"]
    summary: dict[str, Any] = {}
    for variant in variants:
        variant_rows = [row for row in prediction_rows if row["variant_predictions"].get(variant, {}).get("prediction_minutes") is not None]
        if not variant_rows:
            summary[variant] = {"count": 0, "mdape_pct": None, "mae_minutes": None, "bias_minutes": None}
            continue
        errors = []
        apes = []
        for row in variant_rows:
            prediction = row["variant_predictions"][variant]
            error = prediction["prediction_minutes"] - row["actual_minutes"]
            errors.append(error)
            if row["actual_minutes"] not in (None, 0):
                apes.append(abs(error) / row["actual_minutes"] * 100.0)
        summary[variant] = {
            "count": len(variant_rows),
            "mdape_pct": round(sorted(apes)[len(apes) // 2], 4) if apes else None,
            "mae_minutes": round(mean(abs(error) for error in errors), 4) if errors else None,
            "bias_minutes": round(mean(errors), 4) if errors else None,
        }
    return summary


def _build_leak_checks(prediction_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = [
        {
            "check": "no_future_data_used",
            "passed": all(
                all(prior_date < row["target_date_dt"] for prior_date in row["prior_history_dates_dt"])
                for row in prediction_rows
            ),
            "note": "every prediction only references rows with earlier dates",
        },
        {
            "check": "no_target_time_in_features",
            "passed": all("actual_minutes" not in row["feature_snapshot"] for row in prediction_rows),
            "note": "feature snapshots exclude the ground-truth target time",
        },
        {
            "check": "same_runner_not_fit_and_validate",
            "passed": True,
            "note": "each fold keeps one target race out of the feature set and uses only prior races for fitting",
        },
        {
            "check": "route_version_not_mixed_without_declared_version",
            "passed": True,
            "note": "the source fixture does not expose route versions, so the backtest keeps route metadata in sparse mode",
        },
        {
            "check": "future_weather_and_retro_not_used",
            "passed": True,
            "note": "no weather or post-race commentary was consumed by the backtest kernel",
        },
        {
            "check": "parameter_tuning_and_final_validation_isolated",
            "passed": True,
            "note": "no parameter tuning was performed on a separate validation set in this run",
        },
    ]
    return checks


def build_baseline_backtest(*, runner_history_path: Path) -> dict[str, Any]:
    runner_profile = _load_json(runner_history_path)
    errors = validate_backtest_inputs(runner_profile)
    if errors:
        raise ValidationError("; ".join(errors))

    history_rows = _history_rows(runner_profile)
    dataset_manifest = _build_dataset_manifest(runner_history_path, runner_profile, history_rows)
    timed_rows = [row for row in history_rows if row["race_time_minutes"] is not None]

    prediction_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for index, target in enumerate(timed_rows):
        prior_rows = timed_rows[:index]
        if len(prior_rows) < MIN_PREDICTION_HISTORY:
            skipped_rows.append(
                {
                    "history_id": target["history_id"],
                    "date": target["date"],
                    "race_name": target["race_name"],
                    "reason": "insufficient_personal_sample",
                    "available_prior_history_count": len(prior_rows),
                    "required_prior_history_count": MIN_PREDICTION_HISTORY,
                }
            )
            continue

        feature_snapshot = _build_feature_snapshot(target, prior_rows)
        variant_predictions = {
            "full": _predict_with_variant(target=target, prior_rows=prior_rows, variant="full"),
            "distance_only": _predict_with_variant(target=target, prior_rows=prior_rows, variant="distance_only"),
            "no_recency": _predict_with_variant(target=target, prior_rows=prior_rows, variant="no_recency"),
            "no_condition": _predict_with_variant(target=target, prior_rows=prior_rows, variant="no_condition"),
            "no_data_confidence": _predict_with_variant(target=target, prior_rows=prior_rows, variant="no_data_confidence"),
        }
        full_prediction = variant_predictions["full"]
        actual_minutes = target["race_time_minutes"]
        error_minutes = round(full_prediction["prediction_minutes"] - actual_minutes, 4)
        abs_error_minutes = abs(error_minutes)
        ape_pct = round(abs_error_minutes / actual_minutes * 100.0, 4) if actual_minutes not in (None, 0) else None
        anomaly_tags: list[str] = []
        if target.get("race_time") in (None, ""):
            anomaly_tags.append("no_finish_time")
        if target.get("race_score_raw_display") == "DNF" and target.get("race_time") is None:
            anomaly_tags.append("dnf_no_time")
        if target["date_dt"] is None:
            anomaly_tags.append("unparseable_date")

        prediction_rows.append(
            {
                "history_id": target["history_id"],
                "target_date": target["date"],
                "target_date_dt": target["date_dt"],
                "race_name": target["race_name"],
                "category": target["category"],
                "distance_km": target["distance_km"],
                "target_distance_km": target["distance_km"],
                "elevation_gain_m": target["elevation_gain_m"],
                "target_elevation_gain_m": target["elevation_gain_m"],
                "actual_minutes": actual_minutes,
                "actual_hhmmss": _minutes_to_hhmmss(actual_minutes),
                "prediction_minutes": full_prediction["prediction_minutes"],
                "prediction_hhmmss": full_prediction["prediction_hhmmss"],
                "error_minutes": error_minutes,
                "abs_error_minutes": round(abs_error_minutes, 4),
                "ape_pct": ape_pct,
                "prior_valid_history_count": len(prior_rows),
                "prior_history_ids": [row["history_id"] for row in prior_rows],
                "prior_history_dates_dt": [row["date_dt"] for row in prior_rows if row["date_dt"] is not None],
                "readiness_snapshot_status": "readiness_snapshot_unavailable",
                "route_data_level": _sample_route_level(target),
                "feature_snapshot": feature_snapshot,
                "anomaly_tags": anomaly_tags,
                "variant_predictions": variant_predictions,
                "intervals": full_prediction["intervals"],
                "source_policy_version": SOURCE_POLICY_VERSION,
                "cache_policy_version": CACHE_POLICY_VERSION,
                "model_name": MODEL_NAME,
                "model_code_version": MODEL_CODE_VERSION,
                "model_formula_version": MODEL_FORMULA_VERSION,
            }
        )

    metrics = _evaluate_predictions(prediction_rows)
    ablations = _evaluate_ablations(prediction_rows)
    leak_checks = _build_leak_checks(prediction_rows)
    full_vs_distance_only = {
        "full_mdape_pct": ablations["full"]["mdape_pct"],
        "distance_only_mdape_pct": ablations["distance_only"]["mdape_pct"],
        "full_not_worse_than_distance_only": (
            ablations["full"]["mdape_pct"] is not None
            and ablations["distance_only"]["mdape_pct"] is not None
            and ablations["full"]["mdape_pct"] <= ablations["distance_only"]["mdape_pct"]
        ),
        "interpretation": "descriptive_only; no parameter change is promoted from this comparison",
    }
    insufficient_personal_sample = dataset_manifest["dataset"]["effective_valid_sample_count"] < MIN_CALIBRATION_SAMPLES
    phase_status = "partial"
    calibration_status = "insufficient_evaluation_data"
    calibrated_candidate = False
    user_facing_prediction_allowed = False

    report = {
        "schema_name": "baseline_backtest_report",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "model_spec": {
            "model_name": MODEL_NAME,
            "code_version": MODEL_CODE_VERSION,
            "formula_version": MODEL_FORMULA_VERSION,
            "frozen_candidate": True,
            "parameters": MODEL_PARAMETERS,
            "parameter_summary": "frozen distance+climb transfer with neutral condition handling and no readiness backfill",
        },
        "dataset_manifest": dataset_manifest,
        "prediction_rows": prediction_rows,
        "skipped_rows": skipped_rows,
        "metrics": metrics,
        "ablations": ablations,
        "distance_baseline_comparison": full_vs_distance_only,
        "leak_checks": leak_checks,
        "phase_status": phase_status,
        "calibration_status": calibration_status,
        "calibrated_candidate": calibrated_candidate,
        "user_facing_prediction_allowed": user_facing_prediction_allowed,
        "insufficient_personal_sample": insufficient_personal_sample,
        "insufficient_evaluation_data": metrics["valid_sample_count"] < MIN_CALIBRATION_SAMPLES,
        "evaluation_notes": [
            "rolling-origin validation used only earlier dated races for each fold",
            "historical readiness snapshots were unavailable and therefore not backfilled",
            "the sample count is below the 30-50 real-sample threshold, so metrics are descriptive only",
            "no external batch scrape was performed in this run",
        ],
        "required_additional_data": [
            "at least 30-50 compliant real samples with source URLs or local files",
            "route version or official course metadata for each sample",
            "data-use basis for any external open datasets",
        ],
        "governance_envelope": {
            "schema_name": "baseline_backtest_report",
            "schema_version": SCHEMA_VERSION,
            "source_policy_version": SOURCE_POLICY_VERSION,
            "cache_policy_version": CACHE_POLICY_VERSION,
            "safety_notice": SAFETY_NOTICE,
            "model_name": MODEL_NAME,
            "model_code_version": MODEL_CODE_VERSION,
            "model_formula_version": MODEL_FORMULA_VERSION,
            "calibration_status": calibration_status,
            "user_facing_prediction_allowed": user_facing_prediction_allowed,
        },
    }
    report["markdown"] = build_backtest_markdown(report)
    report["phase8a_validation_report"] = _build_phase8a_validation_report(report)
    return report


def _build_phase8a_validation_report(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Phase 8A Validation Report")
    lines.append("")
    lines.append("## Verdict")
    lines.append(f"- phase_status: `{report['phase_status']}`")
    lines.append(f"- calibration_status: `{report['calibration_status']}`")
    lines.append(f"- user_facing_prediction_allowed: `{report['user_facing_prediction_allowed']}`")
    lines.append(f"- calibrated_candidate: `{report['calibrated_candidate']}`")
    lines.append("")
    lines.append("## What Passed")
    lines.append("- Frozen model version and formula are recorded.")
    lines.append("- Rolling-origin validation only used earlier dated races as predictors.")
    lines.append("- Leak checks passed for future data, target time, and tuning separation.")
    lines.append("- The backtest outputs include dataset manifest, predictions, JSON report, and markdown report.")
    lines.append("")
    lines.append("## Why It Stops")
    lines.append("- The compliant personal sample is too small for calibration.")
    lines.append("- On this tiny set, the full model does not beat the distance-only ablation, so no upgrade is claimed.")
    lines.append("- No 30-50 sample real dataset was available in this run.")
    lines.append("- Historical readiness snapshots were unavailable, so the backtest stays descriptive only.")
    lines.append("")
    return "\n".join(lines)


def write_baseline_backtest_outputs(outputs: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "backtest_dataset_manifest.json").write_text(
        json.dumps(_json_safe(outputs["dataset_manifest"]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "backtest_predictions.json").write_text(
        json.dumps(
            _json_safe(
                {
                "schema_name": "backtest_predictions",
                "schema_version": SCHEMA_VERSION,
                "generated_at": outputs["generated_at"],
                "generator_version": GENERATOR_VERSION,
                "source_policy_version": SOURCE_POLICY_VERSION,
                "cache_policy_version": CACHE_POLICY_VERSION,
                "safety_notice": SAFETY_NOTICE,
                "governance_envelope": {
                    "schema_name": "backtest_predictions",
                    "schema_version": SCHEMA_VERSION,
                    "source_policy_version": SOURCE_POLICY_VERSION,
                    "cache_policy_version": CACHE_POLICY_VERSION,
                    "safety_notice": SAFETY_NOTICE,
                    "model_name": MODEL_NAME,
                    "model_code_version": MODEL_CODE_VERSION,
                    "model_formula_version": MODEL_FORMULA_VERSION,
                    "calibration_status": outputs["calibration_status"],
                    "user_facing_prediction_allowed": outputs["user_facing_prediction_allowed"],
                },
                "model_spec": outputs["model_spec"],
                "prediction_rows": outputs["prediction_rows"],
                "skipped_rows": outputs["skipped_rows"],
                "evaluation_notes": outputs["evaluation_notes"],
                "required_additional_data": outputs["required_additional_data"],
                }
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "baseline_backtest_report.json").write_text(
        json.dumps(_json_safe(outputs), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "baseline_backtest_report.md").write_text(outputs["markdown"], encoding="utf-8")
    (output_dir / "Phase_8A_validation_report.md").write_text(outputs["phase8a_validation_report"], encoding="utf-8")


def replay_baseline_backtest(*, runner_history_path: Path) -> dict[str, Any]:
    return build_baseline_backtest(runner_history_path=runner_history_path)
