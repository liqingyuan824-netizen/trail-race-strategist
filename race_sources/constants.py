"""Shared constants for the race source bundle pipeline."""

SCHEMA_NAME = "race_source_bundle"
SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "0.1.0"
SOURCE_POLICY_VERSION = "1.0.0"
CACHE_POLICY_VERSION = "1.0.0"

SAFETY_NOTICE = {
    "version": "1.0.0",
    "medical_advice": False,
    "replaces_race_rules": False,
    "message": "本工具不替代赛事规则、现场医疗、救援人员或专业医疗判断。",
}
