from __future__ import annotations

import base64
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
import unittest

from wearable_ingest.fit_adapter import FitDecodeError, parse_garmin_fit
from wearable_ingest.pipeline import DeleteError, IngestError, delete_request, ingest_fit, ingest_fit_batch


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "wearable" / "synthetic_success.fit.b64"


def make_fit(*, start: int = 100000, include_gps: bool = True, include_hr: bool = True, missing_required: bool = False, elapsed_ms: int = 3_600_000, ascent_raw: int = 800) -> bytes:
    def definition(global_no: int, fields: list[tuple[int, int, int]]) -> bytes:
        return bytes([0x40, 0, 0]) + struct.pack("<H", global_no) + bytes([len(fields)]) + b"".join(bytes(field) for field in fields)
    fields = [(2, 4, 0x86), (7, 4, 0x86), (9, 4, 0x86), (21, 2, 0x84)]
    values = [struct.pack("<I", start), struct.pack("<I", elapsed_ms), struct.pack("<I", 1500000), struct.pack("<H", ascent_raw)]
    if missing_required:
        fields.pop(2)
        values.pop(2)
    if include_hr:
        fields.append((16, 1, 2))
        values.append(bytes([150]))
    body = definition(18, fields) + b"\x00" + b"".join(values)
    if include_gps:
        body += definition(20, [(0, 4, 0x86), (1, 4, 0x86)]) + b"\x00" + struct.pack("<II", 123, 456)
    return bytes([14, 0x10, 0, 0]) + struct.pack("<I", len(body)) + b".FIT" + b"\x00\x00" + body


