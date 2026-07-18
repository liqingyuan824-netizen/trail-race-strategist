"""CLI dedicated to evidence-only Phase 8A closeout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .final_closeout import build_phase8a_final_closeout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-bundle", type=Path, required=True)
    parser.add_argument("--participant-pool", type=Path, required=True)
    parser.add_argument("--validation-result", type=Path, required=True)
    parser.add_argument("--validation-ledger", type=Path, required=True)
    parser.add_argument("--test-evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    outputs = build_phase8a_final_closeout(
        frozen_bundle_dir=args.frozen_bundle,
        participant_pool_dir=args.participant_pool,
        validation_result_dir=args.validation_result,
        validation_ledger_path=args.validation_ledger,
        test_evidence_path=args.test_evidence,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "schema_name": outputs["manifest"]["schema_name"],
                "status": outputs["closeout_state"]["status"],
                "output_dir": str(outputs["output_dir"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
