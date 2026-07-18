"""Question schema generation for runner readiness intake."""

from __future__ import annotations

from datetime import datetime, timezone

from .specs import (
    ALL_FIELDS,
    FIELD_SPECS,
    FORMAL_FIELDS,
    FORMAL_INPUT_FIELDS,
    GENERATOR_VERSION,
    SAFETY_NOTICE,
    SCHEMA_VERSION,
    SOURCE_POLICY_VERSION,
    CACHE_POLICY_VERSION,
    QUICK_FIELDS,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_question_schema(mode: str) -> dict[str, object]:
    if mode not in {"quick", "formal"}:
        raise ValueError(f"unsupported mode: {mode}")
    field_names = QUICK_FIELDS if mode == "quick" else FORMAL_INPUT_FIELDS
    questions: list[dict[str, object]] = []
    for field_name in field_names:
        spec = FIELD_SPECS[field_name]
        questions.append(
            {
                "field": field_name,
                "label": spec["label"],
                "prompt": spec["prompt_quick"] if mode == "quick" else spec["prompt_formal"],
                "required": bool(spec["required_quick"] if mode == "quick" else spec["required_formal"]),
                "sensitive": bool(spec["sensitive"]),
                "local_only": bool(spec["sensitive"]),
                "priority": spec["priority"],
                "kind": spec["kind"],
            }
        )
    return {
        "schema_name": "runner_readiness_questions",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "mode": mode,
        "question_count": len(questions),
        "questions": questions,
        "sensitive_field_policy": {
            "local_only": True,
            "shared_with_general_model": False,
            "note": "Sensitive health details stay local and are not intended for general model sharing.",
        },
        "safety_notice": SAFETY_NOTICE,
    }

