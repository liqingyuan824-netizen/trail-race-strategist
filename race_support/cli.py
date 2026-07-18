"""CLI for Phase 10."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import replay_race_support_plan, write_race_support_plan
from .validation import SupportPlanValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--race-plan", type=Path, required=True)
    parser.add_argument("--course-model", type=Path, required=True)
    parser.add_argument("--support-inputs", type=Path, required=True)
    parser.add_argument("--weather", type=Path)
    parser.add_argument("--case-reference", default="anonymous_internal_case")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = replay_race_support_plan(
            race_plan_path=args.race_plan,
            course_model_path=args.course_model,
            support_inputs_path=args.support_inputs,
            weather_path=args.weather,
            case_reference=args.case_reference,
        )
        write_race_support_plan(plan, args.output_dir)
    except SupportPlanValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"schema_name": plan["schema_name"], "plan_status": plan["plan_status"], "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
