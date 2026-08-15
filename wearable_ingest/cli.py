"""CLI for W1 offline-only FIT import and controlled deletion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import DeleteError, IngestError, delete_request, ingest_fit, ingest_fit_batch, issue_consent_receipt
from .staging import stage_fit_archive
from .archive_selection import issue_archive_selection_authorization, stage_authorized_full_archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Local W1 Garmin FIT ingestion; no cloud access.")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--source", type=Path, required=True)
    ingest.add_argument("--private-root", type=Path, required=True)
    ingest.add_argument("--consent-file", type=Path, required=True)
    ingest.add_argument("--dry-run", action="store_true")
    batch = sub.add_parser("ingest-batch")
    sources = batch.add_mutually_exclusive_group(required=True)
    sources.add_argument("--source", type=Path, action="append", dest="sources")
    sources.add_argument("--source-dir", type=Path)
    batch.add_argument("--private-root", type=Path, required=True)
    batch.add_argument("--consent-file", type=Path, required=True)
    batch.add_argument("--dry-run", action="store_true")
    delete = sub.add_parser("delete")
    delete.add_argument("--request-id", required=True)
    delete.add_argument("--private-root", type=Path, required=True)
    delete.add_argument("--operator-kind", default="local_user")
    issue_consent = sub.add_parser("issue-consent", help="issue one immutable W1-only consent receipt; does not read FIT data")
    issue_consent.add_argument("--request-id", required=True)
    issue_consent.add_argument("--private-alias", required=True)
    issue_consent.add_argument("--consented-at", required=True)
    issue_consent.add_argument("--allowed-start-date", required=True)
    issue_consent.add_argument("--allowed-end-date", required=True)
    issue_consent.add_argument("--consent-root", type=Path, required=True)
    issue_consent.add_argument("--source-brand", choices=("garmin", "coros"), default="garmin")
    stage = sub.add_parser("stage-archive", help="stage only validated activity FIT records from an authorized ZIP; never imports")
    stage.add_argument("--source-archive", type=Path, required=True)
    stage.add_argument("--staging-root", type=Path, required=True)
    stage.add_argument("--consent-file", type=Path, required=True)
    stage.add_argument("--staging-request-id", required=True)
    stage.add_argument("--source-brand", choices=("garmin", "coros"), required=True)
    selection = sub.add_parser("issue-archive-selection", help="issue immutable authorization for local full archive inspection")
    selection.add_argument("--selection-request-id", required=True); selection.add_argument("--private-alias", required=True)
    selection.add_argument("--consented-at", required=True); selection.add_argument("--allowed-start-date", required=True); selection.add_argument("--allowed-end-date", required=True)
    selection.add_argument("--authorization-root", type=Path, required=True); selection.add_argument("--w1-consent-file", type=Path, required=True)
    full_stage = sub.add_parser("stage-authorized-full-archive", help="select only parseable activity FIT records from an authorized account archive")
    full_stage.add_argument("--source-archive", type=Path, required=True); full_stage.add_argument("--staging-root", type=Path, required=True)
    full_stage.add_argument("--w1-consent-file", type=Path, required=True); full_stage.add_argument("--authorization-file", type=Path, required=True)
    full_stage.add_argument("--staging-request-id", required=True); full_stage.add_argument("--source-brand", choices=("garmin", "coros"), required=True)
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            output = ingest_fit(source=args.source, private_root=args.private_root, consent_file=args.consent_file, dry_run=args.dry_run)
        elif args.command == "ingest-batch":
            output = ingest_fit_batch(source_paths=args.sources, source_dir=args.source_dir, private_root=args.private_root, consent_file=args.consent_file, dry_run=args.dry_run)
        elif args.command == "issue-consent":
            output = issue_consent_receipt(
                request_id=args.request_id,
                private_alias=args.private_alias,
                consented_at=args.consented_at,
                allowed_start_date=args.allowed_start_date,
                allowed_end_date=args.allowed_end_date,
                consent_root=args.consent_root,
                source_brand=args.source_brand,
            )
        elif args.command == "stage-archive":
            output = stage_fit_archive(
                source_archive=args.source_archive,
                staging_root=args.staging_root,
                consent_file=args.consent_file,
                staging_request_id=args.staging_request_id,
                source_brand=args.source_brand,
            )
        elif args.command == "issue-archive-selection":
            output = issue_archive_selection_authorization(selection_request_id=args.selection_request_id, private_alias=args.private_alias, consented_at=args.consented_at, allowed_start_date=args.allowed_start_date, allowed_end_date=args.allowed_end_date, authorization_root=args.authorization_root, w1_consent_file=args.w1_consent_file)
        elif args.command == "stage-authorized-full-archive":
            output = stage_authorized_full_archive(source_archive=args.source_archive, staging_root=args.staging_root, w1_consent_file=args.w1_consent_file, authorization_file=args.authorization_file, staging_request_id=args.staging_request_id, source_brand=args.source_brand)
        else:
            output = delete_request(request_id=args.request_id, private_root=args.private_root, operator_kind=args.operator_kind)
    except (IngestError, DeleteError) as exc:
        raise SystemExit(str(exc))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
