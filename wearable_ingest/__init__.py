"""W0–W3 offline wearable ingestion; it is not connected to prediction."""

from .features import FeatureSummaryError, build_feature_summary, validate_feature_summary
from .pipeline import DeleteError, IngestError, delete_request, ingest_fit, ingest_fit_batch, issue_consent_receipt
from .staging import stage_fit_archive
from .archive_selection import issue_archive_selection_authorization, stage_authorized_full_archive

__all__ = ["DeleteError", "FeatureSummaryError", "IngestError", "build_feature_summary", "delete_request", "ingest_fit", "ingest_fit_batch", "issue_consent_receipt", "issue_archive_selection_authorization", "stage_fit_archive", "stage_authorized_full_archive", "validate_feature_summary"]
