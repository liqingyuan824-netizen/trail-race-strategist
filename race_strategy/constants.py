"""Constants for the Phase 9 race strategy module."""

from __future__ import annotations

SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "0.1.0"
SOURCE_POLICY_VERSION = "1.0.0"
CACHE_POLICY_VERSION = "1.0.0"

SAFETY_NOTICE = {
    "version": "1.0.0",
    "medical_advice": False,
    "replaces_race_rules": False,
    "message": "This tool does not replace race rules, on-site safety, or professional medical judgment.",
}

STRATEGY_PARAMETERS = {
    "safe_finish": {
        "label": "safe_finish",
        "finish_multiplier": 1.10,
        "progress_exponent": 0.94,
        "checkpoint_stop_minutes": 4.0,
        "rpe_by_third": [[3, 4], [4, 5], [4, 5]],
        "run_walk_rule": "连续爬升在强度超过计划 RPE 上限前主动切换快走。",
        "technical_descent_rule": "技术下坡优先稳定落脚，不为追时间冒险。",
        "night_rule": "进入夜间前降低强度并确认照明。",
    },
    "stable": {
        "label": "stable",
        "finish_multiplier": 1.00,
        "progress_exponent": 1.00,
        "checkpoint_stop_minutes": 3.0,
        "rpe_by_third": [[4, 5], [5, 6], [5, 6]],
        "run_walk_rule": "连续爬升按计划快走，强度恢复受控后再恢复跑动。",
        "technical_descent_rule": "仅在计划 RPE 下仍能控制的地面跑动。",
        "night_rule": "视野不完整时保持强度，不加速。",
    },
    "aggressive": {
        "label": "aggressive",
        "finish_multiplier": 0.94,
        "progress_exponent": 1.07,
        "checkpoint_stop_minutes": 2.0,
        "rpe_by_third": [[5, 6], [6, 7], [7, 8]],
        "run_walk_rule": "前段控制爬升，最后三分之一开始后才可视状态提高输出。",
        "technical_descent_rule": "任何时间目标都不能凌驾于安全落脚和官方指令。",
        "night_rule": "视野或落脚不确定时暂停积极配速。",
    },
}
