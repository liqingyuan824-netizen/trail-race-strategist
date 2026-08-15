"""CLI for runner readiness intake and artifact generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import build_runner_readiness, replay_runner_readiness, write_readiness_outputs
from .questions import build_question_schema
from .validation import ValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    questions = sub.add_parser("questions", help="emit the intake question schema")
    questions.add_argument("--mode", choices=["quick", "formal"], required=True)

    build = sub.add_parser("build", help="build runner readiness artifacts")
    build.add_argument("--profile", type=Path, required=True)
    build.add_argument("--answers", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--wearable-feature-summary", type=Path)

    replay = sub.add_parser("replay", help="replay readiness artifacts from JSON files")
    replay.add_argument("--profile", type=Path, required=True)
    replay.add_argument("--answers", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path, required=True)
    replay.add_argument("--wearable-feature-summary", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "questions":
            payload = build_question_schema(args.mode)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        if args.command == "build":
            profile = json.loads(args.profile.read_text(encoding="utf-8"))
            answers = json.loads(args.answers.read_text(encoding="utf-8"))
            summary = json.loads(args.wearable_feature_summary.read_text(encoding="utf-8")) if args.wearable_feature_summary else None
            outputs = build_runner_readiness(profile, answers, wearable_feature_summary=summary)
        else:
            outputs = replay_runner_readiness(profile_path=args.profile, answers_path=args.answers, wearable_feature_summary_path=args.wearable_feature_summary)
        write_readiness_outputs(outputs, args.output_dir)
        print(json.dumps({key: outputs[key]["schema_name"] for key in ("runner_profile", "current_readiness", "missing_information")}, ensure_ascii=False, indent=2))
    except ValidationError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
