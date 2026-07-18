"""Privacy auditing and public export helpers for the Phase 8A.2A pool."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .validation import ValidationError


DIRECT_IDENTIFIER_TOKENS = [
    "Qingyuan LI",
    "Xiulan LIU",
    "1901681",
    "5032161",
]

PSEUDONYMOUS_IDENTIFIER_TOKENS = [
    "participant_a5661a64be41",
    "participant_f473d3ae8065",
    "P-0001",
    "P-0002",
    "participant_reference",
    "pseudonymous_runner_id",
]

LOCAL_ONLY_TOKENS = [
    "participant_identity_map",
    ".local.json",
    "private/",
    "E:\\",
    "C:\\",
]

ROW_LEVEL_MARKERS = [
    "race_date",
    "event_name",
    "finish_time",
    "distance_km",
    "elevation_gain_m",
    "runner_history_confirmation",
    "participant_records.anonymized.json",
    "participant_pool_records.anonymized.json",
]

PUBLIC_EXPORT_FILENAMES = {
    "public_pool_summary.json",
    "public_pool_summary.md",
    "public_export_manifest.json",
    "public_privacy_scan.json",
}

INTERNAL_RESEARCH_FILENAMES = {
    "participant_records.anonymized.json",
    "participant_pool_records.anonymized.json",
    "participant_pool_manifest.json",
    "participant_pool_status.json",
    "participant_pool_report.md",
    "participant_import_manifest.json",
    "participant_status.json",
    "participant_trial_report.json",
    "participant_trial_status.json",
    "runner_history_confirmation.json",
    "runner_history_confirmation.predisclosed.json",
    "participant_intake.json",
    "backtest_dataset_manifest.json",
    "eligibility_report.json",
    "dataset_validation_report.md",
    "privacy_audit_report.md",
    "phase8a.2a_p0001_participant_import_report.md",
    "phase8a.2a_p0002_participant_import_report.md",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-8", errors="ignore")


def _contains_windows_absolute_path(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]:\\", text))


def _contains_row_level_history(text: str) -> bool:
    lowered = text.casefold()
    markers = sum(1 for marker in ROW_LEVEL_MARKERS if marker.casefold() in lowered)
    return markers >= 2


def scan_text_for_privacy_issues(text: str, *, filename: str = "") -> dict[str, Any]:
    direct_hits = [token for token in DIRECT_IDENTIFIER_TOKENS if token in text]
    pseudonymous_hits = [token for token in PSEUDONYMOUS_IDENTIFIER_TOKENS if token in text]
    local_only_hits = [token for token in LOCAL_ONLY_TOKENS if token in text]

    if _contains_windows_absolute_path(text):
        local_only_hits.append("absolute_windows_path")
    if filename:
        lowered_name = filename.casefold()
        if ".local.json" in lowered_name or "participant_identity_map" in lowered_name:
            local_only_hits.append("filename_local_only")
        if "participant_records.anonymized.json" in lowered_name or "participant_pool_records.anonymized.json" in lowered_name:
            pseudonymous_hits.append("filename_row_level_history")

    direct_hits = list(dict.fromkeys(direct_hits))
    pseudonymous_hits = list(dict.fromkeys(pseudonymous_hits))
    local_only_hits = list(dict.fromkeys(local_only_hits))
    row_level = _contains_row_level_history(text)
    return {
        "filename": filename,
        "direct_identifier_hits": direct_hits,
        "pseudonymous_identifier_hits": pseudonymous_hits,
        "local_only_hits": local_only_hits,
        "contains_row_level_race_history": row_level,
        "contains_absolute_local_path": bool(_contains_windows_absolute_path(text) or "absolute_windows_path" in local_only_hits),
        "blocked": bool(direct_hits or pseudonymous_hits or local_only_hits or row_level),
    }


def scan_artifact(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    scan = scan_text_for_privacy_issues(text, filename=path.name)
    scan["path"] = str(path)
    scan["is_binary"] = path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"}
    return scan


def classify_artifact(path: Path, scan: Mapping[str, Any]) -> tuple[str, bool, bool, bool, str]:
    lower_name = path.name.casefold()
    if "private" in path.parts or lower_name.endswith(".local.json") or "participant_identity_map" in lower_name:
        return (
            "sensitive_local_only",
            bool(scan["direct_identifier_hits"]),
            bool(scan["pseudonymous_identifier_hits"]),
            bool(scan["contains_row_level_race_history"]),
            "contains_local_only_identity_mapping",
        )
    if lower_name in PUBLIC_EXPORT_FILENAMES:
        return "public_summary", False, False, False, "public_export_summary_artifact"
    if lower_name in INTERNAL_RESEARCH_FILENAMES or bool(scan["blocked"]):
        return (
            "internal_research",
            bool(scan["direct_identifier_hits"]),
            bool(scan["pseudonymous_identifier_hits"]),
            bool(scan["contains_row_level_race_history"]),
            "contains_pseudonymous_row_level_history_or_internal_manifest",
        )
    return (
        "internal_research",
        bool(scan["direct_identifier_hits"]),
        bool(scan["pseudonymous_identifier_hits"]),
        bool(scan["contains_row_level_race_history"]),
        "generic_nonpublic_artifact",
    )


def build_shareability_manifest(scope_paths: Sequence[Path]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for scope_path in scope_paths:
        if scope_path.is_file():
            file_paths = [scope_path]
        else:
            file_paths = [path for path in scope_path.rglob("*") if path.is_file()]
        for path in file_paths:
            scan = scan_artifact(path)
            classification, contains_direct, contains_pseudo, contains_row_level, reason = classify_artifact(path, scan)
            if path.is_absolute():
                try:
                    rel_path = str(path.relative_to(Path.cwd()))
                except ValueError:
                    rel_path = str(path)
            else:
                rel_path = str(path)
            entries.append(
                {
                    "path": rel_path,
                    "classification": classification,
                    "contains_direct_identifier": contains_direct,
                    "contains_pseudonymous_identifier": contains_pseudo,
                    "contains_row_level_race_history": contains_row_level,
                    "contains_absolute_local_path": bool(scan["contains_absolute_local_path"]),
                    "safe_for_public_export": classification == "public_summary",
                    "reason": reason,
                }
            )
    return {
        "schema_name": "shareability_manifest",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "entries": entries,
    }


def _public_summary_payload(pool_manifest: Mapping[str, Any]) -> dict[str, Any]:
    dataset = pool_manifest["dataset"]
    real_eligible_folds = int(dataset["real_eligible_folds"])
    return {
        "schema_name": "public_pool_summary",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "participant_count": int(pool_manifest.get("participant_count", 2)),
        "real_eligible_folds": real_eligible_folds,
        "synthetic_eligible_folds": int(dataset["synthetic_eligible_folds"]),
        "usable_records": int(dataset["usable_records"]),
        "restricted_records": int(dataset["restricted_records"]),
        "distance_to_30": int(max(30 - real_eligible_folds, 0)),
        "calibration_status": "insufficient_evaluation_data" if real_eligible_folds < 30 else "calibrated_candidate",
        "calibration_allowed": bool(dataset["calibration_allowed"]),
        "user_facing_prediction_allowed": bool(dataset["user_facing_prediction_allowed"]),
        "summary_note": "Data is authorized by participants for local evaluation and shared only as aggregated public summary.",
    }


def _public_summary_markdown(payload: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# Dual Participant Pool Public Summary",
            "",
            "This summary contains only aggregate information.",
            "It excludes row-level records, participant identifiers, and local machine paths.",
            "",
            f"- participant_count: `{payload['participant_count']}`",
            f"- real_eligible_folds: `{payload['real_eligible_folds']}`",
            f"- synthetic_eligible_folds: `{payload['synthetic_eligible_folds']}`",
            f"- usable_records: `{payload['usable_records']}`",
            f"- restricted_records: `{payload['restricted_records']}`",
            f"- distance_to_30: `{payload['distance_to_30']}`",
            f"- calibration_status: `{payload['calibration_status']}`",
            f"- calibration_allowed: `{payload['calibration_allowed']}`",
            f"- user_facing_prediction_allowed: `{payload['user_facing_prediction_allowed']}`",
            "",
            "The current model is still below the publication threshold for predictions.",
            "The data is used for local evaluation after participant authorization.",
        ]
    )


def _scan_public_export_payloads(payloads: Mapping[str, Any]) -> dict[str, Any]:
    scan_results: list[dict[str, Any]] = []
    blocked = False
    for filename, payload in payloads.items():
        text = json.dumps(payload, ensure_ascii=False, indent=2) if filename.endswith(".json") else str(payload)
        scan = scan_text_for_privacy_issues(text, filename=filename)
        scan_results.append(
            {
                "filename": filename,
                "blocked": bool(scan["blocked"]),
                "contains_row_level_race_history": bool(scan["contains_row_level_race_history"]),
                "contains_absolute_local_path": bool(scan["contains_absolute_local_path"]),
                "direct_identifier_hits": len(scan["direct_identifier_hits"]),
                "pseudonymous_identifier_hits": len(scan["pseudonymous_identifier_hits"]),
            }
        )
        blocked = blocked or bool(scan["blocked"])
    return {
        "schema_name": "public_privacy_scan",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "scan_passed": not blocked,
        "blocked": blocked,
        "checked_files": list(payloads.keys()),
        "results": scan_results,
    }


def build_public_pool_summary(*, pool_dir: Path, output_dir: Path) -> dict[str, Any]:
    pool_manifest_path = pool_dir / "participant_pool_manifest.json"
    pool_status_path = pool_dir / "participant_pool_status.json"
    if not pool_manifest_path.exists() or not pool_status_path.exists():
        raise ValidationError("participant_pool_manifest_and_status_required")
    pool_manifest = json.loads(pool_manifest_path.read_text(encoding="utf-8-sig"))
    pool_status = json.loads(pool_status_path.read_text(encoding="utf-8-sig"))

    public_summary = _public_summary_payload(pool_manifest)
    public_markdown = _public_summary_markdown(public_summary)
    export_manifest = {
        "schema_name": "public_export_manifest",
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "public_export_ready": False,
        "allowed_files": [
            "public_pool_summary.json",
            "public_pool_summary.md",
            "public_export_manifest.json",
            "public_privacy_scan.json",
        ],
        "source_scope": "participant_pool_aggregates_only",
        "notes": [
            "No participant identifiers or row-level history are exported.",
            "The public bundle is produced only from whitelisted aggregate fields.",
        ],
    }
    scan_payload = _scan_public_export_payloads(
        {
            "public_pool_summary.json": public_summary,
            "public_pool_summary.md": public_markdown,
            "public_export_manifest.json": export_manifest,
            "public_privacy_scan.json": {"placeholder": True},
        }
    )
    export_manifest["public_export_ready"] = bool(scan_payload["scan_passed"])
    scan_payload["public_export_ready"] = bool(scan_payload["scan_passed"])

    if not scan_payload["scan_passed"]:
        raise ValidationError("public_export_privacy_scan_failed")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "public_pool_summary.json", public_summary)
    (output_dir / "public_pool_summary.md").write_text(public_markdown, encoding="utf-8")
    _write_json(output_dir / "public_export_manifest.json", export_manifest)
    _write_json(output_dir / "public_privacy_scan.json", scan_payload)

    return {
        "public_pool_summary": public_summary,
        "public_export_manifest": export_manifest,
        "public_privacy_scan": scan_payload,
        "public_export_ready": True,
        "pool_status": pool_status,
    }


def build_privacy_audit_artifacts(
    *,
    scope_paths: Sequence[Path],
    output_dir: Path,
    public_export_dir: Path | None = None,
) -> dict[str, Any]:
    audit_paths = list(scope_paths)
    if public_export_dir is not None:
        audit_paths.append(public_export_dir)
    manifest = build_shareability_manifest(audit_paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    policy_path = output_dir / "references" / "participant-data-sharing-policy.md"
    report_path = output_dir / "Phase8A.2A_双人池隐私与分享审计报告.md"
    manifest_path = output_dir / "shareability_manifest.json"

    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        "\n".join(
            [
                "# Participant Data Sharing Policy",
                "",
                "## Tiers",
                "- `public_summary`: aggregate-only materials that exclude participant identifiers and row-level race history.",
                "- `internal_research`: anonymized or pseudonymous materials used for modeling, validation, or audit.",
                "- `sensitive_local_only`: direct identity mappings and any file that can re-identify a participant.",
                "",
                "## Rules",
                "- Public case study authorization does not authorize release of row-level datasets or identity maps.",
                "- Local identity maps stay under `private/participant_identity_maps/` and never enter public exports.",
                "- Files with `.local.json` are treated as local-only, not as public-safe by filename alone.",
            ]
        ),
        encoding="utf-8",
    )

    _write_json(manifest_path, manifest)

    classification_counts = Counter(entry["classification"] for entry in manifest["entries"])
    safe_count = sum(1 for entry in manifest["entries"] if entry["safe_for_public_export"])
    risky_entries = [entry for entry in manifest["entries"] if entry["classification"] != "public_summary"]
    report_path.write_text(
        "\n".join(
            [
                "# 双人池隐私与分享审计报告",
                "",
                "## Summary",
                f"- public_summary_files: `{safe_count}`",
                f"- internal_research_files: `{classification_counts.get('internal_research', 0)}`",
                f"- sensitive_local_only_files: `{classification_counts.get('sensitive_local_only', 0)}`",
                "",
                "## Key Risks",
                "- The P-0001 evidence directory is not safe to share as a whole because it still contains `participant_identity_map.local.json`.",
                "- Public case study authorization does not upgrade row-level histories into public materials.",
                "- `.local.json` files remain local-only regardless of filename convenience.",
                "",
                "## Export Boundary",
                "- The public export must be created from whitelisted aggregate fields only.",
                "- No direct identifiers, pseudonymous identifiers, or local paths may appear in the public export bundle.",
                "",
                "## Non-Public Files",
            ]
            + [f"- {entry['path']}: {entry['classification']} ({entry['reason']})" for entry in risky_entries[:50]]
        ),
        encoding="utf-8",
    )

    return {
        "shareability_manifest": manifest,
        "shareability_manifest_path": manifest_path,
        "policy_path": policy_path,
        "report_path": report_path,
    }
