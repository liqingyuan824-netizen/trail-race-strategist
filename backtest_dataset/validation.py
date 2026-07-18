"""Validation and compliance classification for dataset records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .constants import ALLOWED_SOURCE_KINDS, COMPLIANCE_STATUSES


class ValidationError(ValueError):
    """Raised when imported dataset content cannot be normalized."""


REQUIRED_FIELDS = (
    "pseudonymous_runner_id",
    "event_id",
    "event_name",
    "race_date",
    "race_group",
    "distance_km",
    "elevation_gain_m",
    "finish_time_seconds",
    "result_status",
    "source_kind",
    "source_url",
    "source_file",
    "access_date",
    "usage_basis",
    "license_status",
    "route_version",
    "data_confidence",
)

FINISH_STATUSES = {"finish", "completed", "ok"}
NON_FINISH_STATUSES = {
    "dnf",
    "dns",
    "dsq",
    "did_not_finish",
    "did_not_start",
    "disqualified",
    "unknown",
    "time_unavailable",
}
BLOCKED_RIGHTS = {"blocked", "deny", "denied", "forbidden", "not_allowed", "restricted"}
ALLOWED_RIGHTS = {"allowed", "permitted", "open", "authorized", "license_ok", "public_domain"}


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
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


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _lower_text(value: Any) -> str:
    text = _normalize_text(value)
    return text.lower() if text is not None else ""


def _finish_time_seconds(record: Mapping[str, Any]) -> int | None:
    raw = record.get("finish_time_seconds")
    if raw in (None, ""):
        return None
    if isinstance(raw, str) and ":" in raw:
        parts = raw.split(":")
        try:
            if len(parts) == 3:
                hours, minutes, seconds = [float(part) for part in parts]
                return int(round(hours * 3600 + minutes * 60 + seconds))
            if len(parts) == 2:
                minutes, seconds = [float(part) for part in parts]
                return int(round(minutes * 60 + seconds))
        except ValueError:
            return None
    return _parse_int(raw)


def _has_required_shape(record: Mapping[str, Any]) -> list[str]:
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    return missing


def _is_rights_blocked(license_status: Any, usage_basis: Any, source_kind: Any) -> bool:
    status = _lower_text(license_status)
    basis = _lower_text(usage_basis)
    source = _lower_text(source_kind)
    return (
        status in BLOCKED_RIGHTS
        or basis in BLOCKED_RIGHTS
        or source == "blocked"
        or (status not in ALLOWED_RIGHTS and status != "")
    )


def _has_course_data(record: Mapping[str, Any]) -> bool:
    return record.get("event_id") not in (None, "") and record.get("route_version") not in (None, "")


def _is_source_kind_allowed(source_kind: Any) -> bool:
    return _lower_text(source_kind) in ALLOWED_SOURCE_KINDS


def validate_raw_record(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, Mapping):
        return ["not_mapping"]
    missing = _has_required_shape(record)
    if missing:
        errors.extend(f"missing:{field}" for field in missing)
    race_date = _parse_date(record.get("race_date"))
    if race_date is None:
        errors.append("invalid:race_date")
    access_date = _parse_date(record.get("access_date"))
    if access_date is None:
        errors.append("invalid:access_date")
    distance = _parse_float(record.get("distance_km"))
    gain = _parse_float(record.get("elevation_gain_m"))
    confidence = _parse_float(record.get("data_confidence"))
    if distance is None or distance <= 0:
        errors.append("invalid:distance_km")
    if gain is None or gain < 0:
        errors.append("invalid:elevation_gain_m")
    if confidence is None or not 0.0 <= confidence <= 1.0:
        errors.append("invalid:data_confidence")
    result_status = _lower_text(record.get("result_status"))
    finish_seconds = _finish_time_seconds(record)
    if result_status in FINISH_STATUSES and (finish_seconds is None or finish_seconds <= 0):
        errors.append("invalid:finish_time_seconds")
    if result_status not in FINISH_STATUSES and result_status not in NON_FINISH_STATUSES and result_status != "":
        errors.append("invalid:result_status")
    if not _is_source_kind_allowed(record.get("source_kind")):
        errors.append("invalid:source_kind")
    return errors


def classify_compliance_status(record: Mapping[str, Any]) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not isinstance(record, Mapping):
        return "invalid_record", ["not_mapping"]

    validation_errors = validate_raw_record(record)
    if validation_errors:
        issues.extend(validation_errors)
        if any(item.startswith("invalid:") for item in validation_errors):
            return "invalid_record", issues

    if _is_rights_blocked(record.get("license_status"), record.get("usage_basis"), record.get("source_kind")):
        issues.append("rights_blocked")
        return "blocked_by_data_rights", issues

    if not _has_course_data(record):
        issues.append("missing_course_data")
        return "missing_course_data", issues

    result_status = _lower_text(record.get("result_status"))
    finish_seconds = _finish_time_seconds(record)
    if result_status not in FINISH_STATUSES or finish_seconds is None:
        issues.append("non_finish_record")
        return "restricted", issues

    if _lower_text(record.get("route_version")) in {"unknown", "n/a", "na", "sparse", "partial"}:
        issues.append("route_version_sparse")
        return "restricted", issues

    if _parse_float(record.get("data_confidence")) is not None and _parse_float(record.get("data_confidence")) < 0.5:
        issues.append("low_confidence")
        return "restricted", issues

    return "usable", issues


def parse_finish_time_seconds(record: Mapping[str, Any]) -> int | None:
    return _finish_time_seconds(record)


def parse_date(value: Any) -> datetime | None:
    return _parse_date(value)


def parse_float(value: Any) -> float | None:
    return _parse_float(value)


def parse_int(value: Any) -> int | None:
    return _parse_int(value)


def ensure_status(value: str) -> str:
    if value not in COMPLIANCE_STATUSES:
        raise ValidationError(f"unsupported_compliance_status:{value}")
    return value
