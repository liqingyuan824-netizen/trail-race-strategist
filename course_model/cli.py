"""CLI for Phase 5 course model replay and build."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import build_course_model, replay_course_model, write_course_model


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a course model from a race source bundle")
    build.add_argument("--bundle", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)

    replay = sub.add_parser("replay", help="replay a course model from a previously captured bundle")
    replay.add_argument("--bundle", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "build":
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        model = build_course_model(bundle)
    else:
        model = replay_course_model(bundle_path=args.bundle)
    write_course_model(model, args.output)
    print(json.dumps(model, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
