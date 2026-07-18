"""Adapters for already-authorized anonymous development artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import re
from typing import Any

from .validation import ReferenceInputError


def _series(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return f"series_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _race(series: str, date: str, group: Any) -> str:
    value = f"{series}|{date[:10]}|{group or ''}"
    return f"race_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def adapt_anonymous_development_records(
    *,
    participant_payloads: Sequence[Mapping[str, Any]],
    cohort_registry: Mapping[str, Any],
    source_uris: Sequence[str],
    source_fingerprints: Sequence[str],
) -> list[dict[str, Any]]:
    """Convert only registry-confirmed development payloads.

    The caller must select files before loading them. Passing a validation or
    holdout payload fails without returning partial output.
    """

    if len(participant_payloads) != len(source_uris) or len(participant_payloads) != len(source_fingerprints):
        raise ReferenceInputError("development_adapter_source_lengths_mismatch")
    assignments = {str(entry["participant_reference"]): str(entry["assigned_split"]) for entry in cohort_registry.get("entries", [])}
    output: list[dict[str, Any]] = []
    for payload, source_uri, fingerprint in zip(participant_payloads, source_uris, source_fingerprints):
        participant = str(payload.get("participant_reference") or "")
        split = assignments.get(participant)
        if split != "development":
            raise ReferenceInputError(f"development_only_adapter_rejected:{participant}:{split or 'unregistered'}")
        if payload.get("schema_name") != "participant_records_anonymized":
            raise ReferenceInputError(f"anonymous_participant_payload_required:{participant}")
        runner_id = str(payload.get("pseudonymous_runner_id") or "")
        if not runner_id.startswith("participant_"):
            raise ReferenceInputError(f"pseudonymous_runner_id_required:{participant}")
        for row in payload.get("records", []):
            if row.get("compliance_status") != "usable" or row.get("result_status") != "finish" or row.get("finish_time_seconds") is None:
                continue
            series = _series(row.get("event_name"))
            race_date = str(row["race_date"])
            output.append({
                "record_id": str(row["record_id"]),
                "runner_id": runner_id,
                "runner_role": "peer",
                "race_id": _race(series, race_date, row.get("race_group")),
                "event_series_id": series,
                "group_id": str(row.get("race_group") or ""),
                "race_date": race_date,
                "available_at": payload.get("generated_at") or race_date,
                "distance_km": float(row["distance_km"]),
                "elevation_gain_m": float(row["elevation_gain_m"]),
                "technical_score": None,
                "finish_time_minutes": float(row["finish_time_seconds"]) / 60.0,
                "result_status": "finish",
                "route_version": row.get("route_version"),
                "split": "development",
                "authorized_for_internal_research": True,
                "source": {
                    "source_type": "authorized_anonymous_participant_development_artifact",
                    "source_uri": source_uri,
                    "source_fingerprint": fingerprint,
                    "captured_at": payload.get("generated_at") or race_date,
                    "confidence": float(row.get("data_confidence", 0.0)),
                    "immutable": True,
                },
            })
    return output
