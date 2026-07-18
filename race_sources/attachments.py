"""Structured parsers for captured race attachments."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6_371_000.0
    lat1, lon1 = map(math.radians, a); lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1; dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def parse_gpx(path: Path) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    track_points: list[tuple[float, float, float | None]] = []
    waypoints: list[dict[str, Any]] = []
    for node in root.iter():
        local = node.tag.rsplit("}", 1)[-1]
        if local not in {"trkpt", "rtept", "wpt"}:
            continue
        lat = float(node.attrib["lat"]); lon = float(node.attrib["lon"])
        ele_node = next((child for child in node if child.tag.rsplit("}", 1)[-1] == "ele"), None)
        name_node = next((child for child in node if child.tag.rsplit("}", 1)[-1] == "name"), None)
        ele = float(ele_node.text) if ele_node is not None and ele_node.text else None
        if local == "wpt":
            waypoints.append({"name": name_node.text if name_node is not None else None, "lat": lat, "lon": lon, "elevation_m": ele})
        else:
            track_points.append((lat, lon, ele))
    distance = gain = loss = 0.0
    for prev, current in zip(track_points, track_points[1:]):
        distance += _haversine_m((prev[0], prev[1]), (current[0], current[1]))
        if prev[2] is not None and current[2] is not None:
            delta = current[2] - prev[2]; gain += max(delta, 0.0); loss += max(-delta, 0.0)
    return {
        "parse_status": "parsed", "parser_method": "gpx_xml", "raw_sha256": file_sha256(path),
        "track_point_count": len(track_points), "distance_km": round(distance / 1000, 3),
        "elevation_gain_m": round(gain), "elevation_loss_m": round(loss), "waypoints": waypoints,
        "cp_rows": [], "warning": "Named GPX waypoints are not official CPs without group-bound evidence.",
    }


def parse_html_tables(path: Path) -> dict[str, Any]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    tables = []
    for table in soup.find_all("table"):
        rows = [[" ".join(cell.get_text(" ", strip=True).split()) for cell in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        rows = [row for row in rows if row]
        if rows:
            tables.append(rows)
    return {"parse_status": "parsed" if tables else "no_structured_table", "parser_method": "html_table", "raw_sha256": file_sha256(path), "tables": tables}


def bind_visual_transcription(path: Path, transcription: Mapping[str, Any]) -> dict[str, Any]:
    digest = file_sha256(path)
    if transcription.get("raw_sha256") != digest:
        return {"parse_status": "attachment_parse_failed", "error_code": "VISUAL_TRANSCRIPTION_HASH_MISMATCH", "raw_sha256": digest}
    rows = transcription.get("cp_rows")
    if not isinstance(rows, list) or len(rows) < 2:
        return {"parse_status": "attachment_parse_failed", "error_code": "VISUAL_CP_ROWS_INCOMPLETE", "raw_sha256": digest}
    return {
        "parse_status": "parsed", "parser_method": str(transcription.get("parser_method") or "agent_visual_transcription"),
        "raw_sha256": digest, "cp_rows": rows, "route_version": transcription.get("route_version"),
        "applicable_year": transcription.get("applicable_year"), "applicable_group": transcription.get("applicable_group"),
        "notes": list(transcription.get("notes") or []),
    }


def parse_attachment(path: Path, *, visual_transcription: Mapping[str, Any] | None = None) -> dict[str, Any]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".gpx": return parse_gpx(path)
        if suffix in {".html", ".htm"}: return parse_html_tables(path)
        if suffix == ".json":
            return {"parse_status": "parsed", "parser_method": "structured_json", "raw_sha256": file_sha256(path), "payload": json.loads(path.read_text(encoding="utf-8-sig"))}
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}:
            if visual_transcription is None:
                return {"parse_status": "attachment_parse_failed", "error_code": "VISUAL_PARSE_REQUIRED", "raw_sha256": file_sha256(path)}
            return bind_visual_transcription(path, visual_transcription)
        return {"parse_status": "attachment_parse_failed", "error_code": "UNSUPPORTED_ATTACHMENT_TYPE", "raw_sha256": file_sha256(path)}
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        return {"parse_status": "attachment_parse_failed", "error_code": type(exc).__name__.upper(), "raw_sha256": file_sha256(path) if path.is_file() else None}
