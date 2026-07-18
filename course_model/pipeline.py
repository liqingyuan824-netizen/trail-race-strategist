"""Pipeline for building and replaying course models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from .cp_segments import build_cp_model
from .grading import classify_material_grade
from .mapping import map_course_model
from .normalization import normalize_course_fields
from .validation import ValidationError, validate_course_cp_sequence, validate_race_source_bundle


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_course_model(bundle: Mapping[str, Any]) -> dict[str, Any]:
    errors = validate_race_source_bundle(bundle)
    errors.extend(validate_course_cp_sequence(bundle))
    if errors:
        raise ValidationError("; ".join(errors))
    grade = classify_material_grade(bundle)
    normalized = normalize_course_fields(bundle, grade)
    cp_model = build_cp_model(bundle, normalized)
    model = map_course_model(bundle, grade=grade, normalized=normalized, cp_model=cp_model)
    model["generated_at"] = _utc_now()
    model["diagnostics"]["input_validation"] = {
        "status": "passed",
        "error_count": 0,
    }
    return model


def replay_course_model(*, bundle_path: Path) -> dict[str, Any]:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    return build_course_model(bundle)


def write_course_model(model: Mapping[str, Any], output_path: Path) -> None:
    output_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
