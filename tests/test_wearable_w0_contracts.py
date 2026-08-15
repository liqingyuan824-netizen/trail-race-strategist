from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "wearable_ingest" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def property_names(value: object) -> set[str]:
    if isinstance(value, dict):
        names = set(value.get("properties", {}))
        for child in value.values():
            names.update(property_names(child))
        return names
    if isinstance(value, list):
        return set().union(*(property_names(child) for child in value)) if value else set()
    return set()


class WearableW0Contracts(unittest.TestCase):
    def test_consent_receipt_has_w0_envelope_and_research_is_disabled(self) -> None:
        schema = load_schema("consent_receipt.schema.json")
        self.assertEqual(schema["properties"]["schema_name"]["const"], "wearable_consent_receipt")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("immutable_receipt_hash", schema["required"])
        self.assertEqual(schema["properties"]["consent_scope"]["properties"]["allow_model_research"]["const"], False)
        self.assertEqual(schema["properties"]["governance"]["properties"]["user_facing_prediction_allowed"]["const"], False)

    def test_contracts_exclude_raw_sensitive_and_prediction_fields(self) -> None:
        forbidden = {
            "password", "cookie", "oauth_token", "device_serial_number", "external_account_id",
            "gps_points", "heart_rate_samples", "wellness_details", "finish_time_prediction",
            "cp_arrival_time", "prediction_probability",
        }
        all_names = property_names(load_schema("consent_receipt.schema.json")) | property_names(load_schema("wearable_feature_summary.schema.json"))
        self.assertTrue(forbidden.isdisjoint(all_names), sorted(forbidden & all_names))

    def test_feature_summary_allows_only_aggregates_quality_uncertainty_and_locked_governance(self) -> None:
        schema = load_schema("wearable_feature_summary.schema.json")
        self.assertEqual(schema["properties"]["schema_name"]["const"], "wearable_feature_summary")
        self.assertEqual(schema["properties"]["governance"]["properties"]["allow_model_research"]["default"], False)
        self.assertEqual(schema["properties"]["governance"]["properties"]["user_facing_prediction_allowed"]["const"], False)
        self.assertEqual(set(schema["properties"]), {"schema_name", "schema_version", "summary_id", "generated_at", "aggregation_window", "source_trace", "training_load", "quality", "uncertainty", "governance"})
        self.assertFalse(schema["properties"]["training_load"]["properties"]["windows"]["additionalProperties"])
        self.assertFalse(schema["properties"]["training_load"]["properties"]["maxima"]["additionalProperties"])
        self.assertFalse(schema["properties"]["training_load"]["properties"]["ratios"]["additionalProperties"])

    def test_gitignore_protects_real_wearable_data_without_ignoring_fixtures(self) -> None:
        entries = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for required in ("*.fit", "TrailRacePrivateData/", "private/", "*identity_map*.local.json", "wearable-request-receipts/"):
            self.assertIn(required, entries)
        self.assertNotIn("tests/fixtures/", entries)


if __name__ == "__main__":
    unittest.main()
