"""Phase 8A.1 dataset ingestion and eligibility package."""

from .pipeline import (
    build_dataset_artifacts,
    build_dataset_manifest,
    build_eligibility_report,
    load_dataset_files,
    normalize_records,
    write_dataset_outputs,
)
from .participant_trial import (
    build_empty_participant_status,
    import_participant_trial,
    import_request_participant_trial,
    participant_data_request_md,
    participant_intake_template,
    runner_history_confirmation_template,
    write_participant_trial_templates,
)
from .participant_pool import build_participant_pool
from .privacy_export import build_privacy_audit_artifacts, build_public_pool_summary, build_shareability_manifest, scan_artifact, scan_text_for_privacy_issues
from .phase8a_adapter import adapt_phase8a_evidence, convert_phase8a_samples
from .protocol import build_phase8a_evaluation_protocol
from .protocol_freeze import build_phase8a_frozen_protocol
from .post_development_freeze import build_post_development_frozen_bundle, build_validation_authorization_template, build_validation_ready_v11_bundle
from .validation_executor import run_bundle_first_validation
from .final_closeout import build_phase8a_final_closeout
from .protocol_rules import (
    build_metric_summary,
    can_execute_split,
    evaluate_holdout_gate,
    evaluate_validation_gate,
    standard_median,
)
from .split_evaluator import build_synthetic_split_report, execute_synthetic_split
from .real_split_executor import (
    build_development_authorization_template,
    execute_real_split,
    run_bundle_first_development,
    validate_bundle_first_development_readiness,
)
from .participant_capture import (
    build_capture_status,
    build_predisclosed_confirmation_records,
    evaluate_identity_match,
    write_predisclosed_participant_capture,
)

__all__ = [
    "build_dataset_artifacts",
    "build_dataset_manifest",
    "build_eligibility_report",
    "build_empty_participant_status",
    "adapt_phase8a_evidence",
    "build_capture_status",
    "build_participant_pool",
    "build_phase8a_evaluation_protocol",
    "build_phase8a_frozen_protocol",
    "build_post_development_frozen_bundle",
    "build_validation_authorization_template",
    "build_validation_ready_v11_bundle",
    "run_bundle_first_validation",
    "build_phase8a_final_closeout",
    "build_metric_summary",
    "can_execute_split",
    "evaluate_holdout_gate",
    "evaluate_validation_gate",
    "build_privacy_audit_artifacts",
    "build_public_pool_summary",
    "build_shareability_manifest",
    "build_predisclosed_confirmation_records",
    "import_participant_trial",
    "import_request_participant_trial",
    "evaluate_identity_match",
    "convert_phase8a_samples",
    "participant_data_request_md",
    "participant_intake_template",
    "runner_history_confirmation_template",
    "load_dataset_files",
    "normalize_records",
    "build_synthetic_split_report",
    "build_development_authorization_template",
    "scan_artifact",
    "scan_text_for_privacy_issues",
    "standard_median",
    "execute_synthetic_split",
    "execute_real_split",
    "validate_bundle_first_development_readiness",
    "run_bundle_first_development",
    "write_predisclosed_participant_capture",
    "write_participant_trial_templates",
    "write_dataset_outputs",
]
