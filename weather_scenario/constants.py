"""Stable constants and layer policies for Phase 11."""

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

LAYER_POLICY = {
    "climate_baseline": {"max_hours_before_event": None, "freshness_hours": 24 * 365},
    "trend_7_14d": {"max_hours_before_event": 24 * 14, "freshness_hours": 24},
    "forecast_72h": {"max_hours_before_event": 72, "freshness_hours": 6},
    "race_day": {"max_hours_before_event": 24, "freshness_hours": 2},
}

SCENARIO_LIBRARY = {
    "normal": {
        "hazards": [],
        "strategy_action": "Use the conservative base plan and re-check official updates.",
        "equipment_action": "Use verified mandatory equipment and normal carried reserve.",
        "severity": "green",
    },
    "heat": {
        "hazards": ["heat_stress", "dehydration_risk"],
        "strategy_action": "Reduce effort early; suspend aggressive targets when heat risk rises.",
        "equipment_action": "Use only previously tested heat-management equipment and follow official instructions.",
        "severity": "yellow",
    },
    "cold": {
        "hazards": ["cold_stress", "hypothermia_risk"],
        "strategy_action": "Protect warmth and downgrade the goal; hypothermia signs stop performance planning.",
        "equipment_action": "Verify mandatory layers and dry backup only where officially permitted.",
        "severity": "yellow",
    },
    "rain": {
        "hazards": ["slippery_surface", "wet_cold"],
        "strategy_action": "Slow technical terrain and increase time margin.",
        "equipment_action": "Use tested rain protection and keep mandatory items serviceable.",
        "severity": "yellow",
    },
    "wind": {
        "hazards": ["wind_exposure", "falling_debris"],
        "strategy_action": "Avoid exposed-section time chasing and follow course closures.",
        "equipment_action": "Secure loose equipment and use verified wind protection.",
        "severity": "yellow",
    },
    "thunderstorm": {
        "hazards": ["lightning", "flash_flood", "official_course_stop"],
        "strategy_action": "Stop aggressive and finish-time targets; follow official shelter, hold, diversion, or cancellation instructions.",
        "equipment_action": "Official emergency instructions take priority over equipment plans.",
        "severity": "red",
    },
    "mud": {
        "hazards": ["low_traction", "slower_course", "equipment_damage"],
        "strategy_action": "Reduce descent speed and expand the time range; do not recover time in one segment.",
        "equipment_action": "Use previously tested traction and foot-care choices only.",
        "severity": "yellow",
    },
}
