"""Generic, auditable public race-material acquisition primitives.

Network search is performed by the calling agent. This module owns the
deterministic boundary after a URL is discovered: immutable capture, explicit
errors, attachment discovery, and search-completeness receipts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import ssl
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


REQUIRED_COVERAGE = (
    "official_event_or_regulation",
    "official_registration_or_group_page",
    "route_roadbook_gpx_or_attachment",
    "cp_aid_cutoff_material",
    "official_notice_or_social",
    "timing_or_tracking",
    "historical_route_and_results",
)
ATTACHMENT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".gpx", ".kml", ".zip"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_target_event(value: str) -> dict[str, Any]:
    """Extract only explicit year/group tokens; never invent a selection."""

    text = " ".join(str(value or "").split())
    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", text)
    group_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(km|k|公里)(?![A-Za-z])", text, re.I)
    return {
        "raw": text,
        "year": int(year_match.group(1)) if year_match else None,
        "group": f"{group_match.group(1)}km" if group_match else None,
        "resolution_status": "resolved_from_request" if year_match and group_match else "public_search_required",
        "missing_for_resolution": [
            name for name, present in (("year", year_match), ("group", group_match)) if present is None
        ],
    }


def safe_slug(value: str, *, fallback: str = "source") -> str:
    value = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-.")
    return value[:80] or fallback


@dataclass(slots=True)
class CaptureResult:
    source_id: str
    source_type: str
    coverage: str
    url: str
    final_url: str | None
    retrieved_at: str
    capture_status: str
    error_code: str | None
    http_status: int | None
    content_type: str | None
    raw_path: str | None
    meta_path: str
    sha256: str | None
    applicable_year: int | None
    applicable_group: str | None
    source_tier: str
    parse_status: str
    next_action: str | None


def _error_code(exc: BaseException) -> tuple[str, int | None]:
    if isinstance(exc, HTTPError):
        return f"HTTP_{exc.code}", int(exc.code)
    if isinstance(exc, ssl.SSLError):
        return "TLS_CERTIFICATE_ERROR", None
    if isinstance(exc, TimeoutError):
        return "NETWORK_TIMEOUT", None
    if isinstance(exc, URLError):
        if isinstance(exc.reason, ssl.SSLError):
            return "TLS_CERTIFICATE_ERROR", None
        if isinstance(exc.reason, TimeoutError):
            return "NETWORK_TIMEOUT", None
        return "URL_ERROR", None
    return "FETCH_ERROR", None


def capture_public_url(
    *,
    url: str,
    evidence_dir: Path,
    source_id: str,
    source_type: str,
    coverage: str,
    source_tier: str,
    applicable_year: int | None,
    applicable_group: str | None,
    timeout: int = 45,
) -> CaptureResult:
    """Capture one public URL into unique files without overwriting evidence."""

    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"{stamp}-{safe_slug(source_id)}"
    meta_path = evidence_dir / f"{stem}.meta.json"
    retrieved_at = utc_now()
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (trail-race-strategist; public evidence capture)"})
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            final_url = response.geturl()
            http_status = int(getattr(response, "status", 200))
            content_type = response.headers.get_content_type()
        suffix = Path(urlparse(final_url).path).suffix.lower()
        if not suffix or len(suffix) > 8:
            suffix = ".html" if content_type in {"text/html", "application/xhtml+xml"} else ".bin"
        raw_path = evidence_dir / f"{stem}{suffix}"
        raw_path.write_bytes(raw)
        digest = sha256(raw).hexdigest()
        lower = raw.lower()
        blocked = b"captcha" in lower or "验证码".encode() in raw or "环境异常".encode() in raw
        result = {
            "source_id": source_id, "source_type": source_type, "coverage": coverage, "url": url,
            "final_url": final_url, "retrieved_at": retrieved_at,
            "capture_status": "blocked" if blocked else "acquired",
            "error_code": "HUMAN_VERIFICATION_REQUIRED" if blocked else None,
            "http_status": http_status, "content_type": content_type, "raw_path": str(raw_path),
            "meta_path": str(meta_path), "sha256": digest, "applicable_year": applicable_year,
            "applicable_group": applicable_group, "source_tier": source_tier,
            "parse_status": "not_allowed" if blocked else "not_started",
            "next_action": "search_alternative_public_source" if blocked else "parse_captured_material",
        }
    except (HTTPError, URLError, ssl.SSLError, TimeoutError, OSError) as exc:
        code, status = _error_code(exc)
        result = {
            "source_id": source_id, "source_type": source_type, "coverage": coverage, "url": url,
            "final_url": getattr(exc, "url", None), "retrieved_at": retrieved_at,
            "capture_status": "failed", "error_code": code, "http_status": status,
            "content_type": None, "raw_path": None, "meta_path": str(meta_path), "sha256": None,
            "applicable_year": applicable_year, "applicable_group": applicable_group,
            "source_tier": source_tier, "parse_status": "not_started",
            "next_action": "search_alternative_public_source",
        }
    meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CaptureResult(**result)


def discover_attachments(capture: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_path = capture.get("raw_path")
    if capture.get("capture_status") != "acquired" or not raw_path or Path(raw_path).suffix.lower() not in {".html", ".htm"}:
        return []
    soup = BeautifulSoup(Path(raw_path).read_text(encoding="utf-8", errors="replace"), "html.parser")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    base = str(capture.get("final_url") or capture.get("url"))
    for tag, attr in (("a", "href"), ("img", "src"), ("source", "src")):
        for node in soup.find_all(tag):
            value = node.get(attr)
            if not value:
                continue
            absolute = urljoin(base, str(value))
            suffix = Path(urlparse(absolute).path).suffix.lower()
            label = " ".join(node.get_text(" ", strip=True).split()) or Path(urlparse(absolute).path).name
            if suffix not in ATTACHMENT_SUFFIXES and not re.search(r"路线|路书|赛道|手册|roadbook|route|gpx|cp|关门", label, re.I):
                continue
            if absolute not in seen:
                seen.add(absolute)
                found.append({"url": absolute, "label": label, "suffix": suffix, "status": "attachment_discovered"})
    return found


def build_search_receipt(
    *, request_id: str, event: Mapping[str, Any], attempts: Iterable[Mapping[str, Any]],
    attachments: Iterable[Mapping[str, Any]] = (),
    visual_evidence: Iterable[Mapping[str, Any]] = (),
    visual_attempts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Completion means every required search lane was attempted."""

    attempt_rows = [dict(row) for row in attempts]
    attachment_rows = [dict(row) for row in attachments]
    visual_rows = [dict(row) for row in visual_evidence]
    visual_attempt_rows = [dict(row) for row in visual_attempts]
    attempted = {str(row.get("coverage")) for row in attempt_rows}
    missing = [coverage for coverage in REQUIRED_COVERAGE if coverage not in attempted]
    acquired = [row for row in attempt_rows if row.get("capture_status") == "acquired"]
    failures = [row for row in attempt_rows if row.get("capture_status") in {"failed", "blocked"}]
    pending = [row for row in attachment_rows if row.get("status") in {"attachment_discovered", "attachment_not_acquired", "attachment_parse_failed"}]
    identity_ok = bool(event.get("official_name") and event.get("year") and event.get("group_code"))
    status = "completed" if not missing and not pending else "incomplete"
    return {
        "schema_name": "target_group_capture_receipt", "schema_version": "2.0.0",
        "request_id": request_id, "generated_at": utc_now(), "capture_attempt_status": status,
        "search_completion_status": "completed_with_failures" if not missing and failures else "completed" if not missing else "incomplete",
        "attachment_pipeline_status": "failed" if pending else "completed",
        "error_codes": sorted({
            *(str(row.get("error_code")) for row in failures if row.get("error_code")),
            *("ATTACHMENT_NOT_ACQUIRED" if row.get("status") in {"attachment_discovered", "attachment_not_acquired"} else "ATTACHMENT_PARSE_FAILED" for row in pending),
        }),
        "identity_binding": {
            "status": "verified" if identity_ok else "not_verified", "official_name": event.get("official_name"),
            "year": event.get("year"), "group_code": event.get("group_code"),
            "group_name": event.get("group_name"), "route_version": event.get("route_version"),
        },
        "required_coverage": list(REQUIRED_COVERAGE), "attempted_coverage": sorted(attempted),
        "missing_coverage": missing, "sources": attempt_rows, "attachments": attachment_rows,
        "successful_source_count": len(acquired), "failed_or_blocked_source_count": len(failures),
        "pending_attachment_count": len(pending),
        "visual_evidence": visual_rows,
        "visual_evidence_attempts": visual_attempt_rows,
        "next_actions": [
            *[f"search:{coverage}" for coverage in missing],
            *(["acquire_and_parse_discovered_attachments"] if pending else []),
            *(["retry_failed_lanes_via_alternative_public_sources"] if failures else []),
        ],
    }


def as_record(result: CaptureResult) -> dict[str, Any]:
    return asdict(result)
