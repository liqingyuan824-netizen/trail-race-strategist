"""Pipeline for building runner readiness artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from .completeness import assess_completeness
from .health_rules import assess_health_and_planning
from .mapping import build_current_readiness_output, build_missing_information_output, build_profile_output
from .normalization import fingerprint, normalize_answers, normalize_runner_profile
from .questions import build_question_schema
from .validation import ValidationError, validate_readiness_answers, validate_runner_profile


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_runner_readiness(profile: Mapping[str, Any], answers: Mapping[str, Any]) -> dict[str, Any]:
    profile_errors = validate_runner_profile(profile)
    answer_errors = validate_readiness_answers(answers)
    errors = profile_errors + answer_errors
    if errors:
        raise ValidationError("; ".join(errors))

    normalized_profile = normalize_runner_profile(profile)
    question_schema = build_question_schema(answers["mode"])
    prepared_answers = dict(answers)
    prepared_answers["question_schema"] = question_schema
    normalized_answers = normalize_answers(prepared_answers)

    completeness = assess_completeness(answers["mode"], normalized_answers["inputs"], profile)
    health = assess_health_and_planning(normalized_answers["inputs"], profile, completeness)

    cache_key = "|".join(
        [
            "runner_readiness",
            f"mode={answers['mode']}",
            f"profile={normalized_profile['source_profile_fingerprint']}",
            f"answers={normalized_answers['raw_input_fingerprint']}",
            f"health={health['risk_level']}",
            f"permission={health['planning_permission']}",
        ]
    )

    profile_output = build_profile_output(normalized_profile)
    # New request-scoped profiles carry their immutable identity/hash binding
    # through readiness so later report stages cannot silently switch runners.
    if isinstance(profile.get("request_binding"), Mapping):
        profile_output["request_binding"] = dict(profile["request_binding"])
    profile_output["cache_key"] = cache_key
    profile_output["generated_at"] = answers["generated_at"]
    profile_output["diagnostics"] = {
        **profile_output.get("diagnostics", {}),
        "history_summary_fingerprint": fingerprint(normalized_profile.get("historical_summary", {})),
        "input_validation": {
            "status": "passed",
            "error_count": 0,
        },
    }

    current_readiness = build_current_readiness_output(
        profile=normalized_profile,
        normalized_answers=normalized_answers,
        completeness=completeness,
        health=health,
        cache_key=cache_key,
    )
    if isinstance(profile.get("request_binding"), Mapping):
        current_readiness["request_binding"] = dict(profile["request_binding"])
    missing_information = build_missing_information_output(
        normalized_answers=normalized_answers,
        completeness=completeness,
        profile=normalized_profile,
        cache_key=cache_key,
    )
    if isinstance(profile.get("request_binding"), Mapping):
        missing_information["request_binding"] = dict(profile["request_binding"])
    return {
        "runner_profile": profile_output,
        "current_readiness": current_readiness,
        "missing_information": missing_information,
        "question_schema": question_schema,
    }


def write_readiness_outputs(outputs: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("runner_profile", "current_readiness", "missing_information"):
        payload = outputs[name]
        (output_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def replay_runner_readiness(*, profile_path: Path, answers_path: Path) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    return build_runner_readiness(profile, answers)
