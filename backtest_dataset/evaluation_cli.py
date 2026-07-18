"""CLI helpers for frozen Phase 8A protocol and synthetic split execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .protocol_freeze import build_phase8a_frozen_protocol
from .real_split_executor import (
    build_development_authorization_template,
    run_bundle_first_development,
    validate_bundle_first_development_readiness,
)
from .split_evaluator import build_synthetic_split_report
from .validation import ValidationError


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze-phase8a", help="freeze the Phase 8A v3 draft into an immutable bundle")
    freeze.add_argument("--draft-dir", type=Path, required=True)
    freeze.add_argument("--output-dir", type=Path, required=True)

    synth = sub.add_parser("run-synthetic-split", help="evaluate a synthetic-only split contract")
    synth.add_argument("--input", type=Path, required=True)

    auth_template = sub.add_parser("write-development-authorization-template", help="write an unapproved development authorization template")
    auth_template.add_argument("--frozen-bundle", type=Path, required=True)
    auth_template.add_argument("--participant-pool", type=Path, required=True)
    auth_template.add_argument("--output-root", type=Path, required=True)

    real_readiness = sub.add_parser("validate-real-development-readiness", help="check real development readiness without relying on precomputed predictions")
    real_readiness.add_argument("--frozen-bundle", type=Path, required=True)
    real_readiness.add_argument("--participant-pool", type=Path, required=True)
    real_readiness.add_argument("--authorization", type=Path, required=True)
    real_readiness.add_argument("--output-root", type=Path, required=True)

    real_development = sub.add_parser("run-frozen-development", help="run the frozen real development split executor")
    real_development.add_argument("--frozen-bundle", type=Path, required=True)
    real_development.add_argument("--participant-pool", type=Path, required=True)
    real_development.add_argument("--authorization", type=Path, required=True)
    real_development.add_argument("--output-root", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "freeze-phase8a":
            outputs = build_phase8a_frozen_protocol(draft_dir=args.draft_dir, output_dir=args.output_dir)
            print(
                json.dumps(
                    {
                        "schema_name": outputs["protocol_freeze_manifest"]["schema_name"],
                        "frozen_protocol_sha256": outputs["protocol_freeze_manifest"]["frozen_protocol_sha256"],
                        "development_folds": len(outputs["protocol_freeze_manifest"]["development_fold_ids"]),
                        "validation_folds": len(outputs["protocol_freeze_manifest"]["validation_fold_ids"]),
                        "holdout_folds": len(outputs["protocol_freeze_manifest"]["holdout_fold_ids"]),
                        "output_dir": str(args.output_dir),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if args.command == "run-synthetic-split":
            report = build_synthetic_split_report(input_path=args.input)
            print(
                json.dumps(
                    {
                        "split_name": report.get("split_name", "development"),
                        "synthetic_only": report["synthetic_only"],
                        "execution_allowed": report["execution_allowed"],
                        "row_count": report["row_count"],
                        "observed_unique_fold_count": report["metrics"]["observed_unique_fold_count"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if args.command == "write-development-authorization-template":
            outputs = build_development_authorization_template(
                frozen_bundle_dir=args.frozen_bundle,
                participant_pool_dir=args.participant_pool,
                output_root=args.output_root,
            )
            print(
                json.dumps(
                    {
                        "schema_name": outputs["authorization_template"]["schema_name"],
                        "run_id": outputs["authorization_template"]["run_id"],
                        "approved": outputs["authorization_template"]["approved"],
                        "template_path": str(outputs["template_path"]),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if args.command == "validate-real-development-readiness":
            report = validate_bundle_first_development_readiness(
                frozen_bundle_dir=args.frozen_bundle,
                participant_pool_dir=args.participant_pool,
                authorization_path=args.authorization,
                output_root=args.output_root,
            )
            print(
                json.dumps(
                    {
                        "schema_name": report["schema_name"],
                        "split_name": report.get("split_name", "development"),
                        "execution_allowed": report["execution_allowed"],
                        "prediction_invocations": report["prediction_invocations"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if args.command == "run-frozen-development":
            report = run_bundle_first_development(
                frozen_bundle_dir=args.frozen_bundle,
                participant_pool_dir=args.participant_pool,
                authorization_path=args.authorization,
                output_root=args.output_root,
            )
            print(
                json.dumps(
                    {
                        "schema_name": report["schema_name"],
                        "split_name": report.get("split_name", "development"),
                        "execution_allowed": report["execution_allowed"],
                        "prediction_invocations": report["prediction_invocations"],
                        "output_dir": report.get("output_dir"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        raise ValidationError("unsupported_command")
    except ValidationError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
