"""CLI for Phase 8A baseline backtest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import build_baseline_backtest, replay_baseline_backtest, write_baseline_backtest_outputs
from .validation import ValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the Phase 8A backtest")
    run.add_argument("--runner-history", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)

    replay = sub.add_parser("replay", help="replay the Phase 8A backtest from a saved runner history JSON")
    replay.add_argument("--runner-history", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "run":
            outputs = build_baseline_backtest(runner_history_path=args.runner_history)
        else:
            outputs = replay_baseline_backtest(runner_history_path=args.runner_history)
        write_baseline_backtest_outputs(outputs, args.output_dir)
        print(
            json.dumps(
                {
                    "phase_status": outputs["phase_status"],
                    "calibration_status": outputs["calibration_status"],
                    "user_facing_prediction_allowed": outputs["user_facing_prediction_allowed"],
                    "valid_sample_count": outputs["metrics"]["valid_sample_count"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except ValidationError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()

