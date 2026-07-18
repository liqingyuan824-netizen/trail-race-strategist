from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
import json

from race_sources.wechat import (
    _article_image_locator, _capture_lazy_loaded_image, persist_wechat_visual_review,
    preserve_persisted_cp_evidence_rows, preserve_persisted_visual_reviews,
    select_wechat_visual_evidence,
)
from race_strategy.validation import full_cp_evidence_errors, full_cp_evidence_errors_from_manifest


ROOT = Path(__file__).resolve().parents[1]
REAL_REQUEST_EVIDENCE = ROOT / "requests" / "req-20260716T064223Z-b09df52afdf74ef6ad9a8e236057e538" / "race" / "evidence"


def _png(path: Path, *, color: tuple[int, int, int]) -> str:
    width = height = 20
    row_pixels = bytes(color) * width if color == (255, 255, 255) else bytes(color) + bytes((0, 0, 0)) * (width - 1)
    rows = b"".join(b"\x00" + row_pixels for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


def _capture(path: Path, digest: str) -> dict:
    return {
        "source_url": "https://example.test/article",
        "final_url": "https://example.test/article",
        "retrieved_at": "2026-07-16T00:00:00+00:00",
        "images": [{
            "index": 1,
            "source_url": "https://example.test/route-map.png",
            "screenshot_path": str(path),
            "sha256": digest,
        }],
    }


class WeChatVisualEvidenceTests(unittest.TestCase):
    def test_review_is_atomically_persisted_and_survives_candidate_merge(self) -> None:
        with tempfile.TemporaryDirectory(dir="E:\\") as temp:
            image = Path(temp) / "route.png"
            digest = _png(image, color=(20, 40, 80))
            selection = select_wechat_visual_evidence([_capture(image, digest)])
            manifest = Path(temp) / "wechat_article.candidates.manifest.json"
            manifest.write_text(json.dumps({"visual_selection": selection}), encoding="utf-8")
            review = persist_wechat_visual_review(
                manifest, candidate_id="attempt-01-image-01", target_year=2026,
                exact_group="30KM", reviewer_method="visual_inspection",
                review_result="reviewed_no_cp", transcription_status="not_required",
            )
            self.assertEqual(review["screenshot_sha256"], digest)
            persisted = json.loads(manifest.read_text(encoding="utf-8"))
            candidate = persisted["visual_selection"]["attempts"][0]
            self.assertEqual(candidate["visual_review"]["status"], "reviewed_no_cp")
            self.assertEqual(candidate["visual_review"]["exact_group"], "30KM")
            merged = preserve_persisted_visual_reviews(
                persisted, select_wechat_visual_evidence([_capture(image, digest)])
            )
            self.assertEqual(merged["attempts"][0]["visual_review"]["status"], "reviewed_no_cp")

    def test_persisted_cp_rows_are_the_only_manifest_gate_input(self) -> None:
        with tempfile.TemporaryDirectory(dir="E:\\") as temp:
            image = Path(temp) / "route.png"
            digest = _png(image, color=(20, 40, 80))
            selection = select_wechat_visual_evidence([_capture(image, digest)])
            manifest = Path(temp) / "wechat_article.candidates.manifest.json"
            manifest.write_text(json.dumps({"visual_selection": selection}), encoding="utf-8")
            transcription = [
                {"checkpoint_id": "CP1", "name": "CP1", "distance_from_start_km": 0.0, "elevation_gain_m": 0.0, "elevation_loss_m": 0.0, "aid": None, "cutoff": None},
                {"checkpoint_id": "CP2", "name": "CP2", "distance_from_start_km": 5.0, "elevation_gain_m": 10.0, "elevation_loss_m": 5.0, "aid": None, "cutoff": None},
                {"checkpoint_id": "FINISH", "name": "终点", "distance_from_start_km": 10.0, "elevation_gain_m": 0.0, "elevation_loss_m": 20.0, "aid": None, "cutoff": None},
            ]
            persist_wechat_visual_review(
                manifest, candidate_id="attempt-01-image-01", target_year=2026,
                exact_group="30KM", reviewer_method="截图视觉审阅",
                review_result="reviewed_cp_transcribed", transcription_status="completed",
                cp_transcription=transcription,
            )
            persisted = json.loads(manifest.read_text(encoding="utf-8"))
            rows = persisted["cp_evidence_rows"]
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertEqual(row["evidence_tier"], "current_year_official")
                self.assertEqual(row["source_year"], 2026)
                self.assertEqual(row["applicable_group"], "30KM")
                self.assertEqual(row["source_kind"], "official_visual_transcription")
                self.assertEqual(row["visual_transcription"]["raw_sha256"], digest)
            self.assertEqual(full_cp_evidence_errors_from_manifest(persisted, year=2026, group_code="30KM", group_name="30KM"), [])
            merged_selection = preserve_persisted_visual_reviews(persisted, select_wechat_visual_evidence([_capture(image, digest)]))
            merged_rows = preserve_persisted_cp_evidence_rows(persisted, merged_selection)
            self.assertEqual(len(merged_rows), 3)
            merged_manifest = dict(persisted, visual_selection=merged_selection, cp_evidence_rows=merged_rows)
            self.assertEqual(full_cp_evidence_errors_from_manifest(merged_manifest, year=2026, group_code="30KM", group_name="30KM"), [])
            missing_rows = dict(persisted)
            missing_rows.pop("cp_evidence_rows")
            self.assertIn("intermediate_official_cp_required", full_cp_evidence_errors_from_manifest(missing_rows, year=2026, group_code="30KM", group_name="30KM"))

    def test_conversational_claim_without_manifest_review_never_passes_gate(self) -> None:
        candidate = {
            "candidate_id": "route-attempt-01", "suspected_route_map": True,
            "validity_status": "valid", "content_validity": {"status": "valid"},
            "conversation_claim": "I reviewed this map and found CPs",
            "visual_review": {"status": "not_reviewed", "transcription_status": "not_started"},
        }
        errors = full_cp_evidence_errors([], year=2026, group_code="30KM", group_name="30km", visual_candidates=[candidate])
        self.assertIn("suspected_route_map_unreviewed:route-attempt-01", errors)

    def test_locator_matches_source_url_before_dom_position(self) -> None:
        class FakeImages:
            def __init__(self) -> None: self.selected: int | None = None
            def evaluate_all(self, _script: str, source: str) -> list[int]:
                self.source = source
                return [3]
            def nth(self, index: int) -> str:
                self.selected = index
                return f"image-{index}"

        class FakePage:
            def __init__(self) -> None: self.images = FakeImages()
            def locator(self, _selector: str) -> FakeImages: return self.images

        page = FakePage()
        result = _article_image_locator(page, "https://mmbiz.qpic.cn/target", 6)
        self.assertEqual(result, "image-3")
        self.assertEqual(page.images.source, "https://mmbiz.qpic.cn/target")

    def test_lazy_placeholder_retries_until_a_real_image_renders(self) -> None:
        class FakePage:
            def __init__(self) -> None: self.waits: list[int] = []
            def wait_for_timeout(self, milliseconds: int) -> None: self.waits.append(milliseconds)

        class FakeLocator:
            def __init__(self) -> None:
                self.metadata = [
                    {"complete": True, "natural_width": 1, "natural_height": 1, "rendered_width": 300, "rendered_height": 200, "alt": "", "title": ""},
                    {"complete": True, "natural_width": 800, "natural_height": 600, "rendered_width": 300, "rendered_height": 200, "alt": "route", "title": ""},
                ]
                self.scroll_count = 0
            def scroll_into_view_if_needed(self, **_kwargs: object) -> None: self.scroll_count += 1
            def evaluate(self, _script: str) -> dict: return self.metadata.pop(0)
            def screenshot(self, *, path: str, **_kwargs: object) -> None: _png(Path(path), color=(20, 40, 80))

        with tempfile.TemporaryDirectory(dir="E:\\") as temp:
            page = FakePage(); locator = FakeLocator()
            result = _capture_lazy_loaded_image(page, lambda: locator, Path(temp) / "image.png", timeout_ms=4_000)
        self.assertEqual(result["capture_status"], "rendered")
        self.assertEqual(result["lazy_image_status"], "loaded_after_viewport_retry")
        self.assertEqual([item["result"] for item in result["load_attempts"]], ["placeholder_or_not_loaded", "rendered"])
        self.assertEqual(locator.scroll_count, 2)

    def test_lazy_placeholder_never_becomes_an_attachment(self) -> None:
        class FakePage:
            def wait_for_timeout(self, _milliseconds: int) -> None: pass

        class FakeLocator:
            def scroll_into_view_if_needed(self, **_kwargs: object) -> None: pass
            def evaluate(self, _script: str) -> dict:
                return {"complete": True, "natural_width": 1, "natural_height": 1, "rendered_width": 300, "rendered_height": 200, "alt": "", "title": ""}

        with tempfile.TemporaryDirectory(dir="E:\\") as temp:
            result = _capture_lazy_loaded_image(FakePage(), lambda: FakeLocator(), Path(temp) / "image.png", timeout_ms=4_000)
        self.assertEqual(result["capture_status"], "content_invalid")
        self.assertEqual(result["attachment_pipeline_status"], "attachment_not_acquired")
        self.assertEqual(result["lazy_image_status"], "not_loaded_after_viewport_retries")
        self.assertEqual(result["content_validity"]["reason"], "LAZY_IMAGE_NOT_LOADED")
        self.assertEqual(len(result["load_attempts"]), 2)

    @unittest.skipUnless(
        (REAL_REQUEST_EVIDENCE / "wechat_image_07.png").is_file()
        and (REAL_REQUEST_EVIDENCE / "retry-20260716T064500Z" / "wechat_image_07.png").is_file(),
        "real Zhongwei evidence is not present in this checkout",
    )
    def test_real_historical_white_image_is_invalid_but_retry_is_valid(self) -> None:
        white = select_wechat_visual_evidence([{
            "source_url": "https://mp.weixin.qq.com/s/real-history",
            "images": [{
                "index": 7,
                "source_url": "https://mmbiz.qpic.cn/opaque/white",
                "screenshot_path": str(REAL_REQUEST_EVIDENCE / "wechat_image_07.png"),
            }],
        }])
        retry = select_wechat_visual_evidence([{
            "source_url": "https://mp.weixin.qq.com/s/real-history",
            "images": [{
                "index": 7,
                "source_url": "https://mmbiz.qpic.cn/opaque/white",
                "screenshot_path": str(REAL_REQUEST_EVIDENCE / "retry-20260716T064500Z" / "wechat_image_07.png"),
            }],
        }])
        self.assertEqual(white["attempts"][0]["validity_status"], "invalid")
        self.assertEqual(white["attempts"][0]["content_validity"]["reason"], "CONTENT_BLANK_OR_UNIFORM")
        self.assertEqual(retry["attempts"][0]["validity_status"], "valid")

    def test_blank_screenshot_is_not_rendered(self) -> None:
        with tempfile.TemporaryDirectory(dir="E:\\") as temp:
            path = Path(temp) / "blank.png"
            digest = _png(path, color=(255, 255, 255))
            result = select_wechat_visual_evidence([_capture(path, digest)])
            self.assertEqual(result["attempts"][0]["capture_status"], "content_invalid")
            self.assertEqual(result["attempts"][0]["content_validity"]["reason"], "CONTENT_BLANK_OR_UNIFORM")
            self.assertEqual(result["selected_count"], 0)

    def test_retry_selects_valid_candidate_and_retains_both_attempts(self) -> None:
        with tempfile.TemporaryDirectory(dir="E:\\") as temp:
            blank = Path(temp) / "blank.png"
            valid = Path(temp) / "valid.png"
            blank_digest = _png(blank, color=(255, 255, 255))
            valid_digest = _png(valid, color=(20, 40, 80))
            result = select_wechat_visual_evidence([
                _capture(blank, blank_digest),
                _capture(valid, valid_digest),
            ])
            self.assertEqual(result["attempt_count"], 2)
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["selected"][0]["screenshot_path"], str(valid))
            self.assertIn("highest_content_validity_score", result["selected"][0]["selection_reason"])

    def test_suspected_route_map_without_review_is_a_specific_cp_blocker(self) -> None:
        candidate = {
            "candidate_id": "route-attempt-01",
            "suspected_route_map": True,
            "validity_status": "valid",
            "content_validity": {"status": "valid"},
            "visual_review": {"status": "not_reviewed", "transcription_status": "not_started"},
        }
        errors = full_cp_evidence_errors(
            [], year=2026, group_code="20KM", group_name="20km", visual_candidates=[candidate]
        )
        self.assertIn("suspected_route_map_unreviewed:route-attempt-01", errors)
        self.assertNotIn("intermediate_official_cp_required", errors)

    def test_keywordless_mmbiz_body_image_still_enters_review_gate(self) -> None:
        with tempfile.TemporaryDirectory(dir="E:\\") as temp:
            path = Path(temp) / "mmbiz-route.png"
            digest = _png(path, color=(20, 40, 80))
            result = select_wechat_visual_evidence([{
                "source_url": "https://mp.weixin.qq.com/s/keywordless",
                "final_url": "https://mp.weixin.qq.com/s/keywordless",
                "images": [{
                    "index": 7,
                    "source_url": "https://mmbiz.qpic.cn/mmbiz_png/opaque-token/0",
                    "screenshot_path": str(path),
                    "sha256": digest,
                }],
            }])
            candidate = result["selected"][0]
            self.assertFalse(candidate["suspected_route_map"])
            errors = full_cp_evidence_errors(
                [], year=2026, group_code="30KM", group_name="30km",
                visual_candidates=result["attempts"],
            )
            self.assertIn(f"valid_body_image_unreviewed:{candidate['candidate_id']}", errors)


if __name__ == "__main__":
    unittest.main()
