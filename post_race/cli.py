"""CLI for Phase 13 replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import replay_race_retro, write_race_retro
from .validation import PostRaceValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--race-plan", type=Path, required=True)
    parser.add_argument("--actual-result", type=Path, required=True)
    parser.add_argument("--conditions", type=Path, required=True)
    parser.add_argument("--consent", type=Path, required=True)
    parser.add_argument("--prior-model", type=Path)
    parser.add_argument("--case-reference", default="anonymous_internal_case")
    parser.add_argument("--validation-context", choices=["synthetic", "historical_replay", "future_event"], default="synthetic")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        retro = replay_race_retro(race_plan_path=args.race_plan, actual_result_path=args.actual_result, conditions_path=args.conditions, consent_path=args.consent, prior_model_path=args.prior_model, case_reference=args.case_reference, validation_context=args.validation_context)
        write_race_retro(retro, args.output_dir)
    except PostRaceValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"schema_name": retro["schema_name"], "snapshot_id": retro["immutability"]["snapshot_id"], "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
