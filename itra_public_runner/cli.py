"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .request_session import RequestBindingError, create_live_request, create_replay_request


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay", help="parse a previously captured profile without network access; legacy audit command disabled for new requests")
    replay.add_argument("--profile-html", type=Path, required=True)
    replay.add_argument("--name", required=True)
    replay.add_argument("--runner-id", required=True)
    replay.add_argument("--output", type=Path, required=True)
    live = sub.add_parser("live", help="legacy audit command; disabled for new requests")
    live.add_argument("--name", required=True)
    live.add_argument("--runner-id", required=True)
    live.add_argument("--evidence-dir", type=Path, required=True)
    request = sub.add_parser("request", help="new immutable request; defaults to fresh live capture")
    request.add_argument("--name", required=True)
    request.add_argument("--runner-id", required=True)
    request.add_argument("--output-root", type=Path, required=True)
    request.add_argument("--replay", action="store_true", help="use only caller-selected saved HTML")
    request.add_argument("--profile-html", type=Path)
    args = parser.parse_args()
    if args.command in {"replay", "live"}:
        raise SystemExit("LEGACY_COMMAND_DISABLED_USE_REQUEST: new requests use `request` (default live) or `request --replay --profile-html <path>`")
    if args.command == "request":
        try:
            if args.replay:
                if args.profile_html is None:
                    raise RequestBindingError("REPLAY_PROFILE_HTML_REQUIRED")
                result = create_replay_request(name=args.name, runner_id=args.runner_id, profile_html=args.profile_html, output_root=args.output_root)
            else:
                result = create_live_request(name=args.name, runner_id=args.runner_id, output_root=args.output_root)
        except RequestBindingError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"request_id": result["request_id"], "session_dir": str(result["session_dir"]), "source_mode": result["manifest"]["source_mode"]}, ensure_ascii=False, indent=2))
        return
    raise SystemExit("UNREACHABLE_COMMAND")


if __name__ == "__main__":
    main()
