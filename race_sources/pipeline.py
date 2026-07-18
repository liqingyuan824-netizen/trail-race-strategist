"""Pipeline for building and replaying race source bundles."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from .constants import (
    CACHE_POLICY_VERSION,
    GENERATOR_VERSION,
    SAFETY_NOTICE,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    SOURCE_POLICY_VERSION,
)
from .extract import parse_official_hudongba, parse_wechat_block, parse_zuicool_event
from .wechat import select_wechat_visual_evidence


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_record(*, source_id: str, source_kind: str, source_url: str, final_url: str, retrieved_at: str, html_path: Path, text_path: Path, meta_path: Path, sha256_hex: str, capture_status: str) -> dict:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "source_url": source_url,
        "final_url": final_url,
        "retrieved_at": retrieved_at,
        "evidence_paths": {
            "html": str(html_path),
            "text": str(text_path),
            "meta": str(meta_path),
        },
        "sha256": sha256_hex,
        "capture_status": capture_status,
    }


def _wechat_visual_evidence(capture: dict) -> list[dict]:
    selection = _wechat_visual_selection(capture)
    return list(selection.get("selected") or [])


def _wechat_visual_selection(capture: dict) -> dict:
    attempts = capture.get("attempts")
    if isinstance(attempts, list) and attempts:
        return select_wechat_visual_evidence(attempts)
    if isinstance(capture.get("images"), list):
        return select_wechat_visual_evidence([capture])
    cached = capture.get("visual_selection")
    if isinstance(cached, dict) and isinstance(cached.get("selected"), list) and isinstance(cached.get("attempts"), list):
        return cached
    return {"selection_status": "no_attempts", "attempt_count": 0, "selected_count": 0, "attempts": [], "selected": []}


def _field_provenance(source_id: str, retrieved_at: str, evidence_path: Path, *, year: int | None, group: str, source_kind: str, note: str) -> dict:
    return {
        "source_id": source_id,
        "retrieved_at": retrieved_at,
        "applicable_year": year,
        "applicable_group": group,
        "source_kind": source_kind,
        "evidence_path": str(evidence_path),
        "note": note,
    }


def build_race_source_bundle(*, official_capture: dict, aggregator_capture: dict | None, wechat_capture: dict | None, replay_mode: bool = False) -> dict:
    official_text = Path(official_capture["text_path"]).read_text(encoding="utf-8")
    official = parse_official_hudongba(official_text)
    aggregator = parse_zuicool_event(Path(aggregator_capture["text_path"]).read_text(encoding="utf-8")) if aggregator_capture else None
    wechat = parse_wechat_block(Path(wechat_capture["text_path"]).read_text(encoding="utf-8")) if wechat_capture else None

    generated_at = _utc_now()
    group = official["group_name"]
    year = official["year"]
    source_records = [
        _source_record(
            source_id="hudongba_official",
            source_kind="official",
            source_url=official_capture["source_url"],
            final_url=official_capture["final_url"],
            retrieved_at=official_capture["retrieved_at"],
            html_path=Path(official_capture["html_path"]),
            text_path=Path(official_capture["text_path"]),
            meta_path=Path(official_capture["meta_path"]),
            sha256_hex=official_capture["sha256"],
            capture_status=official_capture["capture_status"],
        )
    ]
    if aggregator_capture:
        source_records.append(
            _source_record(
                source_id="zuicool_event",
                source_kind="third_party_aggregator",
                source_url=aggregator_capture["source_url"],
                final_url=aggregator_capture["final_url"],
                retrieved_at=aggregator_capture["retrieved_at"],
                html_path=Path(aggregator_capture["html_path"]),
                text_path=Path(aggregator_capture["text_path"]),
                meta_path=Path(aggregator_capture["meta_path"]),
                sha256_hex=aggregator_capture["sha256"],
                capture_status=aggregator_capture["capture_status"],
            )
        )
    if wechat_capture:
        visual_selection = _wechat_visual_selection(wechat_capture)
        wechat_kind = "official" if wechat_capture.get("capture_status") == "article_accessible" else "blocked_official"
        source_records.append(
            _source_record(
                source_id="wechat_article",
                source_kind=wechat_kind,
                source_url=wechat_capture["source_url"],
                final_url=wechat_capture["final_url"],
                retrieved_at=wechat_capture["retrieved_at"],
                html_path=Path(wechat_capture["html_path"]),
                text_path=Path(wechat_capture["text_path"]),
                meta_path=Path(wechat_capture["meta_path"]),
                sha256_hex=wechat_capture["sha256"],
                capture_status=wechat_capture["capture_status"],
            )
        )
        source_records[-1]["visual_evidence"] = list(visual_selection.get("selected") or [])
        source_records[-1]["visual_attempts"] = list(visual_selection.get("attempts") or [])
        source_records[-1]["visual_selection"] = visual_selection

    facts = {
        "official_name": official["official_name"],
        "year": year,
        "group_code": official["group_code"],
        "group_name": group,
        "route_version": official["route_version"],
        "route_version_note": official["route_version_note"],
        "event_date": official["event_date"],
        "venue": official["venue"],
        "route_text": official["route_text"],
        "course_map": official["course_map"],
        "elevation_map": official["elevation_map"],
        "cp": official["cp"],
        "support_rules": official["support_rules"],
        "mandatory_equipment": official["mandatory_equipment"],
        "free_supply": official["free_supply"],
        "private_supply_rule": official["private_supply_rule"],
        "total_distance_km": aggregator["total_distance_km"] if aggregator else None,
        "total_elevation_gain_m": aggregator["total_elevation_gain_m"] if aggregator else None,
        "total_elevation_loss_m": aggregator["total_elevation_loss_m"] if aggregator else None,
        "start_time": aggregator["start_time"] if aggregator else None,
        "cutoff_time": aggregator["cutoff_time"] if aggregator else None,
        "cutoff_hours": aggregator["cutoff_hours"] if aggregator else None,
        "itra_points": aggregator["itra_points"] if aggregator else None,
        "wechat_blocked": wechat_capture.get("capture_status") != "article_accessible" if wechat_capture else None,
        "wechat_capture_status": wechat_capture.get("capture_status") if wechat_capture else None,
        "wechat_visual_evidence": _wechat_visual_evidence(wechat_capture) if wechat_capture else [],
        "wechat_visual_attempts": list(_wechat_visual_selection(wechat_capture).get("attempts") or []) if wechat_capture else [],
    }

    field_sources = {
        "official_name": [
            _field_provenance("hudongba_official", official_capture["retrieved_at"], Path(official_capture["html_path"]), year=year, group=group, source_kind="official", note="赛事名称字段"),
        ],
        "year": [
            _field_provenance("hudongba_official", official_capture["retrieved_at"], Path(official_capture["html_path"]), year=year, group=group, source_kind="official", note="由赛事名称解析"),
        ],
        "group_name": [
            _field_provenance("hudongba_official", official_capture["retrieved_at"], Path(official_capture["html_path"]), year=year, group=group, source_kind="official", note="30公里组别对应破楼兰30KM"),
        ],
        "route_version": [
            _field_provenance("hudongba_official", official_capture["retrieved_at"], Path(official_capture["html_path"]), year=year, group=group, source_kind="official", note="页面仅见暂拟描述，未见正式版本号"),
        ],
        "route_text": [
            _field_provenance("hudongba_official", official_capture["retrieved_at"], Path(official_capture["html_path"]), year=year, group=group, source_kind="official", note="官方规程页路线文字"),
        ],
        "total_distance_km": [
            _field_provenance("zuicool_event", aggregator_capture["retrieved_at"], Path(aggregator_capture["html_path"]), year=year, group=group, source_kind="third_party_aggregator", note="最酷赛事页汇总"),
        ] if aggregator_capture else [],
        "total_elevation_gain_m": [
            _field_provenance("zuicool_event", aggregator_capture["retrieved_at"], Path(aggregator_capture["html_path"]), year=year, group=group, source_kind="third_party_aggregator", note="最酷赛事页汇总"),
        ] if aggregator_capture else [],
        "total_elevation_loss_m": [
            _field_provenance("zuicool_event", aggregator_capture["retrieved_at"], Path(aggregator_capture["html_path"]), year=year, group=group, source_kind="third_party_aggregator", note="最酷赛事页汇总"),
        ] if aggregator_capture else [],
        "start_time": [
            _field_provenance("zuicool_event", aggregator_capture["retrieved_at"], Path(aggregator_capture["html_path"]), year=year, group=group, source_kind="third_party_aggregator", note="最酷赛事页汇总"),
        ] if aggregator_capture else [],
        "cutoff_time": [
            _field_provenance("zuicool_event", aggregator_capture["retrieved_at"], Path(aggregator_capture["html_path"]), year=year, group=group, source_kind="third_party_aggregator", note="最酷赛事页汇总"),
        ] if aggregator_capture else [],
        "cutoff_hours": [
            _field_provenance("zuicool_event", aggregator_capture["retrieved_at"], Path(aggregator_capture["html_path"]), year=year, group=group, source_kind="third_party_aggregator", note="最酷赛事页汇总"),
        ] if aggregator_capture else [],
        "itra_points": [
            _field_provenance("zuicool_event", aggregator_capture["retrieved_at"], Path(aggregator_capture["html_path"]), year=year, group=group, source_kind="third_party_aggregator", note="最酷赛事页汇总"),
        ] if aggregator_capture else [],
        "support_rules": [
            _field_provenance("hudongba_official", official_capture["retrieved_at"], Path(official_capture["html_path"]), year=year, group=group, source_kind="official", note="官方援助与非官方援助规则"),
        ],
        "mandatory_equipment": [
            _field_provenance("hudongba_official", official_capture["retrieved_at"], Path(official_capture["html_path"]), year=year, group=group, source_kind="official", note="竞赛装备清单"),
        ],
        "wechat_blocked": [
            _field_provenance("wechat_article", wechat_capture["retrieved_at"], Path(wechat_capture["html_path"]), year=year, group=group, source_kind="blocked_official", note="微信公众平台环境验证受限"),
        ] if wechat_capture else [],
    }

    unavailable_fields = [
        "course_map",
        "elevation_map",
        "cp",
        "official_aid_station_list",
        "route_version",
    ]
    warnings = [
        "official route text only provides a provisional route; no formal route version string was confirmed",
        "course map and elevation map were not confirmed from accessible first-party evidence",
    ]
    if wechat_capture and _wechat_visual_selection(wechat_capture).get("attempts"):
        selection = _wechat_visual_selection(wechat_capture)
        if selection.get("selected"):
            warnings.append("official WeChat route images captured; every valid正文图 has structured visual review state and suspected route maps block CP completion until reviewed")
        else:
            warnings.append("official WeChat image attempts were retained but no content-valid final image was selected; suspected route maps require explicit review")
    elif wechat and wechat.get("blocked"):
        warnings.append("wechat article remained behind environment verification; no bypass attempted")

    cache_key = "|".join(
        [
            "race_source_bundle",
            str(year),
            group,
            "route_version=null",
            "official=hudongba/3op57",
            "aggregator=zuicool/58473",
        ]
    )

    bundle = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "generator_version": GENERATOR_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "cache_policy_version": CACHE_POLICY_VERSION,
        "safety_notice": SAFETY_NOTICE,
        "cache_key": cache_key,
        "event": {
            "official_name": official["official_name"],
            "year": year,
            "group_code": official["group_code"],
            "group_name": group,
            "route_version": official["route_version"],
            "route_version_note": official["route_version_note"],
            "facts": facts,
            "field_sources": field_sources,
            "unavailable_fields": unavailable_fields,
            "warnings": warnings,
            "visual_evidence": _wechat_visual_evidence(wechat_capture) if wechat_capture else [],
            "visual_evidence_attempts": list(_wechat_visual_selection(wechat_capture).get("attempts") or []) if wechat_capture else [],
            "visual_selection": _wechat_visual_selection(wechat_capture) if wechat_capture else {},
        },
        "sources": source_records,
        "diagnostics": {
            "replay_mode": replay_mode,
            "source_count": len(source_records),
            "partial_reasons": [x for x in unavailable_fields if x],
        },
    }
    return bundle


def replay_race_source_bundle(*, evidence_dir: Path) -> dict:
    official_capture = {
        "source_url": "https://party.hudongba.com/party/3op57.html",
        "final_url": "https://party.hudongba.com/party/3op57.html",
        "retrieved_at": _utc_now(),
        "html_path": evidence_dir / "hudongba_html.html",
        "text_path": evidence_dir / "hudongba_html.txt",
        "meta_path": evidence_dir / "hudongba_html.meta.json",
        "sha256": sha256((evidence_dir / "hudongba_html.html").read_bytes()).hexdigest(),
        "capture_status": "ok",
    }
    aggregator_capture = {
        "source_url": "https://zuicool.com/event/58473",
        "final_url": "https://zuicool.com/event/58473",
        "retrieved_at": _utc_now(),
        "html_path": evidence_dir / "zuicool_event.html",
        "text_path": evidence_dir / "zuicool_event.txt",
        "meta_path": evidence_dir / "zuicool_event.meta.json",
        "sha256": sha256((evidence_dir / "zuicool_event.html").read_bytes()).hexdigest(),
        "capture_status": "ok",
    }
    wechat_capture = {
        "source_url": "https://mp.weixin.qq.com/s/yz9Ls9jR7f-pebr3kt0GSw",
        "final_url": "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=HDRpVGqjILWHpet5X8Aw7_pNr3ro9safBILWcIdN&target_url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Fyz9Ls9jR7f-pebr3kt0GSw",
        "retrieved_at": _utc_now(),
        "html_path": evidence_dir / "wechat_block.html",
        "text_path": evidence_dir / "wechat_block.txt",
        "meta_path": evidence_dir / "wechat_block.meta.json",
        "sha256": sha256((evidence_dir / "wechat_block.html").read_bytes()).hexdigest(),
        "capture_status": "blocked",
    }
    return build_race_source_bundle(
        official_capture=official_capture,
        aggregator_capture=aggregator_capture,
        wechat_capture=wechat_capture,
        replay_mode=True,
    )
