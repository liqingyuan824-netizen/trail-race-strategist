from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
import unittest

from race_strategy.fixtures import synthetic_course, synthetic_readiness
from runner_readiness import build_training_preparation_advice
from wearable_ingest.features import build_feature_summary


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "wearable" / "synthetic_w2_activities.json"


def _readiness(*, risk: str = "green", permission: str = "normal_planning_allowed", with_summary: bool = True) -> dict[str, object]:
    readiness = synthetic_readiness(risk_level=risk, permission=permission)
    readiness["cache_key"] = "synthetic-readiness-cache"
    readiness["evidence"] = []
    if with_summary:
        activities = json.loads(FIXTURE.read_text(encoding="utf-8"))
        summary = build_feature_summary(activities, generated_at="2026-07-24T00:00:00Z", as_of_date=date(2026, 7, 24))
        readiness["wearable_training_exposure"] = {
            "summary_id": summary["summary_id"], "generated_at": summary["generated_at"],
            "import_request_ids": sorted({row["import_request_id"] for row in summary["source_trace"]["activities"]}),
            "quality": summary["quality"], "uncertainty": summary["uncertainty"],
            "read_only_context": True, "does_not_override_self_report_or_health": True,
        }
        readiness["evidence"].append({"source_type": "wearable_feature_summary", "source_fingerprint": "synthetic-summary-fingerprint"})
    return readiness


class RestrictedPreparationAdviceTests(unittest.TestCase):
    def test_complete_low_uncertainty_summary_generates_five_conditional_categories(self):
        summary = _readiness()
        summary["wearable_training_exposure"]["uncertainty"] = {"level": "low", "reasons": []}
        output = build_training_preparation_advice(current_readiness=summary, course_model=synthetic_course(label="20K", distance_km=20, gain_m=800, cp_count=4, cutoff_hours=7), generated_at="2026-07-25T00:00:00Z")
        self.assertTrue(output["evidence_gate"]["passed"])
        self.assertEqual({item["category"] for item in output["advice"]}, {"conditional_training_focus", "conditional_load_adjustment", "long_distance_elevation_rehearsal", "fueling_rehearsal", "taper_timing"})
        self.assertEqual(output["estimates"], [])
        self.assertEqual(output["prohibited_output_guards"], {"user_facing_prediction_allowed": False, "finish_prediction_included": False, "cp_timing_included": False})

    def test_missing_summary_is_explicit_and_has_no_fabricated_trace_or_numbers(self):
        output = build_training_preparation_advice(current_readiness=_readiness(with_summary=False), course_model=synthetic_course(label="20K", distance_km=20, gain_m=800, cp_count=4, cutoff_hours=7))
        self.assertEqual(output["facts"]["wearable_summary_status"], "wearable_summary_unavailable")
        self.assertEqual(output["data_sufficiency"]["status"], "insufficient")
        self.assertNotIn("summary_id", output["source_trace"])
        self.assertEqual(len(output["advice"]), 5)

    def test_uncertain_summary_and_restricted_permission_never_recommend_increase(self):
        output = build_training_preparation_advice(current_readiness=_readiness(risk="yellow", permission="conservative_planning_only"), course_model=synthetic_course(label="20K", distance_km=20, gain_m=800, cp_count=4, cutoff_hours=7))
        self.assertEqual(output["safety_gate"]["planning_permission"], "conservative_planning_only")
        self.assertTrue(all("increase" not in item["action"].lower() for item in output["advice"]))

    def test_aggressive_plan_blocked_is_preserved_and_never_escalates(self):
        output = build_training_preparation_advice(current_readiness=_readiness(risk="yellow", permission="aggressive_plan_blocked"), course_model=synthetic_course(label="20K", distance_km=20, gain_m=800, cp_count=4, cutoff_hours=7))
        self.assertEqual(output["safety_gate"]["planning_permission"], "aggressive_plan_blocked")
        self.assertTrue(all("increase" not in item["action"].lower() for item in output["advice"]))
        self.assertIn("Maintain or reduce", output["advice"][1]["action"])

    def test_red_gate_is_not_overridden_and_returns_no_advice(self):
        output = build_training_preparation_advice(current_readiness=_readiness(risk="red", permission="stop_and_seek_professional_assessment"), course_model=synthetic_course(label="20K", distance_km=20, gain_m=800, cp_count=4, cutoff_hours=7))
        self.assertEqual(output["advice"], [])
        self.assertTrue(output["safety_gate"]["wearable_cannot_override"])

    def test_course_evidence_and_capture_fail_closed(self):
        course = synthetic_course(label="20K", distance_km=20, gain_m=800, cp_count=4, cutoff_hours=7)
        course["event"]["target_group_capture"]["identity_binding"]["group_code"] = "50K"
        course["event"]["course"]["cp_model"]["cp_points"] = []
        output = build_training_preparation_advice(current_readiness=_readiness(), course_model=course)
        self.assertFalse(output["evidence_gate"]["passed"])
        self.assertEqual(output["advice"], [])
        self.assertIn("target_group_capture_binding_mismatch", output["evidence_gate"]["failure_codes"])
        self.assertIn("intermediate_official_cp_required", output["evidence_gate"]["failure_codes"])

    def test_serialized_artifact_excludes_sensitive_and_prohibited_terms_except_guard_name(self):
        output = build_training_preparation_advice(current_readiness=_readiness(), course_model=synthetic_course(label="20K", distance_km=20, gain_m=800, cp_count=4, cutoff_hours=7))
        serialized = json.dumps(output, sort_keys=True).lower()
        for forbidden in ("finish_range", "arrival", "departure", "checkpoint", "pace", "activity_id", ".fit", "gps", "hrv", "sleep", "wellness"):
            self.assertNotIn(forbidden, serialized)
        for permitted_guard in ("user_facing_prediction_allowed", "finish_prediction_included"):
            serialized = serialized.replace(permitted_guard, "")
        self.assertNotIn("prediction", serialized)


if __name__ == "__main__":
    unittest.main()
