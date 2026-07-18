"""CLI for Phase 9 internal race strategy generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import replay_race_plan, write_race_plan
from .validation import StrategyValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-model", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--distance-only-baseline", type=Path, required=True)
    parser.add_argument("--case-reference", default="anonymous_internal_case")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = replay_race_plan(
            course_model_path=args.course_model,
            readiness_path=args.readiness,
            baseline_path=args.distance_only_baseline,
            case_reference=args.case_reference,
        )
        write_race_plan(plan, args.output_dir)
    except StrategyValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"schema_name": plan["schema_name"], "plan_status": plan["plan_status"], "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

