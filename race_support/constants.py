"""Stable constants for Phase 10."""

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

FAILURE_PLAYBOOK = [
    {
        "failure": "cannot_eat_or_nausea",
        "actions": [
            "Stop any performance push and reduce effort.",
            "Use only a previously tolerated option if one is available; do not trial a new product.",
            "Seek race medical support for persistent vomiting, confusion, severe weakness, or inability to keep fluid down.",
        ],
        "red_flag_escalation": "Persistent vomiting, confusion, or severe dehydration stops performance planning.",
    },
    {
        "failure": "official_supply_shortage",
        "actions": [
            "Use the verified carried reserve only.",
            "Do not assume an unverified later station will replace the missing supply.",
            "Downgrade the goal when the reserve is insufficient for the next verified station.",
        ],
    },
    {
        "failure": "private_support_or_drop_bag_unavailable",
        "actions": [
            "Continue only with the self-contained carried and official-station plan.",
            "Do not wait beyond the planned stop solely for missing support.",
            "Downgrade or stop when required safety equipment cannot be replaced.",
        ],
    },
    {
        "failure": "equipment_damage",
        "actions": [
            "Use a verified carried spare or official repair option if documented.",
            "Do not improvise around mandatory safety equipment.",
            "Follow race staff when required equipment is missing or unsafe.",
        ],
    },
]