def make_compressed_timestamp_fit(*, malformed: bool = False) -> bytes:
    """Build a synthetic FIT stream with a compressed session timestamp."""
    def definition(local: int, global_no: int, fields: list[tuple[int, int, int]]) -> bytes:
        return bytes([0x40 | local, 0, 0]) + struct.pack("<H", global_no) + bytes([len(fields)]) + b"".join(bytes(field) for field in fields)

    prior_timestamp = 100000
    session_timestamp = prior_timestamp + 9
    record_fields = [(253, 4, 0x86)]
    session_fields = [(253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (9, 4, 0x86), (21, 2, 0x84), (16, 1, 2)]
    body = definition(0, 20, record_fields) + b"\x00" + struct.pack("<I", prior_timestamp)
    body += definition(1, 18, session_fields)
    body += bytes([0x80 | (1 << 5) | (session_timestamp & 0x1F)])
    payload = struct.pack("<IIIHB", prior_timestamp, 3_600_000, 1500000, 800, 150)
    body += payload[:-1] if malformed else payload
    return bytes([14, 0x10, 0, 0]) + struct.pack("<I", len(body)) + b".FIT" + b"\x00\x00" + body


def write_consent(root: Path, request_id: str = "wearable-req-test-1") -> Path:
    receipt = {"schema_name": "wearable_consent_receipt", "schema_version": "1.0.0", "receipt_id": "wearable-consent-test-1", "request_id": request_id, "consented_at": "2026-07-24T00:00:00Z", "created_at": "2026-07-24T00:00:00Z", "subject_private_alias": "synthetic_test", "data_owner_alias": "synthetic_test", "privacy_mode": "local_private", "source_brand": "garmin", "allowed_data_window": {"start_date": "1989-01-01", "end_date": "2030-12-31"}, "allowed_purposes": ["derived_training_features", "readiness_advice"], "revocation_method": "request_id_deletion", "consent_scope": {"local_fit_import": True, "derived_training_features": True, "readiness_advice": True, "allow_model_research": False}, "retention": {"raw_fit_retention_days": 90, "derived_feature_retention_days": 365, "delete_by_request_id_supported": True}, "governance": {"user_facing_prediction_allowed": False}}
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    receipt["immutable_receipt_hash"] = hashlib.sha256(canonical).hexdigest()
    path = root / "consent.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def resign_consent(receipt: dict) -> None:
    unsigned = {key: value for key, value in receipt.items() if key != "immutable_receipt_hash"}
    receipt["immutable_receipt_hash"] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


class WearableW1IngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.private = Path(self.temp.name) / "private"
        self.private.mkdir()
        self.consent = write_consent(self.private)
        self.source = self.private / "synthetic.fit"
        self.source.write_bytes(base64.b64decode(FIXTURE.read_text(encoding="ascii")))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_success_creates_request_bound_private_artifacts(self) -> None:
        result = ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        request = Path(result["request_dir"])
        self.assertEqual(request.name, "wearable-req-test-1")
        self.assertEqual(result["request_id"], "wearable-req-test-1")
        self.assertTrue((request / "raw" / "activity.fit").is_file())
        normalized = json.loads((request / "normalized" / "activity.json").read_text(encoding="utf-8"))
        self.assertEqual(normalized["request_id"], result["request_id"])
        self.assertEqual(normalized["distance_km"], 15.0)
        self.assertNotIn("gps_points", normalized)
        summary = json.loads((request / "derived" / "feature_summary.json").read_text(encoding="utf-8"))
        self.assertFalse(summary["governance"]["user_facing_prediction_allowed"])

    def test_dry_run_does_not_write(self) -> None:
        result = ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent, dry_run=True)
        self.assertTrue(result["no_files_written"])
        self.assertFalse((self.private / "wearable-imports").exists())

    def test_cli_dry_run_does_not_write(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "wearable_ingest", "ingest", "--source", str(self.source), "--private-root", str(self.private), "--consent-file", str(self.consent), "--dry-run"],
            check=True, capture_output=True, text=True,
        )
        self.assertTrue(json.loads(completed.stdout)["no_files_written"])
        self.assertFalse((self.private / "wearable-imports").exists())

    def test_bad_file_and_missing_required_fields_fail_closed(self) -> None:
        self.source.write_bytes(b"not a fit")
        with self.assertRaisesRegex(IngestError, "invalid_fit_header"):
            ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        self.source.write_bytes(make_fit(missing_required=True))
        with self.assertRaisesRegex(IngestError, "missing_required_session_fields"):
            ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        self.assertFalse((self.private / "wearable-imports").exists())

    def test_compressed_timestamp_session_is_reconstructed_from_prior_timestamp(self) -> None:
        self.source.write_bytes(make_compressed_timestamp_fit())
        parsed = parse_garmin_fit(self.source)
        self.assertEqual(parsed["started_at_unix"], 100000 + 631065600)
        self.assertEqual(parsed["distance_km"], 15.0)
        self.assertEqual(parsed["average_heart_rate_bpm"], 150.0)
        self.assertFalse(parsed["gps_present"])

    def test_session_elapsed_time_uses_fit_millisecond_scale(self) -> None:
        self.source.write_bytes(make_fit(elapsed_ms=3_600_000))
        self.assertEqual(parse_garmin_fit(self.source)["duration_seconds"], 3600.0)

    def test_invalid_session_elapsed_time_and_ascent_sentinels_fail_safe(self) -> None:
        self.source.write_bytes(make_fit(ascent_raw=0xFFFF))
        self.assertIsNone(parse_garmin_fit(self.source)["ascent_m"])
        self.source.write_bytes(make_fit(elapsed_ms=0xFFFFFFFF))
        with self.assertRaisesRegex(FitDecodeError, "invalid_session_total_elapsed_time"):
            parse_garmin_fit(self.source)

    def test_malformed_compressed_timestamp_records_fail_closed(self) -> None:
        self.source.write_bytes(make_compressed_timestamp_fit(malformed=True))
        with self.assertRaisesRegex(FitDecodeError, "truncated_compressed_timestamp_data_record"):
            parse_garmin_fit(self.source)
        # A compressed timestamp is not meaningful without a preceding record
        # carrying an explicit timestamp, so the decoder refuses it.
        session_fields = [(253, 4, 0x86), (2, 4, 0x86), (7, 4, 0x86), (9, 4, 0x86)]
        compressed_only_body = (
            bytes([0x41, 0, 0])
            + struct.pack("<H", 18)
            + bytes([len(session_fields)])
            + b"".join(bytes(field) for field in session_fields)
            + bytes([0xA0])
        )
        self.source.write_bytes(bytes([14, 0x10, 0, 0]) + struct.pack("<I", len(compressed_only_body)) + b".FIT" + b"\x00\x00" + compressed_only_body)
        with self.assertRaisesRegex(FitDecodeError, "compressed_timestamp_without_prior_timestamp"):
            parse_garmin_fit(self.source)

    def test_duplicate_hash_is_rejected_with_a_new_request_receipt(self) -> None:
        first = ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        self.consent = write_consent(self.private, request_id="wearable-req-test-2")
        second = ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        self.assertEqual(second["status"], "rejected_duplicate")
        self.assertNotEqual(second["request_id"], first["request_id"])
        self.assertTrue((self.private / "wearable-imports" / second["request_id"] / "receipts" / "import_receipt.json").is_file())

    def test_missing_gps_and_hr_are_explicit_quality_flags_not_raw_samples(self) -> None:
        self.source.write_bytes(make_fit(include_gps=False, include_hr=False))
        result = ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        request = Path(result["request_dir"])
        normalized = json.loads((request / "normalized" / "activity.json").read_text(encoding="utf-8"))
        self.assertFalse(normalized["gps_present"])
        self.assertFalse(normalized["heart_rate_present"])
        summary = json.loads((request / "derived" / "feature_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(set(summary["quality"]["missing_data_flags"]), {"gps_not_present", "heart_rate_not_present"})
        self.assertNotIn("heart_rate_samples", json.dumps(summary))

    def test_utc_date_boundary_is_preserved_without_timezone_guessing(self) -> None:
        fit_epoch = 631065600
        unix = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
        self.source.write_bytes(make_fit(start=unix - fit_epoch))
        result = ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        summary = json.loads((Path(result["request_dir"]) / "derived" / "feature_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["aggregation_window"]["start_date"], "2026-01-01")

    def test_existing_request_and_activity_outside_signed_window_fail_closed(self) -> None:
        ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        with self.assertRaisesRegex(IngestError, "request_id_already_exists"):
            ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        separate = write_consent(self.private, request_id="wearable-req-outside-window")
        receipt = json.loads(separate.read_text(encoding="utf-8"))
        receipt["allowed_data_window"] = {"start_date": "2026-01-01", "end_date": "2026-01-02"}
        resign_consent(receipt)
        separate.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(IngestError, "activity_outside_allowed_data_window"):
            ingest_fit(source=self.source, private_root=self.private, consent_file=separate)

    def test_delete_removes_raw_normalized_derived_and_receipts_then_proves_unreadable(self) -> None:
        result = ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        request = Path(result["request_dir"])
        audit = delete_request(request_id=result["request_id"], private_root=self.private)
        self.assertFalse(audit["derived_data_readable"])
        for folder in ("raw", "normalized", "derived", "receipts"):
            self.assertFalse((request / folder).exists())
        with self.assertRaises(FileNotFoundError):
            (request / "derived" / "feature_summary.json").read_text(encoding="utf-8")
        with self.assertRaisesRegex(DeleteError, "request_already_deleted"):
            delete_request(request_id=result["request_id"], private_root=self.private)

    def test_private_root_is_required_and_source_cannot_escape_it(self) -> None:
        with self.assertRaisesRegex(IngestError, "private_root_must_be_explicit"):
            ingest_fit(source=self.source, private_root=None, consent_file=self.consent)
        outside = Path(self.temp.name) / "outside.fit"
        outside.write_bytes(make_fit())
        with self.assertRaisesRegex(IngestError, "inside_explicit_private_root"):
            ingest_fit(source=outside, private_root=self.private, consent_file=self.consent)

    def test_unauthorized_consent_scope_is_rejected_and_no_sensitive_or_prediction_fields_are_written(self) -> None:
        receipt = json.loads(self.consent.read_text(encoding="utf-8"))
        receipt["consent_scope"]["allow_model_research"] = True
        resign_consent(receipt)
        self.consent.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(IngestError, "consent_scope_not_authorized_for_w1"):
            ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
        self.assertFalse((self.private / "wearable-imports").exists())

    def test_extra_sensitive_consent_property_and_missing_required_property_fail_closed_before_import_root(self) -> None:
        for mutation, expected in (
            (lambda receipt: receipt.__setitem__("password", "not-allowed"), "forbidden_field"),
            (lambda receipt: receipt.pop("receipt_id"), "missing_required_property"),
        ):
            with self.subTest(expected=expected):
                receipt = json.loads(self.consent.read_text(encoding="utf-8"))
                mutation(receipt)
                resign_consent(receipt)
                self.consent.write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaisesRegex(IngestError, expected):
                    ingest_fit(source=self.source, private_root=self.private, consent_file=self.consent)
                self.assertFalse((self.private / "wearable-imports").exists())
                self.consent = write_consent(self.private)

    def test_batch_import_stores_each_qualified_activity_and_one_aggregate(self) -> None:
        second = self.private / "second.fit"
        second.write_bytes(make_fit(start=200000))
        result = ingest_fit_batch(source_paths=[self.source, second], private_root=self.private, consent_file=self.consent)
        request = Path(result["request_dir"])
        self.assertEqual(result["eligible_activity_count"], 2)
        self.assertEqual(result["rejected_file_count"], 0)
        self.assertEqual(len(list((request / "raw").glob("*.fit"))), 2)
        self.assertEqual(len(list((request / "normalized").glob("*.json"))), 2)
        manifest = json.loads((request / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([item["status"] for item in manifest["files"]], ["completed", "completed"])
        summary = json.loads((request / "derived" / "feature_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["aggregation_window"]["source_activity_count"], 2)
        self.assertFalse(summary["governance"]["user_facing_prediction_allowed"])

    def test_batch_mixed_rejections_are_manifested_and_not_aggregated(self) -> None:
        bad = self.private / "bad.fit"
        bad.write_bytes(b"not a fit")
        result = ingest_fit_batch(source_paths=[self.source, bad], private_root=self.private, consent_file=self.consent)
        request = Path(result["request_dir"])
        self.assertEqual(result["eligible_activity_count"], 1)
        self.assertEqual(result["rejected_file_count"], 1)
        manifest = json.loads((request / "manifest.json").read_text(encoding="utf-8"))
        rejected = [item for item in manifest["files"] if item["status"] == "rejected"]
        self.assertEqual(rejected[0]["rejection_reason"], "invalid_fit_header")
        self.assertEqual(len(list((request / "raw").glob("*.fit"))), 1)
        summary = json.loads((request / "derived" / "feature_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["aggregation_window"]["source_activity_count"], 1)

    def test_batch_same_and_cross_request_duplicates_fail_closed(self) -> None:
        second_name_same_bytes = self.private / "copy.fit"
        second_name_same_bytes.write_bytes(self.source.read_bytes())
        first = ingest_fit_batch(source_paths=[self.source, second_name_same_bytes], private_root=self.private, consent_file=self.consent)
        self.assertEqual(first["eligible_activity_count"], 1)
        self.assertEqual(first["files"][1]["rejection_reason"], "duplicate_source_sha256_in_batch")
        later_consent = write_consent(self.private, request_id="wearable-req-batch-later")
        later = ingest_fit_batch(source_paths=[self.source], private_root=self.private, consent_file=later_consent)
        self.assertEqual(later["status"], "no_eligible_activities")
        self.assertEqual(later["files"][0]["rejection_reason"], "duplicate_source_sha256_completed_request")
        self.assertFalse((self.private / "wearable-imports" / "wearable-req-batch-later").exists())

    def test_batch_dry_run_and_deletion_preserve_privacy_boundaries(self) -> None:
        second = self.private / "second.fit"
        second.write_bytes(make_fit(start=200000))
        preview = ingest_fit_batch(source_paths=[self.source, second], private_root=self.private, consent_file=self.consent, dry_run=True)
        self.assertTrue(preview["no_files_written"])
        self.assertEqual(preview["eligible_activity_count"], 2)
        self.assertFalse((self.private / "wearable-imports").exists())
        result = ingest_fit_batch(source_paths=[self.source, second], private_root=self.private, consent_file=self.consent)
        audit = delete_request(request_id=result["request_id"], private_root=self.private)
        self.assertEqual(set(audit["deleted_categories"]), {"raw", "normalized", "derived", "receipts"})
        self.assertFalse((Path(result["request_dir"]) / "raw").exists())


if __name__ == "__main__":
    unittest.main()
