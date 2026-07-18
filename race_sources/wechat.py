"""Evidence-preserving capture for publicly accessible WeChat articles."""
from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

_VERIFICATION_MARKERS = ("wappoc_appmsgcaptcha", "captcha", "环境异常", "完成验证")
_ROUTE_HINTS = ("route", "course", "track", "map", "roadbook", "gpx", "cp", "路线", "赛道", "路书", "爬升", "补给", "关门")

def _utc_now() -> str: return datetime.now(timezone.utc).isoformat()
def _sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _verification_required(*, final_url: str, html: str) -> bool:
    haystack = f"{final_url}\n{html}".lower()
    return any(marker.lower() in haystack for marker in _VERIFICATION_MARKERS)
def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#js_content") or soup.select_one("#js_article") or soup.body
    return " ".join(content.stripped_strings) if content else ""
def _image_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#js_content") or soup.select_one("#js_article") or soup
    result: list[str] = []
    for image in content.select("img"):
        url = image.get("data-src") or image.get("src")
        if url and url not in result: result.append(url)
    return result


def _image_is_suspected_route_map(*values: object) -> bool:
    haystack = " ".join(str(value or "") for value in values).lower()
    return any(hint.lower() in haystack for hint in _ROUTE_HINTS)


def _png_content_stats(path: Path, *, content_fraction: float = 0.70) -> dict[str, Any]:
    """Decode enough of a PNG to reject blank/loading screenshots.

    Playwright emits PNG screenshots.  Keeping this small decoder local avoids
    treating a file's existence as proof that the underlying image rendered.
    """
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return {"status": "invalid", "reason": "UNSUPPORTED_IMAGE_ENCODING"}
    offset = 8
    idat = bytearray()
    width = height = bit_depth = color_type = None
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR" and len(data) >= 13:
            width, height, bit_depth, color_type = struct.unpack(">IIBB", data[:10])
        elif kind == b"IDAT":
            idat.extend(data)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type not in {0, 2, 4, 6} or not idat:
        return {"status": "invalid", "reason": "PNG_PIXEL_DATA_UNREADABLE", "width": width, "height": height}
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    row_bytes = width * channels
    try:
        decoded = zlib.decompress(bytes(idat))
    except zlib.error:
        return {"status": "invalid", "reason": "PNG_PIXEL_DATA_UNREADABLE", "width": width, "height": height}
    if len(decoded) < height * (row_bytes + 1):
        return {"status": "invalid", "reason": "PNG_PIXEL_DATA_TRUNCATED", "width": width, "height": height}

    def paeth(left: int, up: int, upper_left: int) -> int:
        estimate = left + up - upper_left
        distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
        return (left, up, upper_left)[distances.index(min(distances))]

    previous = bytearray(row_bytes)
    non_background = 0
    transparent = 0
    distinct: set[tuple[int, ...]] = set()
    content_height = max(1, min(height, int(height * content_fraction)))
    sample_step = max(1, (width * content_height) // 10_000)
    pixel_index = 0
    for row_index in range(content_height):
        filter_type = decoded[row_index * (row_bytes + 1)]
        source = decoded[row_index * (row_bytes + 1) + 1:(row_index + 1) * (row_bytes + 1)]
        current = bytearray(row_bytes)
        for index, value in enumerate(source):
            left = current[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                current[index] = value
            elif filter_type == 1:
                current[index] = (value + left) & 255
            elif filter_type == 2:
                current[index] = (value + up) & 255
            elif filter_type == 3:
                current[index] = (value + ((left + up) // 2)) & 255
            elif filter_type == 4:
                current[index] = (value + paeth(left, up, upper_left)) & 255
            else:
                return {"status": "invalid", "reason": "PNG_FILTER_UNSUPPORTED", "width": width, "height": height}
        for x in range(width):
            pixel = tuple(current[x * channels:(x + 1) * channels])
            if pixel_index % sample_step == 0:
                distinct.add(pixel)
                alpha = pixel[-1] if color_type in {4, 6} else 255
                if alpha == 0:
                    transparent += 1
                else:
                    rgb = pixel[:3] if color_type in {2, 6} else pixel[:1] * 3
                    if min(rgb) < 245:
                        non_background += 1
            pixel_index += 1
        previous = current
    sampled = max(1, (width * content_height + sample_step - 1) // sample_step)
    non_background_ratio = non_background / sampled
    transparent_ratio = transparent / sampled
    blank = (transparent_ratio > 0.995) or len(distinct) <= 1 or non_background_ratio < 0.001
    return {
        "status": "invalid" if blank else "valid",
        "reason": "CONTENT_BLANK_OR_UNIFORM" if blank else None,
        "width": width,
        "height": height,
        "content_fraction": content_fraction,
        "content_region_height": content_height,
        "sampled_pixels": sampled,
        "non_background_ratio": round(non_background_ratio, 6),
        "transparent_ratio": round(transparent_ratio, 6),
        "distinct_sampled_colors": len(distinct),
    }


def validate_rendered_image(
    path: str | Path | None, *, expected_sha256: str | None = None,
    natural_width: int | float | None = None, natural_height: int | float | None = None,
    load_complete: bool | None = None,
) -> dict[str, Any]:
    """Return content validity for one rendered screenshot, never just file existence."""
    if not path:
        return {"status": "invalid", "reason": "SCREENSHOT_PATH_MISSING"}
    image_path = Path(path)
    if not image_path.is_file():
        return {"status": "invalid", "reason": "SCREENSHOT_FILE_MISSING", "path": str(image_path)}
    if load_complete is False:
        return {"status": "invalid", "reason": "IMAGE_ELEMENT_NOT_LOADED"}
    if natural_width is not None and natural_height is not None:
        try:
            if float(natural_width) <= 1 or float(natural_height) <= 1:
                return {
                    "status": "invalid", "reason": "IMAGE_ELEMENT_PLACEHOLDER",
                    "natural_width": natural_width, "natural_height": natural_height,
                }
        except (TypeError, ValueError):
            return {"status": "invalid", "reason": "IMAGE_ELEMENT_DIMENSIONS_INVALID"}
    digest = _sha256(image_path)
    if expected_sha256 and digest != expected_sha256:
        return {"status": "invalid", "reason": "SCREENSHOT_HASH_MISMATCH", "sha256": digest}
    try:
        stats = _png_content_stats(image_path)
    except OSError:
        return {"status": "invalid", "reason": "SCREENSHOT_READ_FAILED", "sha256": digest}
    stats.update({"sha256": digest, "path": str(image_path)})
    if stats.get("status") == "valid" and (stats.get("width", 0) < 2 or stats.get("height", 0) < 2):
        stats.update({"status": "invalid", "reason": "SCREENSHOT_DIMENSIONS_TOO_SMALL"})
    return stats


def _image_element_metadata(locator: Any) -> dict[str, Any]:
    """Read the image element again after scrolling; do not trust initial DOM state."""
    return dict(locator.evaluate("""img => ({
        complete: img.complete,
        natural_width: img.naturalWidth,
        natural_height: img.naturalHeight,
        rendered_width: img.getBoundingClientRect().width,
        rendered_height: img.getBoundingClientRect().height,
        alt: img.alt || '',
        title: img.title || ''
    })"""))


def _image_element_loaded(metadata: Mapping[str, Any]) -> bool:
    try:
        return bool(metadata.get("complete")) and float(metadata.get("natural_width") or 0) > 1 and float(metadata.get("natural_height") or 0) > 1
    except (TypeError, ValueError):
        return False


def _article_image_locator(page: Any, source_url: str, fallback_index: int) -> Any:
    """Resolve by the extracted URL before falling back to DOM order.

    ``_image_urls`` de-duplicates sources while the DOM selector does not, so
    using only ``nth(index)`` can screenshot the wrong image when an article
    contains a duplicate decorative image.
    """
    images = page.locator("#js_content img, #js_article img")
    try:
        matches = images.evaluate_all(
            """(elements, source) => elements.map((img, index) => ({
                index, source: img.getAttribute('data-src') || img.getAttribute('src') || ''
            })).filter(item => item.source === source).map(item => item.index)""",
            source_url,
        )
        if matches:
            return images.nth(int(matches[0]))
    except PlaywrightError:
        pass
    return images.nth(fallback_index)


def _capture_lazy_loaded_image(
    page: Any, locator_factory: Any, screenshot_path: Path, *, timeout_ms: int,
) -> dict[str, Any]:
    """Scroll a lazy image into view and keep every bounded load attempt.

    WeChat commonly leaves ``data-src`` images as 1x1 placeholders until they
    have spent time in the viewport.  A placeholder is evidence of failure,
    not an attachment.  Re-resolve the locator on every round so a replaced
    DOM image cannot leave us reading stale dimensions.
    """
    rounds = max(2, min(4, max(2, timeout_ms // 2_000)))
    wait_ms = max(250, min(1_000, timeout_ms // (rounds * 2)))
    attempts: list[dict[str, Any]] = []
    last_metadata: dict[str, Any] = {}
    for attempt_number in range(1, rounds + 1):
        attempt: dict[str, Any] = {"attempt": attempt_number, "started_at": _utc_now()}
        try:
            locator = locator_factory()
            locator.scroll_into_view_if_needed(timeout=min(timeout_ms, 5_000))
            page.wait_for_timeout(wait_ms)
            metadata = _image_element_metadata(locator)
            last_metadata = metadata
            attempt.update(metadata)
            if not _image_element_loaded(metadata):
                attempt.update({"result": "placeholder_or_not_loaded", "lazy_image_status": "waiting_for_natural_dimensions"})
                attempts.append(attempt)
                continue
            locator.screenshot(path=str(screenshot_path), timeout=min(timeout_ms, 5_000))
            digest = _sha256(screenshot_path)
            content = validate_rendered_image(
                screenshot_path, expected_sha256=digest,
                natural_width=metadata.get("natural_width"), natural_height=metadata.get("natural_height"),
                load_complete=metadata.get("complete"),
            )
            attempt.update({"result": "rendered" if content.get("status") == "valid" else "screenshot_content_invalid", "screenshot_path": str(screenshot_path), "sha256": digest, "content_validity": content})
            attempts.append(attempt)
            result = {**metadata, "load_attempts": attempts, "screenshot_path": str(screenshot_path), "sha256": digest, "content_validity": content}
            if content.get("status") == "valid":
                result.update({"capture_status": "rendered", "attachment_pipeline_status": "completed", "lazy_image_status": "loaded_after_viewport_retry" if attempt_number > 1 else "loaded"})
            else:
                result.update({"capture_status": "content_invalid", "attachment_pipeline_status": "attachment_parse_failed", "lazy_image_status": "loaded_but_screenshot_invalid"})
            return result
        except PlaywrightError as exc:
            attempt.update({"result": "playwright_error", "error_code": type(exc).__name__})
            attempts.append(attempt)
    return {
        **last_metadata,
        "load_attempts": attempts,
        "capture_status": "content_invalid",
        "attachment_pipeline_status": "attachment_not_acquired",
        "lazy_image_status": "not_loaded_after_viewport_retries",
        "error_code": "LAZY_IMAGE_NOT_LOADED",
        "content_validity": {"status": "invalid", "reason": "LAZY_IMAGE_NOT_LOADED", "attempt_count": len(attempts)},
    }


def _review_state(item: Mapping[str, Any]) -> dict[str, Any]:
    existing = item.get("visual_review")
    if isinstance(existing, Mapping):
        return {
            **dict(existing),
            "status": existing.get("status") or "not_reviewed",
            "reviewed_at": existing.get("reviewed_at"),
            "reviewer_method": existing.get("reviewer_method"),
            "transcription_status": existing.get("transcription_status") or "not_started",
            "cp_evidence_status": existing.get("cp_evidence_status") or "not_reviewed",
        }
    return {
        "status": item.get("review_status") or "not_reviewed",
        "reviewed_at": item.get("reviewed_at"),
        "reviewer_method": item.get("reviewer_method"),
        "transcription_status": item.get("transcription_status") or "not_started",
        "cp_evidence_status": item.get("cp_evidence_status") or "not_reviewed",
    }


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    """Replace a manifest only after its complete JSON has been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _candidate_fingerprint(candidate: Mapping[str, Any]) -> tuple[str, str, str]:
    """Bind a review to the exact captured image, rather than its display order."""
    return (
        str(candidate.get("candidate_id") or ""),
        str(candidate.get("source_url") or ""),
        str(candidate.get("sha256") or ""),
    )


def _cp_evidence_fingerprint(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """Bind persisted CP evidence to the exact reviewed candidate image."""
    visual = row.get("visual_transcription")
    visual = visual if isinstance(visual, Mapping) else {}
    return (
        str(row.get("candidate_id") or visual.get("candidate_id") or ""),
        str(row.get("source_url") or visual.get("candidate_source_url") or ""),
        str(
            row.get("screenshot_sha256")
            or visual.get("screenshot_sha256")
            or visual.get("raw_sha256")
            or ""
        ),
    )


def _year_value(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def build_cp_evidence_rows(review: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize one persisted visual review into standard CP evidence rows.

    The row keeps the transcriber-supplied fields, while the candidate-level
    source, screenshot path and screenshot hash are written from the review
    that was actually validated by ``persist_wechat_visual_review``.  Aid-only
    rows are deliberately excluded: an aid station is not an official CP row.
    """
    raw_rows = review.get("cp_transcription")
    if not isinstance(raw_rows, list):
        return []
    target_year = _year_value(review.get("target_year"))
    exact_group = review.get("exact_group")
    candidate_id = str(review.get("candidate_id") or "")
    candidate_source_url = str(review.get("source_url") or "")
    candidate_retrieved_at = str(review.get("retrieved_at") or "")
    screenshot_path = str(review.get("screenshot_path") or "")
    screenshot_sha256 = str(review.get("screenshot_sha256") or "")
    rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(raw_rows, start=1):
        if not isinstance(raw_row, Mapping):
            continue
        row = dict(raw_row)
        point_type = str(row.get("point_type") or "").lower()
        checkpoint_id = str(row.get("checkpoint_id") or row.get("cp_id") or "")
        if point_type in {"support_station", "aid_station", "sp"} or checkpoint_id.upper().startswith("SP"):
            continue
        transcribed_source_url = str(row.get("source_url") or candidate_source_url)
        transcribed_retrieved_at = str(row.get("retrieved_at") or candidate_retrieved_at)
        raw_sha256 = str(
            row.get("raw_sha256")
            or row.get("screenshot_sha256")
            or screenshot_sha256
        )
        applicable_year = _year_value(
            row.get("applicable_year") or row.get("target_year") or target_year
        )
        applicable_group = row.get("applicable_group") or row.get("exact_group") or exact_group
        parser_method = str(
            row.get("parser_method")
            or row.get("transcription_method")
            or review.get("reviewer_method")
            or ""
        )
        visual_transcription = {
            "source_url": transcribed_source_url,
            "candidate_source_url": candidate_source_url,
            "retrieved_at": transcribed_retrieved_at,
            "raw_sha256": raw_sha256,
            "applicable_year": applicable_year,
            "applicable_group": applicable_group,
            "parser_method": parser_method,
            "candidate_id": candidate_id,
            "screenshot_path": screenshot_path,
            "screenshot_sha256": screenshot_sha256,
        }
        standard_row = dict(row)
        standard_row.update(
            {
                "transcription_index": index,
                "candidate_id": candidate_id,
                "source_url": candidate_source_url,
                "retrieved_at": candidate_retrieved_at,
                "screenshot_path": screenshot_path,
                "screenshot_sha256": screenshot_sha256,
                "evidence_tier": "current_year_official",
                "source_year": _year_value(row.get("source_year") or applicable_year),
                "applicable_year": applicable_year,
                "applicable_group": applicable_group,
                "source_kind": "official_visual_transcription",
                "visual_transcription": visual_transcription,
            }
        )
        rows.append(standard_row)
    return rows


def preserve_persisted_cp_evidence_rows(
    previous_manifest: Mapping[str, Any], selection: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Keep CP rows only when the same valid screenshot survives a merge."""
    previous_rows = previous_manifest.get("cp_evidence_rows")
    if not isinstance(previous_rows, list):
        return []
    current_candidates = {
        _candidate_fingerprint(item): item
        for item in selection.get("attempts", [])
        if isinstance(item, Mapping) and item.get("validity_status") == "valid"
    }
    retained: list[dict[str, Any]] = []
    for raw_row in previous_rows:
        if not isinstance(raw_row, Mapping):
            continue
        candidate = current_candidates.get(_cp_evidence_fingerprint(raw_row))
        if not isinstance(candidate, Mapping):
            continue
        review = candidate.get("visual_review")
        if not isinstance(review, Mapping):
            continue
        if review.get("status") not in {"reviewed_cp_transcribed", "completed"}:
            continue
        if review.get("transcription_status") != "completed":
            continue
        if str(raw_row.get("screenshot_sha256") or "") != str(candidate.get("sha256") or ""):
            continue
        retained.append(dict(raw_row))
    return retained


def persist_wechat_visual_review(
    manifest_path: str | Path,
    *,
    candidate_id: str,
    target_year: int | str,
    exact_group: str,
    reviewer_method: str,
    review_result: str,
    transcription_status: str,
    cp_transcription: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Atomically record one visual review in the request's authoritative manifest.

    A conversational claim is deliberately not an input to CP validation.  This
    entrypoint requires the candidate's saved screenshot and hash, then writes
    the review into both the all-attempts and selected views before returning.
    """
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    selection = payload.get("visual_selection")
    if not isinstance(selection, Mapping):
        raise ValueError("wechat_visual_selection_missing")
    attempts = selection.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("wechat_visual_attempts_missing")
    target = next((item for item in attempts if isinstance(item, Mapping) and item.get("candidate_id") == candidate_id), None)
    if not isinstance(target, Mapping):
        raise ValueError(f"wechat_candidate_not_found:{candidate_id}")
    if target.get("validity_status") != "valid":
        raise ValueError(f"wechat_candidate_not_valid:{candidate_id}")
    screenshot = Path(str(target.get("screenshot_path") or ""))
    expected_sha = str(target.get("sha256") or "")
    retrieved_at = str(target.get("retrieved_at") or "")
    if not retrieved_at:
        raise ValueError(f"wechat_candidate_retrieved_at_missing:{candidate_id}")
    validity = validate_rendered_image(screenshot, expected_sha256=expected_sha)
    if validity.get("status") != "valid":
        raise ValueError(f"wechat_candidate_attachment_invalid:{candidate_id}")
    if review_result not in {"reviewed", "reviewed_no_cp", "reviewed_cp_transcribed", "completed"}:
        raise ValueError("wechat_review_result_invalid")
    if transcription_status not in {"not_required", "completed"}:
        raise ValueError("wechat_transcription_status_invalid")
    if review_result in {"reviewed_cp_transcribed", "completed"} and not cp_transcription:
        raise ValueError("wechat_cp_transcription_required")
    review = {
        "status": review_result,
        "candidate_id": candidate_id,
        "source_url": str(target.get("source_url") or ""),
        "retrieved_at": retrieved_at,
        "screenshot_path": str(screenshot),
        "screenshot_sha256": expected_sha,
        "target_year": target_year,
        "exact_group": exact_group,
        "reviewer_method": reviewer_method,
        "review_result": review_result,
        "reviewed_at": _utc_now(),
        "transcription_status": transcription_status,
        "cp_evidence_status": "transcribed" if cp_transcription else "no_cp",
        "cp_transcription": [dict(row) for row in cp_transcription or []],
    }
    target["visual_review"] = review
    target["transcription_status"] = transcription_status
    fingerprint = _candidate_fingerprint(target)
    for collection_name in ("selected",):
        collection = selection.get(collection_name)
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, Mapping) and _candidate_fingerprint(item) == fingerprint:
                    item["visual_review"] = dict(review)
                    item["transcription_status"] = transcription_status
    history = payload.setdefault("visual_review_history", [])
    if isinstance(history, list):
        history.append({"candidate_id": candidate_id, "reviewed_at": review["reviewed_at"], "screenshot_sha256": expected_sha})
    payload["visual_selection"] = dict(selection)
    if review_result in {"reviewed_cp_transcribed", "completed"}:
        cp_rows = build_cp_evidence_rows(review)
        if not cp_rows:
            raise ValueError("wechat_cp_evidence_rows_empty")
        target_fingerprint = _candidate_fingerprint(target)
        existing_rows = payload.get("cp_evidence_rows")
        if not isinstance(existing_rows, list):
            existing_rows = []
        payload["cp_evidence_rows"] = [
            row for row in existing_rows
            if not isinstance(row, Mapping) or _cp_evidence_fingerprint(row) != target_fingerprint
        ] + cp_rows
    elif isinstance(payload.get("cp_evidence_rows"), list):
        target_fingerprint = _candidate_fingerprint(target)
        payload["cp_evidence_rows"] = [
            row for row in payload["cp_evidence_rows"]
            if not isinstance(row, Mapping) or _cp_evidence_fingerprint(row) != target_fingerprint
        ]
    _atomic_json_write(path, payload)
    return review


def preserve_persisted_visual_reviews(previous_manifest: Mapping[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    """Carry only exact-image, already-persisted reviews into a later merge."""
    previous_selection = previous_manifest.get("visual_selection")
    if not isinstance(previous_selection, Mapping):
        return selection
    previous_attempts = previous_selection.get("attempts")
    if not isinstance(previous_attempts, list):
        return selection
    reviews = {
        _candidate_fingerprint(item): dict(item.get("visual_review") or {})
        for item in previous_attempts
        if isinstance(item, Mapping) and (item.get("visual_review") or {}).get("status") not in {None, "", "not_reviewed"}
    }
    if not reviews:
        return selection
    for collection_name in ("attempts", "selected"):
        collection = selection.get(collection_name)
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, Mapping) and _candidate_fingerprint(item) in reviews:
                    item["visual_review"] = dict(reviews[_candidate_fingerprint(item)])
                    item["transcription_status"] = item["visual_review"].get("transcription_status")
    return selection


def select_wechat_visual_evidence(captures: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Unify all article attempts and select the best valid candidate per image slot."""
    attempts: list[dict[str, Any]] = []
    for attempt_index, capture in enumerate(captures, start=1):
        article_url = str(capture.get("source_url") or capture.get("final_url") or "")
        for image_index, raw_item in enumerate(capture.get("images") or [], start=1):
            item = dict(raw_item)
            for path_key in ("screenshot_path", "html_path", "text_path", "manifest_path"):
                if isinstance(item.get(path_key), Path):
                    item[path_key] = str(item[path_key])
            candidate_id = f"attempt-{attempt_index:02d}-image-{int(item.get('index') or image_index):02d}"
            content = item.get("content_validity")
            if not isinstance(content, Mapping):
                content = validate_rendered_image(
                    item.get("screenshot_path"), expected_sha256=item.get("sha256"),
                    natural_width=item.get("natural_width"), natural_height=item.get("natural_height"),
                    load_complete=item.get("complete"),
                )
            else:
                content = dict(content)
            valid = content.get("status") == "valid"
            source_url = str(item.get("source_url") or "")
            suspected = bool(item.get("suspected_route_map")) or _image_is_suspected_route_map(
                source_url, item.get("alt"), item.get("title"), item.get("label"), item.get("nearby_text")
            )
            candidate = {
                **item,
                "candidate_id": candidate_id,
                "attempt_index": attempt_index,
                "logical_key": f"{article_url}#image-{int(item.get('index') or image_index)}",
                "retrieved_at": item.get("retrieved_at") or capture.get("retrieved_at"),
                "content_validity": content,
                "capture_status": "rendered" if valid else "content_invalid",
                "validity_status": "valid" if valid else "invalid",
                "suspected_route_map": suspected,
                "visual_review": _review_state(item),
            }
            attempts.append(candidate)

    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in attempts:
        groups.setdefault(str(candidate["logical_key"]), []).append(candidate)
    selected: list[dict[str, Any]] = []
    for logical_key, candidates in groups.items():
        valid_candidates = [candidate for candidate in candidates if candidate.get("validity_status") == "valid"]
        if not valid_candidates:
            continue
        best = max(
            valid_candidates,
            key=lambda candidate: (
                float((candidate.get("content_validity") or {}).get("non_background_ratio") or 0),
                int((candidate.get("content_validity") or {}).get("width") or 0) * int((candidate.get("content_validity") or {}).get("height") or 0),
                -int(candidate.get("attempt_index") or 0),
            ),
        )
        selected_item = dict(best)
        selected_item["selection_reason"] = (
            f"selected_valid_candidate_for_{logical_key}; all_attempts_preserved; "
            "highest_content_validity_score"
        )
        selected.append(selected_item)
    selected.sort(key=lambda item: (str(item.get("logical_key")), str(item.get("candidate_id"))))
    suspected = [item for item in attempts if item.get("suspected_route_map")]
    return {
        "selection_status": "selected" if selected else "no_valid_candidates",
        "selection_reason": "all_attempts_retained_and_valid_candidates_selected_per_image_slot",
        "attempt_count": len(attempts),
        "selected_count": len(selected),
        "attempts": attempts,
        "selected": selected,
        "suspected_route_map_count": len(suspected),
        "unreviewed_suspected_route_map_count": sum(
            1 for item in suspected
            if (item.get("visual_review") or {}).get("status") in {None, "", "not_reviewed"}
        ),
    }

@dataclass(slots=True)
class WeChatCapture:
    source_url: str; final_url: str; retrieved_at: str; capture_status: str; title: str | None
    html_path: Path; text_path: Path; manifest_path: Path; page_screenshot_path: Path | None
    page_screenshot_sha256: str | None; html_sha256: str; images: list[dict[str, Any]]; error_code: str | None = None
    visual_selection: dict[str, Any] = field(default_factory=dict)

def capture_wechat_article(url: str, evidence_dir: Path, *, timeout_ms: int = 15_000) -> WeChatCapture:
    """Use a normal browser context; never spoof identity or bypass verification."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = _utc_now(); html_path = evidence_dir / "wechat_article.html"; text_path = evidence_dir / "wechat_article.txt"
    manifest_path = evidence_dir / "wechat_article.manifest.json"; page_screenshot_path = evidence_dir / "wechat_page.png"
    html = ""; final_url = url; title: str | None = None; images: list[dict[str, Any]] = []; error_code: str | None = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True); page = browser.new_page()
            try:
                page.goto(url, wait_until="commit", timeout=timeout_ms); page.wait_for_timeout(1_000)
                final_url = page.url; title = page.title() or None; html = page.content()
                page.screenshot(path=str(page_screenshot_path), full_page=True, timeout=timeout_ms)
                for index, source_url in enumerate(_image_urls(html), start=1):
                    record: dict[str, Any] = {
                        "index": index, "source_url": source_url, "capture_status": "not_rendered",
                        "suspected_route_map": _image_is_suspected_route_map(source_url),
                    }
                    try:
                        screenshot_path = evidence_dir / f"wechat_image_{index:02d}.png"
                        record.update(_capture_lazy_loaded_image(
                            page,
                            lambda: _article_image_locator(page, source_url, index - 1),
                            screenshot_path,
                            timeout_ms=timeout_ms,
                        ))
                    except PlaywrightError as exc:
                        record.update({
                            "capture_status": "content_invalid",
                            "attachment_pipeline_status": "attachment_not_acquired",
                            "lazy_image_status": "capture_error",
                            "error_code": type(exc).__name__,
                            "content_validity": {"status": "invalid", "reason": type(exc).__name__},
                        })
                    images.append(record)
            finally: browser.close()
    except PlaywrightError as exc: error_code = type(exc).__name__
    html_path.write_text(html, encoding="utf-8"); text_path.write_text(_visible_text(html), encoding="utf-8")
    capture_status = "human_verification_required" if _verification_required(final_url=final_url, html=html) else "browser_capture_failed" if error_code else "empty_response" if not html else "article_accessible"
    capture = WeChatCapture(url, final_url, retrieved_at, capture_status, title, html_path, text_path, manifest_path, page_screenshot_path if page_screenshot_path.exists() else None, _sha256(page_screenshot_path) if page_screenshot_path.exists() else None, _sha256(html_path), images, error_code)
    capture.visual_selection = select_wechat_visual_evidence([asdict(capture)])
    manifest_path.write_text(json.dumps(asdict(capture), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return capture
