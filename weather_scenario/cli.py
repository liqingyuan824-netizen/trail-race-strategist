"""CLI for Phase 11."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import replay_weather_scenarios, write_weather_scenarios
from .validation import WeatherValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--case-reference", default="anonymous_internal_case")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        bundle = replay_weather_scenarios(event_path=args.event, observations_path=args.observations, as_of=args.as_of, case_reference=args.case_reference)
        write_weather_scenarios(bundle, args.output_dir)
    except WeatherValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"schema_name": bundle["schema_name"], "forecast_phase": bundle["forecast_phase"], "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
