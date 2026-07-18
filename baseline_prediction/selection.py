"""Historical race selection for the Phase 7A baseline."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import math
import re
from typing import Any


SOURCE_QUALITY_VERSION = "phase7a.1-source-quality-v1"
RECENCY_VERSION = "phase7a.1-recency-v1"
DISTANCE_VERSION = "phase7a.1-distance-v1"
GAIN_DENSITY_VERSION = "phase7a.1-gain-density-v1"
CONDITION_VERSION = "phase7a.1-condition-v1"
COURSE_PENALTY_VERSION = "phase7a.1-course-penalty-v1"
FINAL_WEIGHT_VERSION = "phase7a.1-final-weight-v1"
CLUSTER_VERSION = "phase7a.1-cluster-v1"

_WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _race_time_to_minutes(race_time: Any) -> float | None:
    if not race_time:
        return None
    parts = str(race_time).split(":")
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _days_between(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return abs((later - earlier).total_seconds()) / 86400.0


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _token_set(value: Any) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(str(value or ""))}


def _name_similarity(left: Any, right: Any) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    if union <= 0:
        return 0.0
    return round(overlap / union, 4)


def _scale_similarity(delta: float | None, scale: float, *, floor: float = 0.0) -> float:
    if delta is None or scale <= 0:
        return floor
    value = 1.0 - min(abs(delta) / scale, 1.0)
    return round(max(floor, value), 4)


def _distance_similarity(a: float | None, b: float | None) -> float:
    if a is None or b is None:
        return 0.0
    return _scale_similarity(abs(a - b), max(max(a, b), 1.0))


def _gain_density(distance_km: float | None, elevation_gain_m: float | None) -> float | None:
    if distance_km in (None, 0) or elevation_gain_m is None:
        return None
    return round(float(elevation_gain_m) / float(distance_km), 4)


def _gain_density_similarity(
    left_distance_km: float | None,
    left_gain_m: float | None,
    right_distance_km: float | None,
    right_gain_m: float | None,
) -> float:
    left = _gain_density(left_distance_km, left_gain_m)
    right = _gain_density(right_distance_km, right_gain_m)
    if left is None or right is None:
        return 0.0
    return _scale_similarity(abs(left - right), max(max(left, right), 1.0))


def _readiness_note(current_readiness: Mapping[str, Any]) -> str:
    assessment = current_readiness.get("assessment", {})
    band = assessment.get("readiness_band", {})
    planning_permission = assessment.get("planning_permission")
    return (
        f"readiness_band={band.get('label')} is an internal heuristic, "
        f"while planning_permission={planning_permission} is the safety cap."
    )


def _safety_notice(runner_profile: Mapping[str, Any]) -> dict[str, Any]:
    return runner_profile.get("safety_notice") or {
        "version": "1.0.0",
        "medical_advice": False,
        "replaces_race_rules": False,
        "message": "This tool does not replace race rules, on-site safety, or professional medical judgment.",
    }


def _source_meta_from_evidence(
    *,
    parent_evidence: list[Mapping[str, Any]] | list[Any],
    source_type: str | None,
    default_uri: str,
    default_fingerprint: str | None,
    default_captured_at: str | None,
    default_confidence: float | None,
) -> dict[str, Any]:
    source_uri = default_uri
    source_fingerprint = default_fingerprint
    captured_at = default_captured_at
    confidence = default_confidence
    missing_reason: list[str] = []
    if not source_uri:
        missing_reason.append("source_uri_missing")
    if not source_fingerprint:
        missing_reason.append("source_fingerprint_missing")
    if not captured_at:
        missing_reason.append("captured_at_missing")
    if confidence is None:
        missing_reason.append("confidence_missing")
    return {
        "source_type": source_type,
        "source_uri": source_uri,
        "source_fingerprint": source_fingerprint,
        "captured_at": captured_at,
        "confidence": confidence,
        "missing_reason": missing_reason or None,
        "evidence_count": len(parent_evidence),
    }


def _evidence_entry_value(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    if key == "source_uri" and isinstance(entry, str):
        return entry
    return default


def _runner_profile_evidence_meta(runner_profile: Mapping[str, Any]) -> dict[str, Any]:
    evidence = list(runner_profile.get("evidence", []))
    first = evidence[0] if evidence else {}
    uri = _evidence_entry_value(first, "source_uri") or _evidence_entry_value(first, "evidence_path") or runner_profile.get("identity", {}).get("profile_url")
    fingerprint = _evidence_entry_value(first, "source_fingerprint") or runner_profile.get("source_profile_fingerprint")
    captured_at = _evidence_entry_value(first, "retrieved_at") or runner_profile.get("retrieved_at") or runner_profile.get("generated_at")
    confidence = _evidence_entry_value(first, "confidence", 0.96)
    return _source_meta_from_evidence(
        parent_evidence=evidence,
        source_type="runner_profile",
        default_uri=uri,
        default_fingerprint=fingerprint,
        default_captured_at=captured_at,
        default_confidence=confidence,
    )


def _readiness_evidence_meta(current_readiness: Mapping[str, Any]) -> dict[str, Any]:
    evidence = list(current_readiness.get("evidence", []))
    first = evidence[0] if len(evidence) > 0 else {}
    second = evidence[1] if len(evidence) > 1 else {}
    return {
        "runner_profile": _source_meta_from_evidence(
            parent_evidence=evidence,
            source_type=str(_evidence_entry_value(first, "source_type") or "runner_profile"),
            default_uri=_evidence_entry_value(first, "source_uri"),
            default_fingerprint=_evidence_entry_value(first, "source_fingerprint"),
            default_captured_at=_evidence_entry_value(first, "captured_at"),
            default_confidence=_evidence_entry_value(first, "confidence", 0.96),
        ),
        "runner_readiness_input": _source_meta_from_evidence(
            parent_evidence=evidence,
            source_type=str(_evidence_entry_value(second, "source_type") or "runner_readiness_input"),
            default_uri=_evidence_entry_value(second, "source_uri") or _evidence_entry_value(second, "evidence_path"),
            default_fingerprint=_evidence_entry_value(second, "source_fingerprint"),
            default_captured_at=_evidence_entry_value(second, "captured_at"),
            default_confidence=_evidence_entry_value(second, "confidence", 0.98),
        ),
    }


def _source_kind_priority(source_type: str | None) -> int:
    return {
        "itra_public_runner": 0,
        "official": 0,
        "third_party_aggregator": 1,
        "user_self_report": 2,
    }.get(str(source_type or ""), 3)


def _field_resolution(sources: list[dict[str, Any]], field_name: str) -> dict[str, Any]:
    observations = []
    for index, source in enumerate(sources):
        value = source.get(field_name)
        if value is None or value == "":
            continue
        observations.append(
            {
                "index": index,
                "source_type": source.get("source_type"),
                "value": value,
                "confidence": source.get("source_meta", {}).get("confidence"),
            }
        )
    if not observations:
        return {
            "used_source_index": None,
            "used_source_type": None,
            "used_value": None,
            "all_values": [],
            "conflict": False,
            "conflict_note": "no usable values",
        }
    observations.sort(key=lambda item: (_source_kind_priority(item["source_type"]), -(item["confidence"] or 0.0), item["index"]))
    used = observations[0]
    values = [item["value"] for item in observations]
    unique_values = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return {
        "used_source_index": used["index"],
        "used_source_type": used["source_type"],
        "used_value": used["value"],
        "all_values": values,
        "conflict": len(unique_values) > 1,
        "conflict_note": "preserved dual-source disagreement" if len(unique_values) > 1 else "no conflict",
    }


def _condition_tags_from_text(*texts: Any) -> set[str]:
    combined = " ".join(str(text or "") for text in texts)
    normalized = combined.lower()
    tags: set[str] = set()
    if any(keyword in normalized for keyword in ("night", "夜", "夜赛", "夜跑", "头灯")):
        tags.add("night_race")
    if any(keyword in normalized for keyword in ("heat", "高温", "暴晒", "炎热", "sun", "晒")):
        tags.add("high_heat")
    if any(keyword in normalized for keyword in ("暴晒", "sun", "晒")):
        tags.add("sun_exposure")
    if any(keyword in normalized for keyword in ("反胃", "nausea", "恶心")):
        tags.add("brief_nausea")
    if any(keyword in normalized for keyword in ("高海拔", "altitude", "海拔")):
        tags.add("high_altitude")
    if any(keyword in normalized for keyword in ("沙漠", "sand", "沙地")):
        tags.add("desert_sand")
    return tags


def _alias_variants(name: Any) -> list[str]:
    raw = str(name or "").strip().lower()
    normalized = _normalize_text(raw)
    stripped = re.sub(r"\d+(?:km|k)?$", "", raw).strip()
    stripped_normalized = _normalize_text(stripped)
    variants = {variant for variant in (raw, normalized, stripped, stripped_normalized) if variant}
    return list(variants)


def _target_condition_tags(course_model: Mapping[str, Any]) -> dict[str, Any]:
    event = course_model.get("event", {})
    course = event.get("course", {})
    evidence_texts = [
        event.get("official_name"),
        event.get("group_name"),
        event.get("group_code"),
        course.get("route_text", {}).get("value") if isinstance(course.get("route_text"), Mapping) else None,
        course.get("route_text"),
    ]
    tags = sorted(_condition_tags_from_text(*evidence_texts))
    if tags:
        return {
            "status": "official_explicit",
            "tags": tags,
            "source_policy": "official_route_text_only",
            "notes": [
                "Target surface / desert tags are only carried when the official course text makes them explicit.",
                "The tags are descriptive only and are not treated as a calibrated time multiplier.",
            ],
        }
    return {
        "status": "unknown",
        "tags": [],
        "source_policy": "unknown_without_official_confirmation",
        "notes": [
            "No official course text explicitly confirms desert / sand conditions.",
            "The condition field stays unknown and does not drive any extra time adjustment.",
        ],
    }


def _observation_similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, float]:
    left_date = _parse_date(left.get("date"))
    right_date = _parse_date(right.get("date"))
    days = _days_between(left_date, right_date)
    date_similarity = 0.5 if days is None else _scale_similarity(days, 365.0)
    distance_similarity = _distance_similarity(_coerce_float(left.get("distance_km")), _coerce_float(right.get("distance_km")))
    gain_similarity = _distance_similarity(_coerce_float(left.get("elevation_gain_m")), _coerce_float(right.get("elevation_gain_m")))
    name_similarity = _name_similarity(left.get("event_name"), right.get("event_name"))
    group_similarity = 0.0
    left_group = _normalize_text(left.get("group_name") or left.get("group_code") or left.get("category"))
    right_group = _normalize_text(right.get("group_name") or right.get("group_code") or right.get("category"))
    if left_group and right_group:
        group_similarity = 1.0 if left_group == right_group else (1.0 if left_group in right_group or right_group in left_group else 0.0)
    score = (
        0.34 * distance_similarity
        + 0.26 * gain_similarity
        + 0.18 * date_similarity
        + 0.12 * max(name_similarity, group_similarity)
        + 0.10 * min(name_similarity + group_similarity, 1.0)
    )
    return {
        "date_similarity": round(date_similarity, 4),
        "distance_similarity": round(distance_similarity, 4),
        "gain_similarity": round(gain_similarity, 4),
        "name_similarity": round(name_similarity, 4),
        "group_similarity": round(group_similarity, 4),
        "score": round(score, 4),
    }


def _cluster_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_observations = [observation for observation in observations if observation.get("source_family") == "runner_profile"]
    readiness_observations = [observation for observation in observations if observation.get("source_family") != "runner_profile"]

    clusters: list[dict[str, Any]] = [
        {
            "anchor": observation,
            "observations": [observation],
            "merge_scores": [],
        }
        for observation in sorted(
            profile_observations,
            key=lambda item: (
                _parse_date(item.get("date")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
                -(item.get("source_meta", {}).get("confidence") or 0.0),
            ),
            reverse=True,
        )
    ]

    readiness_groups: dict[Any, list[dict[str, Any]]] = {}
    for observation in readiness_observations:
        group_key = observation.get("parent_event_index")
        readiness_groups.setdefault(group_key, []).append(observation)

    group_summaries: list[dict[str, Any]] = []
    for group_key, group_observations in readiness_groups.items():
        sorted_group = sorted(
            group_observations,
            key=lambda item: (
                _source_kind_priority(item.get("source_type")),
                -(item.get("source_meta", {}).get("confidence") or 0.0),
                _parse_date(item.get("date")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
            ),
        )
        summary = sorted_group[0]
        group_summaries.append(
            {
                "group_key": group_key,
                "observations": group_observations,
                "summary": summary,
                "has_official": any(item.get("source_type") == "itra_public_runner" for item in group_observations),
            }
        )

    for group in sorted(
        group_summaries,
        key=lambda item: (
            _parse_date(item["summary"].get("date")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
            -(item["summary"].get("source_meta", {}).get("confidence") or 0.0),
        ),
        reverse=True,
    ):
        observation = group["summary"]
        best_cluster = None
        best_score = -1.0
        best_components: dict[str, float] | None = None
        for cluster in clusters:
            components = _observation_similarity(observation, cluster["anchor"])
            score = components["score"]
            if score > best_score:
                best_score = score
                best_cluster = cluster
                best_components = components
        threshold = 0.62 if group["has_official"] else 0.82
        if best_cluster is not None and best_score >= threshold:
            best_cluster["observations"].extend(group["observations"])
            best_cluster["merge_scores"].append(best_components or {"score": best_score})
            continue
        clusters.append(
            {
                "anchor": observation,
                "observations": list(group["observations"]),
                "merge_scores": [],
            }
        )
    return clusters


def _calc_data_confidence(sources: list[dict[str, Any]]) -> float:
    confidences = [float(source.get("source_meta", {}).get("confidence") or 0.0) for source in sources if source.get("source_meta", {}).get("confidence") is not None]
    if not confidences:
        return 0.0
    average = sum(confidences) / len(confidences)
    spread = max(confidences) - min(confidences) if len(confidences) > 1 else 0.0
    penalty = min(0.08, spread * 0.12)
    return round(max(0.0, min(1.0, average - penalty)), 4)


def _provenance_score(sources: list[dict[str, Any]]) -> float:
    kinds = {str(source.get("source_type") or "") for source in sources}
    if "itra_public_runner" in kinds and "user_self_report" in kinds:
        return 0.93
    if "itra_public_runner" in kinds:
        return 0.97
    if "user_self_report" in kinds:
        return 0.84
    if "third_party_aggregator" in kinds:
        return 0.86
    return 0.8


def _condition_similarity(candidate_tags: set[str], target_tags: set[str]) -> tuple[float, str]:
    if not target_tags:
        return 0.5, "target conditions are unknown, so the component stays neutral"
    overlap = candidate_tags & target_tags
    if overlap:
        score = 0.6 + 0.2 * min(len(overlap), len(target_tags)) / max(len(target_tags), 1)
        return round(min(score, 1.0), 4), f"shared tags: {sorted(overlap)}"
    if candidate_tags:
        return 0.4, "candidate conditions are known but do not match the target surface tags"
    return 0.5, "candidate condition tags are absent, so the component stays neutral"


def _course_grade_penalty(course_grade: str | None) -> tuple[float, str]:
    grade = (course_grade or "").upper()
    if grade == "C":
        return 0.12, "C-grade provisional course keeps a stronger penalty because the route is still degraded and not fully calibrated."
    if grade == "B":
        return 0.05, "B-grade course receives a mild caution penalty."
    if grade == "A":
        return 0.0, "A-grade structural sample receives no course penalty."
    return 0.07, "Unknown grade receives a neutral caution penalty."


def _weight_components(
    *,
    sources: list[dict[str, Any]],
    target_distance_km: float | None,
    target_gain_m: float | None,
    target_tags: set[str],
    course_grade: str | None,
    candidate_condition_tags: set[str],
    current_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    source_quality = round(_provenance_score(sources) * max(_calc_data_confidence(sources), 0.01), 4)
    recency_anchor = _parse_date(current_readiness.get("generated_at")) or _parse_date(_utc_now())
    candidate_date = _parse_date(_field_resolution(sources, "date").get("used_value"))
    most_recent = candidate_date
    days_old = _days_between(recency_anchor, most_recent)
    recency_similarity = round(math.exp(-(days_old or 540.0) / 150.0), 4)

    primary_distance = _coerce_float(_field_resolution(sources, "distance_km").get("used_value"))
    primary_gain = _coerce_float(_field_resolution(sources, "elevation_gain_m").get("used_value"))
    distance_similarity = _distance_similarity(target_distance_km, primary_distance)
    gain_density_similarity = _gain_density_similarity(target_distance_km, target_gain_m, primary_distance, primary_gain)
    condition_similarity, condition_explanation = _condition_similarity(candidate_condition_tags, target_tags)
    course_grade_penalty, course_grade_explanation = _course_grade_penalty(course_grade)
    data_confidence = round(_calc_data_confidence(sources), 4)

    blended = (
        0.22 * source_quality
        + 0.18 * recency_similarity
        + 0.22 * distance_similarity
        + 0.18 * gain_density_similarity
        + 0.10 * condition_similarity
        + 0.10 * data_confidence
    )
    final_weight = round(max(0.0, min(1.0, blended - course_grade_penalty)), 4)
    source_confidences = [source.get("source_meta", {}).get("confidence") for source in sources if source.get("source_meta", {}).get("confidence") is not None]
    return {
        "source_quality": {
            "value": source_quality,
            "formula_version": SOURCE_QUALITY_VERSION,
            "formula": "source_quality = provenance_score * data_confidence",
            "explanation": "Provenance favors official/public records, and data_confidence is computed from the contributing sources.",
        },
        "recency_similarity": {
            "value": recency_similarity,
            "formula_version": RECENCY_VERSION,
            "formula": "recency_similarity = exp(-days_since_latest_race / 150)",
            "explanation": f"days_since_latest_race={round(days_old or 0.0, 2)} from the latest source date to the readiness timestamp.",
        },
        "distance_similarity": {
            "value": distance_similarity,
            "formula_version": DISTANCE_VERSION,
            "formula": "distance_similarity = 1 - abs(target_distance_km - source_distance_km) / max(target_distance_km, source_distance_km, 1)",
            "explanation": f"source_distance_km={primary_distance}, target_distance_km={target_distance_km}.",
        },
        "gain_density_similarity": {
            "value": gain_density_similarity,
            "formula_version": GAIN_DENSITY_VERSION,
            "formula": "gain_density_similarity = 1 - abs(target_gain_density - source_gain_density) / max(target_gain_density, source_gain_density, 1)",
            "explanation": f"source_gain_density={_gain_density(primary_distance, primary_gain)}, target_gain_density={_gain_density(target_distance_km, target_gain_m)}.",
        },
        "condition_similarity": {
            "value": condition_similarity,
            "formula_version": CONDITION_VERSION,
            "formula": "condition_similarity = neutral_or_overlap_based_score_from_explicit_condition_tags",
            "explanation": condition_explanation,
        },
        "course_grade_penalty": {
            "value": course_grade_penalty,
            "formula_version": COURSE_PENALTY_VERSION,
            "formula": "course_grade_penalty = fixed_penalty_by_grade",
            "explanation": course_grade_explanation,
        },
        "data_confidence": {
            "value": data_confidence,
            "formula_version": "phase7a.1-data-confidence-v1",
            "formula": "data_confidence = adjusted_average(contributing_source_confidences)",
            "explanation": f"contributing_source_confidences={source_confidences}",
        },
        "final_weight": {
            "value": final_weight,
            "formula_version": FINAL_WEIGHT_VERSION,
            "formula": "final_weight = clamp(0.22*source_quality + 0.18*recency_similarity + 0.22*distance_similarity + 0.18*gain_density_similarity + 0.10*condition_similarity + 0.10*data_confidence - course_grade_penalty, 0, 1)",
            "explanation": "The final weight is a transparent ranking score, not a calibrated time multiplier.",
        },
        "blended_score": round(blended, 4),
    }


def _candidate_condition_tags(candidate: Mapping[str, Any], readiness: Mapping[str, Any]) -> set[str]:
    tags = set(candidate.get("source_condition_tags", []))
    candidate_name = candidate.get("display_name") or candidate.get("canonical_name") or ""
    experience = readiness.get("experience", {})
    aliases = _alias_variants(candidate_name)
    for field in ("night_experience", "heat_experience", "cold_experience", "altitude_experience", "technical_terrain_experience"):
        record = experience.get(field)
        if not isinstance(record, Mapping):
            continue
        value = record.get("value")
        note = record.get("note")
        if aliases and any(alias in str(value) or alias in str(note) for alias in aliases):
            tags |= _condition_tags_from_text(value, note)
    return tags


def _collect_observations(
    *,
    runner_profile: Mapping[str, Any],
    current_readiness: Mapping[str, Any],
) -> list[dict[str, Any]]:
    profile_meta = _runner_profile_evidence_meta(runner_profile)
    readiness_meta = _readiness_evidence_meta(current_readiness)
    observations: list[dict[str, Any]] = []

    profile_races = runner_profile.get("historical_races") or runner_profile.get("race_results") or []

    for index, race in enumerate(profile_races):
        if not isinstance(race, Mapping):
            continue
        observations.append(
            {
                "observation_id": f"profile:{index}",
                "source_family": "runner_profile",
                "source_type": "itra_public_runner",
                "event_name": race.get("race") or race.get("event_name"),
                "display_name": race.get("race") or race.get("event_name"),
                "canonical_name": _normalize_text(race.get("race") or race.get("event_name")),
                "date": race.get("date"),
                "group_name": race.get("category") or race.get("group_name"),
                "group_code": race.get("category") or race.get("group_code"),
                "distance_km": race.get("distance_km"),
                "elevation_gain_m": race.get("elevation_gain_m"),
                "race_time": race.get("race_time"),
                "race_url": race.get("race_url"),
                "note": None,
                "source_meta": dict(profile_meta),
                "raw_source": dict(race),
            }
        )

    representative_races = current_readiness.get("experience", {}).get("representative_races", {}).get("value", [])
    readiness_evidence = list(current_readiness.get("evidence", []))
    readiness_source_map = {
        "itra_public_runner": readiness_meta["runner_profile"],
        "user_self_report": readiness_meta["runner_readiness_input"],
    }

    for race_index, race in enumerate(representative_races):
        if not isinstance(race, Mapping):
            continue
        for source_index, source in enumerate(race.get("sources", [])):
            if not isinstance(source, Mapping):
                continue
            source_type = str(source.get("source_type") or "user_self_report")
            source_meta = dict(readiness_source_map.get(source_type, readiness_meta["runner_readiness_input"]))
            observations.append(
                {
                    "observation_id": f"readiness:{race_index}:{source_index}",
                    "source_family": "current_readiness",
                    "source_type": source_type,
                    "event_name": race.get("event_name"),
                    "display_name": race.get("event_name"),
                    "canonical_name": _normalize_text(race.get("event_name")),
                    "date": source.get("date"),
                    "group_name": race.get("event_name"),
                    "group_code": race.get("event_name"),
                    "distance_km": source.get("distance_km"),
                    "elevation_gain_m": source.get("elevation_gain_m"),
                    "race_time": source.get("race_time"),
                    "race_url": None,
                    "note": source.get("note"),
                    "source_meta": source_meta,
                    "raw_source": dict(source),
                    "parent_event_index": race_index,
                }
            )

    return observations


def _cluster_to_candidate(
    *,
    cluster: Mapping[str, Any],
    target_distance_km: float | None,
    target_elevation_gain_m: float | None,
    target_condition_tags: set[str],
    course_grade: str | None,
    current_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    sources = list(cluster["observations"])
    sources.sort(
        key=lambda item: (
            _source_kind_priority(item.get("source_type")),
            -(item.get("source_meta", {}).get("confidence") or 0.0),
            _parse_date(item.get("date")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
        )
    )
    display_name = None
    for preferred in sources:
        if preferred.get("source_family") == "current_readiness" and preferred.get("display_name"):
            display_name = preferred.get("display_name")
            break
    if display_name is None:
        display_name = sources[0].get("display_name") or sources[0].get("event_name")

    source_resolution = {
        "cluster_version": CLUSTER_VERSION,
        "anchor_observation_id": cluster["anchor"].get("observation_id"),
        "merge_scores": list(cluster.get("merge_scores", [])),
        "sources": [],
        "field_resolution": {},
    }

    field_map = {
        "date": _field_resolution(sources, "date"),
        "distance_km": _field_resolution(sources, "distance_km"),
        "elevation_gain_m": _field_resolution(sources, "elevation_gain_m"),
        "race_time": _field_resolution(sources, "race_time"),
    }

    for field_name, resolution in field_map.items():
        source_index = resolution.get("used_source_index")
        chosen = sources[source_index] if source_index is not None else None
        source_resolution["field_resolution"][field_name] = {
            **resolution,
            "used_source_observation_id": chosen.get("observation_id") if chosen else None,
            "used_source_type": chosen.get("source_type") if chosen else None,
            "used_source_family": chosen.get("source_family") if chosen else None,
        }

    source_resolution["sources"] = [
        {
            "observation_id": source.get("observation_id"),
            "source_family": source.get("source_family"),
            "source_type": source.get("source_type"),
            "event_name": source.get("event_name"),
            "display_name": source.get("display_name"),
            "date": source.get("date"),
            "distance_km": source.get("distance_km"),
            "elevation_gain_m": source.get("elevation_gain_m"),
            "race_time": source.get("race_time"),
            "note": source.get("note"),
            "source_meta": dict(source.get("source_meta", {})),
        }
        for source in sources
    ]

    merged_condition_tags: set[str] = set()
    for source in sources:
        merged_condition_tags |= _condition_tags_from_text(source.get("note"), source.get("display_name"), source.get("event_name"))
        merged_condition_tags |= set(source.get("condition_tags", []))

    merged_condition_tags |= _candidate_condition_tags(
        {
            "display_name": display_name,
            "canonical_name": cluster["anchor"].get("canonical_name"),
            "source_condition_tags": sorted(merged_condition_tags),
        },
        current_readiness,
    )

    weight_components = _weight_components(
        sources=sources,
        target_distance_km=target_distance_km,
        target_gain_m=target_elevation_gain_m,
        target_tags=target_condition_tags,
        course_grade=course_grade,
        candidate_condition_tags=merged_condition_tags,
        current_readiness=current_readiness,
    )

    primary_resolution = {
        "distance_km": field_map["distance_km"],
        "elevation_gain_m": field_map["elevation_gain_m"],
        "race_time": field_map["race_time"],
    }
    calculation_source_notes = []
    for field_name, field_resolution in primary_resolution.items():
        if field_resolution.get("conflict"):
            calculation_source_notes.append(f"{field_name} uses {field_resolution['used_source_type']} while preserving alternate values {field_resolution['all_values']}")
        else:
            calculation_source_notes.append(f"{field_name} uses {field_resolution['used_source_type']} as the calculation field")

    data_confidence = weight_components["data_confidence"]["value"]
    final_weight = weight_components["final_weight"]["value"]

    selected_race_time = field_map["race_time"]["used_value"]
    selected_distance = _coerce_float(field_map["distance_km"]["used_value"])
    selected_gain = _coerce_float(field_map["elevation_gain_m"]["used_value"])
    selected_date = field_map["date"]["used_value"]

    source_conflict_note = "no conflict"
    if any(resolution.get("conflict") for resolution in field_map.values()):
        source_conflict_note = "source conflict preserved; calculation fields are explicitly selected and alternates remain attached"

    candidate = {
        "candidate_id": f"candidate:{_normalize_text(display_name)}",
        "label": display_name,
        "canonical_name": cluster["anchor"].get("canonical_name"),
        "display_name": display_name,
        "matched_race_name": display_name,
        "date": selected_date,
        "distance_km": selected_distance,
        "elevation_gain_m": selected_gain,
        "race_time": selected_race_time,
        "race_time_minutes": _race_time_to_minutes(selected_race_time),
        "source_type": source_resolution["field_resolution"]["race_time"]["used_source_type"] or sources[0].get("source_type"),
        "source_family": source_resolution["field_resolution"]["race_time"]["used_source_family"] or sources[0].get("source_family"),
        "time_source_type": source_resolution["field_resolution"]["race_time"]["used_source_type"] or sources[0].get("source_type"),
        "time_sources": [
            {
                "observation_id": source.get("observation_id"),
                "source_type": source.get("source_type"),
                "source_family": source.get("source_family"),
                "source_uri": source.get("source_meta", {}).get("source_uri"),
                "source_fingerprint": source.get("source_meta", {}).get("source_fingerprint"),
                "captured_at": source.get("source_meta", {}).get("captured_at"),
                "confidence": source.get("source_meta", {}).get("confidence"),
                "race_time": source.get("race_time"),
                "distance_km": source.get("distance_km"),
                "elevation_gain_m": source.get("elevation_gain_m"),
                "note": source.get("note"),
                "is_calculation_source": source.get("observation_id") == source_resolution["field_resolution"]["race_time"].get("used_source_observation_id"),
            }
            for source in sources
        ],
        "source_resolution": source_resolution,
        "source_conflict_note": source_conflict_note,
        "source_quality": weight_components["source_quality"]["value"],
        "recency_similarity": weight_components["recency_similarity"]["value"],
        "distance_similarity": weight_components["distance_similarity"]["value"],
        "gain_density_similarity": weight_components["gain_density_similarity"]["value"],
        "condition_similarity": weight_components["condition_similarity"]["value"],
        "course_grade_penalty": weight_components["course_grade_penalty"]["value"],
        "data_confidence": data_confidence,
        "final_weight": final_weight,
        "weight": final_weight,
        "weighting": weight_components,
        "condition_tags": sorted(merged_condition_tags),
        "target_condition_tags": sorted(target_condition_tags),
        "target_condition_status": "official_explicit" if target_condition_tags else "unknown",
        "distance_ratio_to_target": None if target_distance_km in (None, 0) or selected_distance is None else round(target_distance_km / selected_distance, 4),
        "gain_density_m_per_km": _gain_density(selected_distance, selected_gain),
        "target_difference": {
            "distance_km": None if target_distance_km is None or selected_distance is None else round(target_distance_km - selected_distance, 3),
            "elevation_gain_m": None if target_elevation_gain_m is None or selected_gain is None else round(target_elevation_gain_m - selected_gain, 1),
        },
        "source_condition_tags": sorted(merged_condition_tags),
        "planning_cap": current_readiness.get("assessment", {}).get("planning_permission"),
        "readiness_note": _readiness_note(current_readiness),
        "calculation_source_notes": calculation_source_notes,
    }
    candidate["weight_components"] = weight_components
    candidate["merge_score"] = cluster.get("merge_scores", [])
    candidate["source_count"] = len(sources)
    return candidate


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    date_value = _parse_date(candidate.get("date")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        -(candidate.get("final_weight") or 0.0),
        -(candidate.get("recency_similarity") or 0.0),
        -(candidate.get("distance_similarity") or 0.0),
        -date_value.timestamp(),
        candidate.get("label") or "",
    )


def build_historical_race_selection(
    *,
    runner_profile: Mapping[str, Any],
    current_readiness: Mapping[str, Any],
    target_event: Mapping[str, Any],
) -> dict[str, Any]:
    target_distance_km = _coerce_float(target_event.get("distance_km"))
    target_elevation_gain_m = _coerce_float(target_event.get("elevation_gain_m"))
    target_grade = str(target_event.get("grade") or "").upper() or None
    target_conditions = _target_condition_tags({"event": {"official_name": target_event.get("event_name"), "group_name": target_event.get("group_name"), "group_code": target_event.get("group_code"), "course": {"route_text": target_event.get("route_text")}}})
    target_condition_tags = set(target_conditions["tags"])
    safety_notice = _safety_notice(runner_profile)

    observations = _collect_observations(runner_profile=runner_profile, current_readiness=current_readiness)
    clusters = _cluster_observations(observations)
    candidates = [
        _cluster_to_candidate(
            cluster=cluster,
            target_distance_km=target_distance_km,
            target_elevation_gain_m=target_elevation_gain_m,
            target_condition_tags=target_condition_tags,
            course_grade=target_grade,
            current_readiness=current_readiness,
        )
        for cluster in clusters
    ]

    usable_candidates = [candidate for candidate in candidates if candidate.get("race_time_minutes") is not None and candidate.get("distance_km") is not None and candidate.get("elevation_gain_m") is not None]
    if len(usable_candidates) < 2:
        raise ValueError("insufficient_valid_candidates")

    usable_candidates.sort(key=_candidate_sort_key)
    selected_count = min(5, max(2, len(usable_candidates)))
    selected_ids = {candidate["candidate_id"] for candidate in usable_candidates[:selected_count]}

    for rank, candidate in enumerate(sorted(candidates, key=_candidate_sort_key), start=1):
        if candidate["candidate_id"] in selected_ids:
            candidate["include_in_baseline"] = True
            candidate["selection_rank"] = rank
            if candidate["source_type"] == "user_self_report" and len(candidate.get("time_sources", [])) == 1:
                candidate["selection_reason"] = "Included because it is a runner-confirmed self-report anchor and no official counterpart exists."
            elif len(candidate.get("time_sources", [])) > 1:
                candidate["selection_reason"] = "Included because it is a dual-source anchor with an official/public calculation source and preserved self-report evidence."
            else:
                candidate["selection_reason"] = "Included because it is a public runner anchor with usable time, distance, and climb evidence."
            candidate["sort_reason"] = (
                "Sorted by final_weight, then recency_similarity, then geometry components to keep the most recent and closest races near the top."
            )
        else:
            candidate["include_in_baseline"] = False
            candidate["selection_rank"] = None
            candidate["selection_reason"] = "Excluded because it falls outside the dynamic top 2-5 valid-history window."
            candidate["sort_reason"] = "Excluded by rank."

    rows = sorted(candidates, key=_candidate_sort_key)
    included_rows = [row for row in rows if row["include_in_baseline"]]
    excluded_rows = [row for row in rows if not row["include_in_baseline"]]

    evidence = [
        {
            "source_type": "runner_profile",
            "source_uri": _runner_profile_evidence_meta(runner_profile).get("source_uri"),
            "source_fingerprint": _runner_profile_evidence_meta(runner_profile).get("source_fingerprint"),
            "captured_at": _runner_profile_evidence_meta(runner_profile).get("captured_at"),
            "missing_reason": _runner_profile_evidence_meta(runner_profile).get("missing_reason"),
            "immutable": True,
        },
        {
            "source_type": "current_readiness",
            "source_uri": _readiness_evidence_meta(current_readiness)["runner_readiness_input"].get("source_uri"),
            "source_fingerprint": _readiness_evidence_meta(current_readiness)["runner_readiness_input"].get("source_fingerprint"),
            "captured_at": _readiness_evidence_meta(current_readiness)["runner_readiness_input"].get("captured_at"),
            "missing_reason": _readiness_evidence_meta(current_readiness)["runner_readiness_input"].get("missing_reason"),
            "immutable": True,
        },
    ]

    governance_envelope = {
        "schema_name": "historical_race_selection",
        "schema_version": "1.0.0",
        "generator_version": "0.1.0",
        "source_policy_version": "1.0.0",
        "cache_policy_version": "1.0.0",
        "safety_notice": safety_notice,
        "prediction_status": "unvalidated_research_candidate",
        "user_facing_prediction": False,
        "calibrated": False,
        "requires_phase8a_backtest": True,
    }

    return {
        "schema_name": "historical_race_selection",
        "schema_version": "1.0.0",
        "generated_at": current_readiness.get("generated_at") or _utc_now(),
        "generator_version": "0.1.0",
        "source_policy_version": "1.0.0",
        "cache_policy_version": "1.0.0",
        "safety_notice": safety_notice,
        "governance_envelope": governance_envelope,
        "target_event": {
            "event_name": target_event.get("event_name"),
            "group_name": target_event.get("group_name"),
            "group_code": target_event.get("group_code"),
            "grade": target_event.get("grade"),
            "distance_km": target_distance_km,
            "elevation_gain_m": target_elevation_gain_m,
            "route_version_state": target_event.get("route_version_state"),
            "condition_tags": sorted(target_condition_tags),
            "condition_status": target_conditions["status"],
            "condition_policy_notes": target_conditions["notes"],
        },
        "selection_policy": {
            "scope": "runner_self_only",
            "excluded_sources": [
                "other runners",
                "elite reference tables",
                "ungrounded heuristics from outside the loaded JSON files",
            ],
            "notes": [
                "Selection stays inside the runner's own profile and formal readiness snapshot.",
                "We keep both exact and self-reported records when the user explicitly asked for dual provenance.",
                "Selection is dynamic and now enumerates every historical race source instead of hardcoding known names.",
            ],
        },
        "candidates": rows,
        "selected_candidates": included_rows,
        "selection_summary": {
            "candidate_count": len(rows),
            "selected_count": len(included_rows),
            "included_count": len(included_rows),
            "excluded_count": len(excluded_rows),
            "included_labels": [row["label"] for row in included_rows],
            "excluded_labels": [row["label"] for row in excluded_rows],
            "selection_window": "top_2_to_5_valid_history_anchors",
            "weight_total": round(sum(row.get("final_weight", 0.0) for row in included_rows), 4),
            "readiness_note": _readiness_note(current_readiness),
        },
        "evidence": evidence,
        "diagnostics": {
            "input_validation": {
                "status": "passed",
                "error_count": 0,
            },
            "partial_reasons": [
                "runner_self_only",
                "dynamic_candidate_enumeration",
                "dual_source_preserved_when_available",
            ],
            "cluster_count": len(clusters),
            "selected_count": len(included_rows),
            "exclusion_count": len(excluded_rows),
        },
    }
