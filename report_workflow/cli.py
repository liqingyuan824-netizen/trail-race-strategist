"""CLI for the three-input report workflow and its terminal completion gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import (
    ReportWorkflowError,
    capture_runner_for_request,
    finalize_report_request,
    inspect_report_request,
    start_report_request,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    request = sub.add_parser("request", help="start an immutable three-input request; status remains in_progress")
    request.add_argument("--name", required=True)
    request.add_argument("--runner-id", required=True)
    request.add_argument("--target-event", required=True)
    request.add_argument("--output-root", type=Path, required=True)

    status = sub.add_parser("status", help="inspect required request artifacts and terminal status")
    status.add_argument("--request-dir", type=Path, required=True)

    finalize = sub.add_parser("finalize", help="build course/readiness/strategy and enforce the final report contract")
    finalize.add_argument("--request-dir", type=Path, required=True)
    finalize.add_argument(
        "--historical-reference-consent",
        action="store_true",
        help="record explicit user consent to use a previous-year same-event, same-group official route as reference",
    )

    runner = sub.add_parser("runner-live", help="fresh ITRA public capture bound to the existing report request")
    runner.add_argument("--request-dir", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "request":
            result = start_report_request(
                name=args.name, runner_id=args.runner_id, target_event=args.target_event, output_root=args.output_root
            )
        elif args.command == "status":
            result = inspect_report_request(args.request_dir)
        elif args.command == "runner-live":
            result = capture_runner_for_request(args.request_dir)
        else:
            result = finalize_report_request(
                args.request_dir,
                historical_reference_consent=bool(getattr(args, "historical_reference_consent", False)),
            )
    except ReportWorkflowError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
