"""Health and planning rules for runner readiness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .specs import RED_FLAG_FIELDS, YELLOW_HINT_FIELDS


def _contains_any(text: str, needles: set[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if isinstance(value, Mapping):
        return " ".join(f"{key}:{_flatten_text(val)}" for key, val in value.items())
    return str(value)


def extract_flags(normalized_inputs: Mapping[str, Any]) -> dict[str, list[str]]:
    red_flags: list[str] = []
    yellow_flags: list[str] = []

    red_symptoms = _flatten_text(normalized_inputs.get("red_flag_symptoms", {}).get("value"))
    if red_symptoms:
        for marker in RED_FLAG_FIELDS:
            if marker.lower() in red_symptoms.lower():
                red_flags.append(marker)

    injury_text = _flatten_text(normalized_inputs.get("injury_status", {}).get("value"))
    illness_text = _flatten_text(normalized_inputs.get("illness_status", {}).get("value"))
    if _contains_any(injury_text, {"骨折", "无法负重", "胸痛", "剧痛", "晕厥", "呼吸困难"}):
        red_flags.append("injury_red_flag")
    if _contains_any(illness_text, {"高烧", "发烧", "意识", "呼吸困难", "持续呕吐", "脱水", "胸痛"}):
        red_flags.append("illness_red_flag")

    sleep_hours = normalized_inputs.get("sleep_hours", {}).get("value")
    subjective_fatigue = normalized_inputs.get("subjective_fatigue", {}).get("value")
    training_break_days = normalized_inputs.get("training_break_days", {}).get("value")
    recovery_days = normalized_inputs.get("recovery_days", {}).get("value")

    try:
        sleep_hours_f = float(sleep_hours) if sleep_hours is not None else None
    except (TypeError, ValueError):
        sleep_hours_f = None
    try:
        fatigue_f = float(subjective_fatigue) if subjective_fatigue is not None else None
    except (TypeError, ValueError):
        fatigue_f = None
    try:
        break_days_f = float(training_break_days) if training_break_days is not None else None
    except (TypeError, ValueError):
        break_days_f = None
    try:
        recovery_days_f = float(recovery_days) if recovery_days is not None else None
    except (TypeError, ValueError):
        recovery_days_f = None

    if sleep_hours_f is not None and sleep_hours_f < 6.5:
        yellow_flags.append("short_sleep")
    if fatigue_f is not None and fatigue_f >= 7:
        yellow_flags.append("high_fatigue")
    if break_days_f is not None and break_days_f >= 7:
        yellow_flags.append("training_break")
    if recovery_days_f is not None and recovery_days_f >= 4:
        yellow_flags.append("extended_recovery")
    if injury_text and injury_text.strip().lower() not in {"none", ""}:
        yellow_flags.append("minor_injury_or_soreness")
    if illness_text and illness_text.strip().lower() not in {"none", ""}:
        yellow_flags.append("minor_illness_or_recovery")
    if _contains_any(injury_text, {"?", "?", "??", "??", "??", "soreness"}):
        yellow_flags.append("minor_injury_or_soreness")
    if _contains_any(illness_text, {"??", "???", "??", "??", "???"}):
        yellow_flags.append("minor_illness_or_recovery")
    return {"red_flags": list(dict.fromkeys(red_flags)), "yellow_flags": list(dict.fromkeys(yellow_flags))}


def _goal_intensity(goal_text: str) -> str:
    text = goal_text.lower()
    aggressive_markers = ["pb", "pb+", "冲", "all in", "all-in", "激进", "冒进", "拼成绩", "sub", "破"]
    conservative_markers = ["完赛", "安全", "保守", "稳", "finish", "完成"]
    if any(marker in text for marker in aggressive_markers):
        return "aggressive"
    if any(marker in text for marker in conservative_markers):
        return "conservative"
    return "unknown"


def compute_readiness_score(normalized_inputs: Mapping[str, Any], profile: Mapping[str, Any]) -> float:
    weekly_km = normalized_inputs.get("weekly_km", {}).get("value")
    weekly_elevation_m = normalized_inputs.get("weekly_elevation_m", {}).get("value")
    continuity_weeks = normalized_inputs.get("continuity_weeks", {}).get("value")
    longest_distance = normalized_inputs.get("longest_session_distance_km", {}).get("value")
    longest_duration = normalized_inputs.get("longest_session_duration_min", {}).get("value")
    longest_elevation = normalized_inputs.get("longest_session_elevation_m", {}).get("value")
    race_count = len(profile.get("race_results", []))

    def _num(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    score = 0.0
    wk = _num(weekly_km)
    if wk is not None:
        score += min(wk / 80.0, 1.0) * 24.0
    we = _num(weekly_elevation_m)
    if we is not None:
        score += min(we / 4000.0, 1.0) * 12.0
    cw = _num(continuity_weeks)
    if cw is not None:
        score += min(cw / 12.0, 1.0) * 16.0
    ld = _num(longest_distance)
    if ld is not None:
        score += min(ld / 40.0, 1.0) * 12.0
    ldur = _num(longest_duration)
    if ldur is not None:
        score += min(ldur / 360.0, 1.0) * 8.0
    le = _num(longest_elevation)
    if le is not None:
        score += min(le / 2500.0, 1.0) * 6.0
    score += min(race_count / 5.0, 1.0) * 10.0

    terrain_fields = [
        "night_experience",
        "heat_experience",
        "cold_experience",
        "altitude_experience",
        "technical_terrain_experience",
        "fueling_tolerance",
        "pole_experience",
        "gear_experience",
        "support_arrangements",
    ]
    filled_terrain = sum(1 for field in terrain_fields if normalized_inputs.get(field, {}).get("value") not in (None, "", []))
    score += min(filled_terrain / len(terrain_fields), 1.0) * 14.0

    sleep_hours = _num(normalized_inputs.get("sleep_hours", {}).get("value"))
    fatigue = _num(normalized_inputs.get("subjective_fatigue", {}).get("value"))
    if sleep_hours is not None:
        score += max(min((sleep_hours - 5.0) / 3.0, 1.0), 0.0) * 4.0
    if fatigue is not None:
        score += max(min((10.0 - fatigue) / 10.0, 1.0), 0.0) * 4.0

    if normalized_inputs.get("training_break_days", {}).get("value") is not None:
        score -= min(float(normalized_inputs["training_break_days"]["value"]) / 10.0, 10.0) * 1.5
    if normalized_inputs.get("recovery_days", {}).get("value") is not None:
        score -= min(float(normalized_inputs["recovery_days"]["value"]) / 10.0, 10.0) * 1.0

    return max(0.0, min(score, 100.0))


def assess_health_and_planning(
    normalized_inputs: Mapping[str, Any],
    profile: Mapping[str, Any],
    completeness: Mapping[str, Any],
) -> dict[str, Any]:
    flags = extract_flags(normalized_inputs)
    goal_text = _flatten_text(normalized_inputs.get("race_goal", {}).get("value"))
    goal_intensity = _goal_intensity(goal_text)
    readiness_score = compute_readiness_score(normalized_inputs, profile)
    required_missing_count = int(completeness.get("required_missing_count", completeness.get("missing_count", 0)))

    if flags["red_flags"]:
        planning_permission = "stop_and_seek_professional_assessment"
        risk_level = "red"
    elif flags["yellow_flags"]:
        planning_permission = "conservative_planning_only"
        risk_level = "yellow"
    elif required_missing_count > 0:
        planning_permission = "conservative_planning_only"
        risk_level = "yellow"
    elif goal_intensity == "aggressive" and readiness_score < 75.0:
        planning_permission = "aggressive_plan_blocked"
        risk_level = "yellow"
    elif readiness_score >= 70.0:
        planning_permission = "normal_planning_allowed"
        risk_level = "green"
    else:
        planning_permission = "conservative_planning_only"
        risk_level = "yellow"

    return {
        "risk_level": risk_level,
        "planning_permission": planning_permission,
        "goal_intensity": goal_intensity,
        "readiness_score": round(readiness_score, 1),
        "red_flags": flags["red_flags"],
        "yellow_flags": flags["yellow_flags"],
        "reason_codes": (
            ["red_flag_present"]
            if flags["red_flags"]
            else (["yellow_flag_present"] if flags["yellow_flags"] else ["insufficient_or_conservative"])
        ),
    }


def readiness_explanation(
    *,
    completeness: Mapping[str, Any],
    health: Mapping[str, Any],
) -> str:
    required_missing_count = int(completeness.get("required_missing_count", completeness.get("missing_count", 0)))
    recommended_missing_count = int(completeness.get("recommended_missing_count", 0))
    if health["risk_level"] == "red":
        return "红旗已触发，当前输出停止在专业评估上限。"
    if required_missing_count == 0 and recommended_missing_count > 0:
        return "必填formal资料完整，但仍缺3项建议补充资料。readiness_band: high 只是未验证的内部启发式训练准备度；conservative_planning_only 是近期伤痛和疾病黄旗触发的安全上限，两者衡量对象不同，并不冲突。"
    if required_missing_count == 0:
        return "必填formal资料完整。readiness_band: high 只是未验证的内部启发式训练准备度；conservative_planning_only 是近期伤痛和疾病黄旗触发的安全上限，两者衡量对象不同，并不冲突。"
    return "formal资料仍有必填缺口，因此当前画像仍然不完整。"
