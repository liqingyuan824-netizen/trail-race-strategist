from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import unittest

from runner_readiness import build_runner_readiness
from runner_readiness.validation import ValidationError
from wearable_ingest.features import build_feature_summary, validate_feature_summary


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "wearable" / "synthetic_w2_activities.json"


def _answers() -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_name": "runner_readiness_input", "schema_version": "1.0.0", "generated_at": now, "generator_version": "synthetic-w2",
        "mode": "quick", "subject": {"runner_name": "Synthetic Runner", "runner_id": "synthetic-1", "synthetic_fixture": True},
        "default_source": {"source_type": "synthetic_fixture", "captured_at": now, "is_user_self_report": True, "confidence": 0.9, "source_uri": "synthetic://w2"},
        "inputs": {"weekly_km": 40, "weekly_elevation_m": 1000, "continuity_weeks": 4, "longest_session_distance_km": 20, "longest_session_duration_min": 120, "injury_status": "none", "illness_status": "none", "race_goal": "finish safely"},
    }


def _profile() -> dict[str, object]:
    return {
        "schema_name": "runner_profile", "schema_version": "1.0.0", "generated_at": "2026-07-24T00:00:00Z", "generator_version": "synthetic-w2", "safety_notice": {"medical_advice": False},
        "query": {"runner_id": "synthetic-1"}, "identity": {"runner_id": "synthetic-1", "name": "Synthetic Runner"}, "performance": {"general_pi": 400}, "race_results": [], "evidence": ["synthetic://w2-profile"],
    }


class WearableW2Features(unittest.TestCase):
    def setUp(self) -> None:
        self.activities = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.summary = build_feature_summary(self.activities, generated_at="2026-07-24T00:00:00Z", as_of_date=datetime(2026, 7, 24, tzinfo=timezone.utc).date())

    def test_synthetic_aggregate_windows_and_trace(self) -> None:
        self.assertEqual(self.summary["training_load"]["windows"]["7d"]["distance_km"], 35.0)
        self.assertEqual(self.summary["training_load"]["windows"]["28d"]["duration_minutes"], 210.0)
        self.assertEqual(self.summary["training_load"]["maxima"]["longest_activity_distance_km"], 20.0)
        self.assertEqual(self.summary["training_load"]["ratios"]["load_7d_to_28d"], 4.0)
        self.assertEqual(self.summary["training_load"]["ratios"]["long_distance_frequency"], 0.083)
        self.assertEqual(self.summary["source_trace"]["activities"][0]["activity_id"], "wearable-activity-00000000000000000001")
        self.assertEqual({row["import_request_id"] for row in self.summary["source_trace"]["activities"]}, {"wearable-req-synthetic-a", "wearable-req-synthetic-b", "wearable-req-synthetic-c"})
        self.assertFalse(self.summary["governance"]["allow_model_research"])
        self.assertFalse(self.summary["governance"]["user_facing_prediction_allowed"])

    def test_missing_ascent_is_not_fabricated_and_lowers_confidence(self) -> None:
        self.assertIsNone(self.summary["training_load"]["windows"]["7d"]["ascent_m"])
        self.assertLess(self.summary["quality"]["coverage_by_window"]["7d"]["ascent_m"], 1.0)
        self.assertEqual(self.summary["uncertainty"]["level"], "medium")
        self.assertTrue(self.summary["uncertainty"]["reasons"])

    def test_readiness_optional_context_is_read_only_and_does_not_change_health(self) -> None:
        baseline = build_runner_readiness(_profile(), _answers())["current_readiness"]
        with_summary = build_runner_readiness(_profile(), _answers(), wearable_feature_summary=self.summary)["current_readiness"]
        self.assertNotIn("wearable_training_exposure", baseline)
        self.assertEqual(baseline["assessment"]["planning_permission"], with_summary["assessment"]["planning_permission"])
        self.assertEqual(baseline["assessment"]["risk_level"], with_summary["assessment"]["risk_level"])
        exposure = with_summary["wearable_training_exposure"]
        self.assertTrue(exposure["read_only_context"])
        self.assertTrue(exposure["does_not_override_self_report_or_health"])
        self.assertNotIn("prediction", json.dumps(with_summary).lower())

    def test_invalid_or_unlocked_summary_is_rejected(self) -> None:
        invalid = json.loads(json.dumps(self.summary))
        invalid["governance"]["user_facing_prediction_allowed"] = True
        self.assertIn("wearable_summary:governance_not_locked", validate_feature_summary(invalid))
        with self.assertRaisesRegex(ValidationError, "wearable_summary:governance_not_locked"):
            build_runner_readiness(_profile(), _answers(), wearable_feature_summary=invalid)


if __name__ == "__main__":
    unittest.main()
