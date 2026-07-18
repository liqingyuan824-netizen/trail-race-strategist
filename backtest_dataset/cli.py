"""CLI for the Phase 8A.1 dataset layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from .phase8a_adapter import adapt_phase8a_evidence
from .participant_pool import build_participant_pool
from .participant_trial import build_empty_participant_status, import_participant_trial, write_participant_trial_templates
from .privacy_export import build_public_pool_summary
from .protocol_freeze import build_phase8a_frozen_protocol
from .post_development_freeze import build_post_development_frozen_bundle, build_validation_authorization_template, build_validation_ready_v11_bundle
from .validation_executor import run_bundle_first_validation
from .pipeline import build_dataset_artifacts, load_dataset_files, write_dataset_outputs
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

    ingest = sub.add_parser("import", help="import dataset files and emit manifest/report artifacts")
    ingest.add_argument("--input", type=Path, nargs="+", required=True)
    ingest.add_argument("--output-dir", type=Path, required=True)
    ingest.add_argument("--synthetic", action="store_true", help="mark imported data as synthetic fixture data")

    validate = sub.add_parser("validate", help="validate dataset files without writing raw imports")
    validate.add_argument("--input", type=Path, nargs="+", required=True)
    validate.add_argument("--output-dir", type=Path, required=True)
    validate.add_argument("--synthetic", action="store_true")

    adapt = sub.add_parser("adapt-phase8a", help="adapt a Phase 8A baseline report into standard dataset records")
    adapt.add_argument("--input-report", type=Path, required=True)
    adapt.add_argument("--output-dir", type=Path)
    adapt.add_argument("--output-root", type=Path, default=Path("evidence"))

    templates = sub.add_parser("write-participant-templates", help="write participant intake templates and the data request note")
    templates.add_argument("--output-dir", type=Path, required=True)

    status = sub.add_parser("participant-status", help="emit an empty participant trial status snapshot")
    status.add_argument("--output-dir", type=Path, required=True)

    import_trial = sub.add_parser("import-participant", help="import one participant's confirmed history into the backtest dataset")
    import_trial.add_argument("--intake", type=Path, required=True)
    import_trial.add_argument("--confirmation", type=Path, required=True)
    import_trial.add_argument("--runner-profile", type=Path, required=True)
    import_trial.add_argument("--output-dir", type=Path, required=True)
    import_trial.add_argument("--sensitive-map-output", type=Path)

    pool = sub.add_parser("build-participant-pool", help="merge anonymized participant imports into a shared backtest pool")
    pool.add_argument("--participant-dir", type=Path, action="append", required=True)
    pool.add_argument("--cohort-registry", type=Path, required=True)
    pool.add_argument("--output-dir", type=Path, required=True)

    public_pool = sub.add_parser("build-public-pool-summary", help="export a public aggregate summary from a participant pool")
    public_pool.add_argument("--pool-dir", type=Path, required=True)
    public_pool.add_argument("--output-dir", type=Path, required=True)

    freeze = sub.add_parser("freeze-phase8a-protocol", help="freeze the Phase 8A v3 draft into an immutable protocol bundle")
    freeze.add_argument("--draft-dir", type=Path, required=True)
    freeze.add_argument("--output-dir", type=Path, required=True)

    synthetic = sub.add_parser("run-synthetic-split", help="evaluate a synthetic-only split input against the frozen rule gate")
    synthetic.add_argument("--input", type=Path, required=True)

    auth_template = sub.add_parser("write-development-authorization-template", help="write an unapproved development authorization template")
    auth_template.add_argument("--frozen-bundle", type=Path, required=True)
    auth_template.add_argument("--participant-pool", type=Path, required=True)
    auth_template.add_argument("--output-root", type=Path, required=True)

    real_readiness = sub.add_parser("validate-real-development-readiness", help="check whether a real frozen development split is unlocked and hash-bound")
    real_readiness.add_argument("--frozen-bundle", type=Path, required=True)
    real_readiness.add_argument("--participant-pool", type=Path, required=True)
    real_readiness.add_argument("--authorization", type=Path, required=True)
    real_readiness.add_argument("--output-root", type=Path, required=True)

    real_development = sub.add_parser("run-frozen-development", help="run the frozen real development split executor")
    real_development.add_argument("--frozen-bundle", type=Path, required=True)
    real_development.add_argument("--participant-pool", type=Path, required=True)
    real_development.add_argument("--authorization", type=Path, required=True)
    real_development.add_argument("--output-root", type=Path, required=True)

    post_freeze = sub.add_parser("freeze-post-development", help="freeze audited development evidence before validation")
    post_freeze.add_argument("--prior-bundle", type=Path, required=True)
    post_freeze.add_argument("--development-result", type=Path, required=True)
    post_freeze.add_argument("--output-dir", type=Path, required=True)

    validation_template = sub.add_parser("write-validation-authorization-template", help="write an unapproved validation authorization template")
    validation_template.add_argument("--frozen-bundle", type=Path, required=True)
    validation_template.add_argument("--output-root", type=Path, required=True)

    validation_freeze = sub.add_parser("freeze-validation-ready-v11", help="bind the production validation executor without unlocking validation")
    validation_freeze.add_argument("--prior-bundle", type=Path, required=True)
    validation_freeze.add_argument("--output-dir", type=Path, required=True)

    validation_run = sub.add_parser("run-frozen-validation", help="run the single-use frozen validation executor")
    validation_run.add_argument("--frozen-bundle", type=Path, required=True)
    validation_run.add_argument("--participant-pool", type=Path, required=True)
    validation_run.add_argument("--authorization", type=Path, required=True)
    validation_run.add_argument("--output-root", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command in {"import", "validate"}:
            outputs = build_dataset_artifacts(input_paths=args.input, output_dir=args.output_dir, synthetic=args.synthetic)
            output_dir = args.output_dir
        elif args.command == "adapt-phase8a":
            output_dir = args.output_dir
            if output_dir is None:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                output_dir = args.output_root / f"phase8a-adapted-{stamp}"
            outputs = adapt_phase8a_evidence(report_path=args.input_report, output_dir=output_dir)
        elif args.command == "write-participant-templates":
            output_dir = args.output_dir
            outputs = write_participant_trial_templates(output_dir)
            print(
                json.dumps(
                    {
                        "schema_name": "participant_trial_templates",
                        "output_dir": str(output_dir),
                        "files": [
                            "participant_intake_template.json",
                            "runner_history_confirmation_template.json",
                            "participant_data_request.md",
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        elif args.command == "participant-status":
            output_dir = args.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            status_report = build_empty_participant_status()
            (output_dir / "participant_trial_status.json").write_text(json.dumps(status_report, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "participant_trial_status.md").write_text(
                "\n".join(
                    [
                        "# Phase 8A.2A 空数据状态",
                        "",
                        f"- real_runner_count: `{status_report['real_runner_count']}`",
                        f"- real_eligible_folds: `{status_report['real_eligible_folds']}`",
                        f"- distance_to_30: `{status_report['distance_to_30']}`",
                        f"- calibration_allowed: `{status_report['calibration_allowed']}`",
                        f"- user_facing_prediction_allowed: `{status_report['user_facing_prediction_allowed']}`",
                    ]
                ),
                encoding="utf-8",
            )
            outputs = {"manifest": {"schema_name": status_report["schema_name"], "dataset": {"eligible_folds": 0, "real_eligible_folds": 0, "synthetic_eligible_folds": 0, "usable_records": 0}}, "eligibility_report": {"overall_status": "insufficient_history"}}
            print(json.dumps(status_report, ensure_ascii=False, indent=2))
            return
        elif args.command == "import-participant":
            output_dir = args.output_dir
            outputs = import_participant_trial(
                intake_path=args.intake,
                confirmation_path=args.confirmation,
                runner_profile_path=args.runner_profile,
                output_dir=output_dir,
                sensitive_map_output=args.sensitive_map_output,
            )
        elif args.command == "build-participant-pool":
            output_dir = args.output_dir
            outputs = build_participant_pool(participant_dirs=args.participant_dir, cohort_registry=args.cohort_registry, output_dir=output_dir)
        elif args.command == "build-public-pool-summary":
            output_dir = args.output_dir
            outputs = build_public_pool_summary(pool_dir=args.pool_dir, output_dir=output_dir)
        elif args.command == "freeze-phase8a-protocol":
            output_dir = args.output_dir
            outputs = build_phase8a_frozen_protocol(draft_dir=args.draft_dir, output_dir=output_dir)
            print(
                json.dumps(
                    {
                        "schema_name": outputs["protocol_freeze_manifest"]["schema_name"],
                        "frozen_protocol_sha256": outputs["protocol_freeze_manifest"]["frozen_protocol_sha256"],
                        "development_folds": len(outputs["protocol_freeze_manifest"]["development_fold_ids"]),
                        "validation_folds": len(outputs["protocol_freeze_manifest"]["validation_fold_ids"]),
                        "holdout_folds": len(outputs["protocol_freeze_manifest"]["holdout_fold_ids"]),
                        "output_dir": str(output_dir),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        elif args.command == "run-synthetic-split":
            outputs = build_synthetic_split_report(input_path=args.input)
            print(
                json.dumps(
                    {
                        "split_name": outputs.get("split_name", "development"),
                        "synthetic_only": outputs["synthetic_only"],
                        "execution_allowed": outputs["execution_allowed"],
                        "row_count": outputs["row_count"],
                        "observed_unique_fold_count": outputs["metrics"]["observed_unique_fold_count"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        elif args.command == "write-development-authorization-template":
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
        elif args.command == "validate-real-development-readiness":
            outputs = validate_bundle_first_development_readiness(
                frozen_bundle_dir=args.frozen_bundle,
                participant_pool_dir=args.participant_pool,
                authorization_path=args.authorization,
                output_root=args.output_root,
            )
            print(
                json.dumps(
                    {
                        "schema_name": outputs["schema_name"],
                        "split_name": outputs.get("split_name", "development"),
                        "execution_allowed": outputs["execution_allowed"],
                        "prediction_invocations": outputs["prediction_invocations"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        elif args.command == "run-frozen-development":
            outputs = run_bundle_first_development(
                frozen_bundle_dir=args.frozen_bundle,
                participant_pool_dir=args.participant_pool,
                authorization_path=args.authorization,
                output_root=args.output_root,
            )
            print(
                json.dumps(
                    {
                        "schema_name": outputs["schema_name"],
                        "split_name": outputs.get("split_name", "development"),
                        "execution_allowed": outputs["execution_allowed"],
                        "prediction_invocations": outputs["prediction_invocations"],
                        "output_dir": outputs.get("output_dir"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        elif args.command == "freeze-post-development":
            outputs = build_post_development_frozen_bundle(
                prior_bundle_dir=args.prior_bundle,
                development_result_dir=args.development_result,
                output_dir=args.output_dir,
            )
            print(json.dumps({"freeze_version": outputs["manifest"]["freeze_version"], "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))
            return
        elif args.command == "write-validation-authorization-template":
            outputs = build_validation_authorization_template(frozen_bundle_dir=args.frozen_bundle, output_root=args.output_root)
            print(json.dumps({"run_id": outputs["authorization_template"]["run_id"], "approved": False, "template_path": str(outputs["template_path"])}, ensure_ascii=False, indent=2))
            return
        elif args.command == "freeze-validation-ready-v11":
            outputs = build_validation_ready_v11_bundle(prior_bundle_dir=args.prior_bundle, output_dir=args.output_dir)
            print(json.dumps({"freeze_version": outputs["manifest"]["freeze_version"], "output_dir": str(args.output_dir)}, ensure_ascii=False, indent=2))
            return
        elif args.command == "run-frozen-validation":
            outputs = run_bundle_first_validation(frozen_bundle_dir=args.frozen_bundle, participant_pool_dir=args.participant_pool, authorization_path=args.authorization, output_root=args.output_root)
            print(json.dumps({"schema_name": outputs["schema_name"], "split_name": outputs["split_name"], "execution_allowed": outputs["execution_allowed"], "prediction_invocations": outputs["prediction_invocations"], "output_dir": outputs.get("output_dir")}, ensure_ascii=False, indent=2))
            return
        else:
            raise ValidationError("unsupported_command")
        if args.command == "build-public-pool-summary":
            print(
                json.dumps(
                    {
                        "schema_name": outputs["public_export_manifest"]["schema_name"],
                        "public_export_ready": outputs["public_export_ready"],
                        "participant_count": outputs["public_pool_summary"]["participant_count"],
                        "real_eligible_folds": outputs["public_pool_summary"]["real_eligible_folds"],
                        "synthetic_eligible_folds": outputs["public_pool_summary"]["synthetic_eligible_folds"],
                        "usable_records": outputs["public_pool_summary"]["usable_records"],
                        "output_dir": str(output_dir),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        print(
            json.dumps(
                {
                    "schema_name": outputs["manifest"]["schema_name"],
                    "overall_status": outputs["eligibility_report"]["overall_status"],
                    "eligible_folds": outputs["manifest"]["dataset"]["eligible_folds"],
                    "real_eligible_folds": outputs["manifest"]["dataset"]["real_eligible_folds"],
                    "synthetic_eligible_folds": outputs["manifest"]["dataset"]["synthetic_eligible_folds"],
                    "usable_records": outputs["manifest"]["dataset"]["usable_records"],
                    "output_dir": str(output_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except ValidationError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
