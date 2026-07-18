"""CLI for Phase 12 replay and snapshot generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import replay_live_replan, write_live_replan
from .validation import LiveReplanningValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--race-plan", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--processing-mode", choices=["near_real_time", "delayed_replay"], default="near_real_time")
    parser.add_argument("--validation-context", choices=["synthetic", "historical_replay", "future_event"], default="synthetic")
    parser.add_argument("--case-reference", default="anonymous_internal_case")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        snapshot = replay_live_replan(race_plan_path=args.race_plan, events_path=args.events, as_of=args.as_of, processing_mode=args.processing_mode, case_reference=args.case_reference, validation_context=args.validation_context)
        write_live_replan(snapshot, args.output_dir)
    except LiveReplanningValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"schema_name": snapshot["schema_name"], "decision": snapshot["decision"]["action"], "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
