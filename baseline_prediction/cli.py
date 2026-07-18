"""CLI for Phase 7A baseline prediction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import build_baseline_prediction, replay_baseline_prediction, write_baseline_outputs
from .validation import ValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build Phase 7A baseline prediction artifacts")
    build.add_argument("--runner-profile", type=Path, required=True)
    build.add_argument("--readiness", type=Path, required=True)
    build.add_argument("--course-model", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)

    replay = sub.add_parser("replay", help="replay Phase 7A baseline prediction artifacts from JSON files")
    replay.add_argument("--runner-profile", type=Path, required=True)
    replay.add_argument("--readiness", type=Path, required=True)
    replay.add_argument("--course-model", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "build":
            runner_profile = json.loads(args.runner_profile.read_text(encoding="utf-8"))
            readiness = json.loads(args.readiness.read_text(encoding="utf-8"))
            course_model = json.loads(args.course_model.read_text(encoding="utf-8"))
            outputs = build_baseline_prediction(
                runner_profile=runner_profile,
                current_readiness=readiness,
                course_model=course_model,
            )
        else:
            outputs = replay_baseline_prediction(
                runner_profile_path=args.runner_profile,
                readiness_path=args.readiness,
                course_model_path=args.course_model,
            )
        write_baseline_outputs(outputs, args.output_dir)
        print(
            json.dumps(
                {
                    "baseline_prediction_inputs": outputs["baseline_prediction_inputs"]["schema_name"],
                    "historical_race_selection": outputs["historical_race_selection"]["schema_name"],
                    "baseline_candidate_ranges": outputs["baseline_candidate_ranges"]["schema_name"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except ValidationError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
