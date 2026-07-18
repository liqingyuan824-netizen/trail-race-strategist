"""Request-bound participant import CLI.

This is intentionally separate from the Phase 8A frozen CLI. New user
requests must use this entrypoint; the historical CLI remains audit-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .participant_trial import import_request_participant_trial
from .validation import ValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("import-participant")
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--runner-profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sensitive-map-output", type=Path)
    args = parser.parse_args()
    try:
        outputs = import_request_participant_trial(
            intake_path=args.intake,
            confirmation_path=args.confirmation,
            request_manifest_path=args.request_manifest,
            runner_profile_path=args.runner_profile,
            output_dir=args.output_dir,
            sensitive_map_output=args.sensitive_map_output,
        )
    except ValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"request_id": outputs["participant_import_manifest"]["request_binding"]["request_id"], "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
