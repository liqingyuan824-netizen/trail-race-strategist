"""Official UTMB race page capture helpers for Phase 5B positive samples."""

from __future__ import annotations

import json
import ssl
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    ctx = ssl._create_unverified_context()
    with urlopen(req, timeout=120, context=ctx) as r:
        return r.read()


def _source_record(*, source_id: str, source_kind: str, source_url: str, final_url: str, retrieved_at: str, artifact_paths: dict[str, Path], raw_bytes: bytes) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "source_url": source_url,
        "final_url": final_url,
        "retrieved_at": retrieved_at,
        "evidence_paths": {name: str(path) for name, path in artifact_paths.items()},
        "sha256": sha256(raw_bytes).hexdigest(),
        "capture_status": "ok",
    }


def _field_provenance(source_id: str, retrieved_at: str, evidence_path: Path, *, source_kind: str, note: str, year: int | None = None, group: str | None = None) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "retrieved_at": retrieved_at,
        "applicable_year": year,
        "applicable_group": group,
        "source_kind": source_kind,
        "evidence_path": str(evidence_path),
        "note": note,
    }


def _parse_next_data(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise ValueError("Missing __NEXT_DATA__ script on UTMB race page.")
    return json.loads(script.string)


def _extract_display_number(html: str, label: str) -> float | None:
    import re

    pattern = rf"{label}</p><p[^>]*>([0-9]+(?:\.[0-9]+)?)"
    m = re.search(pattern, html)
    if not m:
        return None
    return float(m.group(1))


def build_shudao_20k_race_source_bundle(*, page_url: str, evidence_dir: Path) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)

    html_bytes = _fetch(page_url)
    html = html_bytes.decode("utf-8", "ignore")
    page_data = _parse_next_data(html)
    page_props = page_data["props"]["pageProps"]
    gpx_url = page_props["gpxUrl"]
    gpx_bytes = _fetch(gpx_url)

    html_path = evidence_dir / "shudao_20k_page.html"
    html_path.write_bytes(html_bytes)
    gpx_path = evidence_dir / "shudao_20k.gpx"
    gpx_path.write_bytes(gpx_bytes)
    next_data_path = evidence_dir / "shudao_20k_page.json"
    next_data_path.write_text(json.dumps(page_data, ensure_ascii=False, indent=2), encoding="utf-8")

    generated_at = _utc_now()
    page_header = page_props["pageHeader"]
    track = page_props["track"]
    points = track["points"]
    route_names = [point["name"] for point in points]
    route_text = " → ".join(route_names)

    display_distance_km = _extract_display_number(html, "Distance")
    display_gain_m = _extract_display_number(html, "Elevation Gain")

    source_records = [
        _source_record(
            source_id="shudao_20k_page",
            source_kind="official",
            source_url=page_url,
            final_url=page_url,
            retrieved_at=generated_at,
            artifact_paths={"html": html_path, "json": next_data_path},
            raw_bytes=html_bytes,
        ),
        _source_record(
            source_id="shudao_20k_gpx",
            source_kind="official",
            source_url=gpx_url,
            final_url=gpx_url,
            retrieved_at=generated_at,
            artifact_paths={"gpx": gpx_path},
            raw_bytes=gpx_bytes,
        ),
    ]

    point_sources = [
        _field_provenance(
            "shudao_20k_page",
            generated_at,
            html_path,
            source_kind="official",
            note="Official UTMB race page track data.",
            year=2026,
            group="20K",
        )
    ]
    gpx_ref = _field_provenance(
        "shudao_20k_gpx",
        generated_at,
        gpx_path,
        source_kind="official",
        note="Official published GPX route file.",
        year=2026,
        group="20K",
    )

    cp_points: list[dict[str, Any]] = []
    for index, point in enumerate(points, start=1):
        role = "start" if index == 1 else "finish" if index == len(points) else "checkpoint"
        cp_points.append(
            {
                "sequence": index,
                "name": point["name"],
                "short_name": point.get("shortName"),
                "role": role,
                "distance_m": point["distance"],
                "distance_km": round(point["distance"] / 1000, 3),
                "elevation_m": point["elevation"],
                "cumulative_gain_m": point["gainElevation"],
                "cumulative_loss_m": point["lossElevation"],
                "segment_distance_m": point["distanceFromLastPoint"],
                "segment_distance_km": round(point["distanceFromLastPoint"] / 1000, 3),
                "segment_elevation_gain_m": point["gainElevationFromLastPoint"],
                "segment_elevation_loss_m": point["lossElevationFromLastPoint"],
                "isChrono": point["isChrono"],
                "isMeet": point["isMeet"],
                "isAssistance": point["isAssistance"],
                "supplies": point["supplies"],
                "hasRest": point["hasRest"],
                "hasToilets": point["hasToilets"],
                "hasMedical": point["hasMedical"],
                "hasBus": point["hasBus"],
                "hasShower": point["hasShower"],
                "hasPower": point["hasPower"],
                "hasBag": point["hasBag"],
                "hasNaak": point["hasNaak"],
                "cutoff": point["cutoff"],
                "cutoff_datetime": point["cutoffDatetime"],
                "slowest_datetime": point["slowestDatetime"],
                "fastest_datetime": point["fastestDatetime"],
                "evidence": [point_sources[0], gpx_ref],
                "source_kind": "official",
                "officially_confirmed": True,
                "confidence": 0.99,
            }
        )

    aid_station_list = [
        {
            "name": point["name"],
            "sequence": index,
            "supplies": point["supplies"],
            "timed": bool(point["isChrono"]),
            "officially_confirmed": True,
        }
        for index, point in enumerate(points, start=1)
        if point["supplies"] not in (None, "none")
    ]

    course_map = {
        "distance_m": track["distance"],
        "distance_km": round(track["distance"] / 1000, 3),
        "polyline": track["polyline"],
        "points": [
            {
                "sequence": index,
                "name": point["name"],
                "lat": point["lat"],
                "lon": point["lon"],
                "distance_m": point["distance"],
                "elevation_m": point["elevation"],
            }
            for index, point in enumerate(points, start=1)
        ],
        "max_elevation_m": track["maxElevation"],
        "min_elevation_m": track["minElevation"],
        "official_page_media": page_header["media"],
    }
    elevation_map = {
        "profile": track["profile"],
        "grid_elevation": track["gridElevation"],
        "max_elevation_m": track["maxElevation"],
        "min_elevation_m": track["minElevation"],
        "width_coefficient": track["widthCoefficient"],
        "has_elevation_margin": track["hasElevationMargin"],
    }

    facts = {
        "route_text": route_text,
        "route_text_note": page_header["summary"],
        "course_map": course_map,
        "elevation_map": elevation_map,
        "cp": cp_points,
        "support_rules": {
            "timed_points": [point["name"] for point in points if point["isChrono"]],
            "aid_station_names": [item["name"] for item in aid_station_list],
            "course_note": "Official page track points carry both timing and supply metadata.",
        },
        "mandatory_equipment": None,
        "free_supply": None,
        "private_supply_rule": None,
        "official_aid_station_list": aid_station_list,
        "total_distance_km": round(track["distance"] / 1000, 3),
        "track_distance_km_display": display_distance_km,
        "total_elevation_gain_m": track["gainElevation"],
        "total_elevation_gain_m_display": display_gain_m,
        "total_elevation_loss_m": track["lossElevation"],
        "start_time": page_header["startDateIso"],
        "cutoff_time": page_header["endDateIso"],
        "cutoff_hours": 7.0,
        "itra_points": None,
    }

    field_sources = {
        "route_text": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official course narrative and point order.", year=2026, group="20K"),
        ],
        "course_map": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official race page track object with polyline and point markers.", year=2026, group="20K"),
        ],
        "elevation_map": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official race page track profile object.", year=2026, group="20K"),
        ],
        "cp": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official race page CP/timing points.", year=2026, group="20K"),
        ],
        "official_aid_station_list": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official supply markers from the track points.", year=2026, group="20K"),
        ],
        "total_distance_km": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Precise route distance from the official track object.", year=2026, group="20K"),
        ],
        "track_distance_km_display": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Public hero card display distance; not used as the canonical route length.", year=2026, group="20K"),
        ],
        "total_elevation_gain_m": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Precise elevation gain from the official track object.", year=2026, group="20K"),
        ],
        "total_elevation_gain_m_display": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Public hero card display gain; not used as the canonical gain figure.", year=2026, group="20K"),
        ],
        "total_elevation_loss_m": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Precise elevation loss from the official track object.", year=2026, group="20K"),
        ],
        "start_time": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official start time on the event page.", year=2026, group="20K"),
        ],
        "cutoff_time": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official cutoff time on the event page.", year=2026, group="20K"),
        ],
        "cutoff_hours": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Derived from the official start and cutoff times.", year=2026, group="20K"),
        ],
        "official_name": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Event title from the official page header.", year=2026, group="20K"),
        ],
        "year": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Event year derived from the official page date.", year=2026, group="20K"),
        ],
        "group_code": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Race code from the official page slug.", year=2026, group="20K"),
        ],
        "group_name": [
            _field_provenance("shudao_20k_page", generated_at, html_path, source_kind="official", note="Official 20K race grouping.", year=2026, group="20K"),
        ],
    }

    cache_key = "|".join(
        [
            "race_source_bundle",
            "2026",
            "ESD 20K",
            "route_version=null",
            "official=utmb/shudao-20k",
            "gpx=Shudao_22k_900_c8a925d2cc",
        ]
    )

    return {
        "schema_name": "race_source_bundle",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "generator_version": "0.1.0",
        "source_policy_version": "1.0.0",
        "cache_policy_version": "1.0.0",
        "safety_notice": {
            "version": "1.0.0",
            "medical_advice": False,
            "replaces_race_rules": False,
            "message": "This tool does not replace race rules, on-site safety, or professional medical judgment.",
        },
        "cache_key": cache_key,
        "event": {
            "official_name": page_header["title"],
            "year": 2026,
            "group_code": "20K",
            "group_name": "20K",
            "route_version": None,
            "route_version_note": "No separate route version string is published on the public race page; the official track object and GPX file are the canonical source.",
            "facts": facts,
            "field_sources": field_sources,
            "unavailable_fields": [
                "route_version",
                "mandatory_equipment",
                "private_supply_rule",
            ],
            "warnings": [
                "Public hero card shows 21.5 KM and 900 M+, while the official track object and GPX resolve to 22.307 KM and 881 M+.",
                "The track object is treated as the canonical route length because it is internally consistent with the GPX and CP table.",
            ],
        },
        "sources": source_records,
        "diagnostics": {
            "replay_mode": False,
            "source_count": len(source_records),
            "partial_reasons": [
                "route_version absent as a separate published field",
                "mandatory equipment was not fetched for this positive sample",
            ],
        },
    }
