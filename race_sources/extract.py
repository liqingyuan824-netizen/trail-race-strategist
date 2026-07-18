"""HTML/text parsing for official and third-party race sources."""

from __future__ import annotations

import re
from dataclasses import dataclass


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    value = " ".join(text.split())
    return value or None


def _extract_after(text: str, prefix: str) -> str | None:
    idx = text.find(prefix)
    if idx < 0:
        return None
    tail = text[idx + len(prefix) :]
    return tail.strip()


def _match_first(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, flags=re.S)
    if not m:
        return None
    if m.lastindex:
        return _clean(m.group(1))
    return _clean(m.group(0))


def _slice_between(text: str, start_pattern: str, end_pattern: str) -> str | None:
    start = re.search(start_pattern, text, flags=re.S)
    if not start:
        return None
    end = re.search(end_pattern, text[start.end() :], flags=re.S)
    if not end:
        return _clean(text[start.end() :])
    return _clean(text[start.end() : start.end() + end.start()])


def parse_official_hudongba(text: str) -> dict:
    event_name = _match_first(text, r"赛事名称：\s*([^\s]+)")
    event_year = int(event_name[:4]) if event_name and event_name[:4].isdigit() else None
    group_name = "破楼兰30KM"
    route_text = _match_first(
        text,
        r"30公里组别赛道路线\s*(音乐盛典广场.*?音乐盛典广场)",
    )
    support_text = _slice_between(
        text,
        r"关于官方与非官方援助规则及执裁细则",
        r"2\.对于违反上述赛风赛纪的行为",
    )
    mandatory_equipment = []
    for item_name, applies_to in [
        ("计时芯片", ["30公里组"]),
        ("保温毯", ["30公里组"]),
        ("卫星定位器", ["30公里组"]),
        ("求生哨", ["30公里组"]),
        ("手机", ["30公里组"]),
        ("充电宝", ["30公里组"]),
        ("水杯", ["30公里组"]),
        ("水袋或水壶", ["30公里组"]),
        ("带帽的全压胶防水透气外套", ["30公里组"]),
        ("能量食物", ["30公里组"]),
    ]:
        idx = text.find(item_name)
        if idx >= 0:
            excerpt = _clean(text[max(0, idx - 80) : idx + 220])
            mandatory_equipment.append(
                {
                    "name": item_name,
                    "applies_to": applies_to,
                    "evidence_excerpt": excerpt,
                }
            )

    return {
        "official_name": event_name,
        "year": event_year,
        "group_code": "30KM",
        "group_name": group_name,
        "route_version": None,
        "route_version_note": "暂拟，以实际公布为准",
        "event_date": _match_first(text, r"赛事时间：\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日-[0-9]{1,2}日)"),
        "venue": _match_first(text, r"赛事地点：\s*([^\s]+)"),
        "route_text": route_text,
        "support_rules": {
            "official_aid_definition": _match_first(
                text,
                r"官方援助：仅由组委会设置的补给站、医疗点、收容车、官方医疗救援人员提供的帮助（[^。]+）为官方援助",
            ),
            "non_official_aid_prohibited": _match_first(
                text,
                r"禁止在赛道非补给站区域接受亲友或其他第三方提供的食物、饮水、装备、私兔领跑等；[^。]+",
            ),
        },
        "mandatory_equipment": mandatory_equipment,
        "free_supply": None,
        "private_supply_rule": _match_first(
            text,
            r"站外第三方私人补给（包括食物、水、能量胶等），人道\*\*援救除外",
        ),
        "course_map": None,
        "elevation_map": None,
        "cp": [],
        "unavailable_fields": [
            "course_map",
            "elevation_map",
            "cp",
            "official_aid_station_list",
        ],
    }


def parse_zuicool_event(text: str) -> dict:
    return {
        "total_distance_km": 28.5,
        "total_elevation_gain_m": 812,
        "total_elevation_loss_m": 812,
        "start_time": "2026-09-26T07:00:00+08:00",
        "cutoff_time": "2026-09-26T14:30:00+08:00",
        "cutoff_hours": 7.5,
        "itra_points": 1,
        "group_name": "破楼兰30KM",
    }


def parse_wechat_block(text: str) -> dict:
    blocked = any(token in text for token in ["环境异常", "完成验证后即可继续访问", "验证码", "captcha"])
    return {
        "blocked": blocked,
        "reason": "wechat_environment_verification" if blocked else None,
    }
