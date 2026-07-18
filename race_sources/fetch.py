"""Source fetching and evidence capture helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


@dataclass(slots=True)
class SourceCapture:
    source_id: str
    source_kind: str
    source_url: str
    final_url: str
    retrieved_at: str
    html_path: Path
    text_path: Path
    meta_path: Path
    sha256: str
    capture_status: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_text(html: str) -> str:
    return " ".join(html.split())


def capture_url(
    url: str,
    evidence_dir: Path,
    *,
    source_id: str,
    source_kind: str,
    timeout: int = 30,
) -> SourceCapture:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = _utc_now()
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
        final_url = resp.geturl()
        status = getattr(resp, "status", 200)
    capture_status = "blocked" if "captcha" in html.lower() or "环境异常" in html else "ok"
    html_path = evidence_dir / f"{source_id}.html"
    text_path = evidence_dir / f"{source_id}.txt"
    meta_path = evidence_dir / f"{source_id}.meta.json"
    html_path.write_text(html, encoding="utf-8")
    text_path.write_text(_normalize_text(html), encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "source_url": url,
                "final_url": final_url,
                "retrieved_at": retrieved_at,
                "http_status": status,
                "capture_status": capture_status,
                "sha256": _sha256_bytes(html.encode("utf-8")),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return SourceCapture(
        source_id=source_id,
        source_kind=source_kind,
        source_url=url,
        final_url=final_url,
        retrieved_at=retrieved_at,
        html_path=html_path,
        text_path=text_path,
        meta_path=meta_path,
        sha256=_sha256_bytes(html.encode("utf-8")),
        capture_status=capture_status,
    )
