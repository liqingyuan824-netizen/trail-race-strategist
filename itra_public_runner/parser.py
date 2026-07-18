"""Pure HTML parsing. No navigation and no network access occur here."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


def clean(node: Tag | None) -> str | None:
    if node is None:
        return None
    value = " ".join(node.get_text(" ", strip=True).split())
    return value or None


def parse_number(value: str | None, *, decimal: bool = False):
    if not value:
        return None
    match = re.search(r"[+-]?[\d,]+(?:\.\d+)?", value)
    if not match:
        return None
    number = match.group(0).replace(",", "")
    return float(number) if decimal or "." in number else int(number)


def _label_value(soup: BeautifulSoup, label: str) -> str | None:
    heading = soup.find(lambda tag: isinstance(tag, Tag) and tag.name in {"h5", "p"} and clean(tag) == label)
    if not heading:
        return None
    card = heading.find_parent(class_="general_stats_cards")
    return clean(card.find("h4")) if card else None


def parse_profile(html: str, page_url: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.select_one('link[rel="canonical"]')
    canonical_url = canonical.get("href") if canonical else page_url
    title = clean(soup.select_one("h1")) or clean(soup.select_one("title"))
    body_text = clean(soup) or ""

    runner_id_match = re.search(r"ITRA ID:\s*(\d+)", body_text)
    if not runner_id_match and canonical_url:
        runner_id_match = re.search(r"/(\d+)/?$", canonical_url)
    name = None
    if title:
        name = re.sub(r"^ITRA\s+", "", title).split("|")[0].strip()

    def body_field(label: str) -> str | None:
        node = soup.find(string=lambda s: s and re.search(rf"{re.escape(label)}\s*:", s))
        if node:
            value = clean(node.parent)
            match = re.search(rf"{re.escape(label)}\s*:\s*(.+)", value or "")
            return match.group(1).strip() if match else None
        return None

    general_pi = None
    level = None
    pi_heading = soup.find(string=lambda s: s and "ITRA Performance Index" in s)
    if pi_heading:
        region = pi_heading.find_parent()
        for parent in list(region.parents)[:6] if region else []:
            badge = parent.select_one(".badge-number, .performance-index-number, .pi-number")
            if badge and parse_number(clean(badge)) is not None:
                general_pi = parse_number(clean(badge))
                level_node = parent.select_one(".badge-rank")
                level = clean(level_node)
                break
    if general_pi is None:
        meta = soup.select_one('meta[name="description"]')
        match = re.search(r"Performance Index is\s+(\d+)", meta.get("content", "") if meta else "")
        general_pi = int(match.group(1)) if match else None

    races = []
    latest = soup.select_one("#latestResultOverview")
    rows = latest.select("#raceResultsContainer .table-body-row") if latest else []
    for row in rows:
        race_link = row.select_one(".info-col a.dec-info")
        raw_score = clean(row.select_one(".race-score .locked, .race-score"))
        score_cell = row.select_one(".race-score-col")
        locked = bool(score_cell and (score_cell.select_one(".locked") or score_cell.select_one('img[src*="non_subscriber"]')))
        time_value = clean(row.select_one(".race-time-col .table-info"))
        detail = {clean(x.select_one(".title")): clean(x.select_one(".result-table")) for x in row.select(".data-show-hide-table [class*='col-']") if x.select_one(".title")}
        distance_text = clean(row.select_one(".distance-col .table-info"))
        distance_match = re.search(r"([\d.]+)\s*km\s*/\s*([\d,]+)\s*m\+", distance_text or "")
        date_text = clean(row.select_one(".date-col .table-info"))
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", date_text or "")
        status = None
        score = None
        score_access = "locked" if locked else "public"
        if not locked:
            if raw_score and raw_score.upper() in {"DNF", "DNS", "DSQ"} and not time_value:
                status = raw_score.upper()
            elif raw_score:
                score = parse_number(raw_score)
        races.append({
            "date": date_match.group(0) if date_match else None,
            "category": clean(row.select_one(".category-col .table-info")),
            "race": clean(race_link),
            "country": clean(row.select_one(".country-col .table-info")),
            "distance_km": float(distance_match.group(1)) if distance_match else None,
            "elevation_gain_m": int(distance_match.group(2).replace(",", "")) if distance_match else None,
            "endurance_points": parse_number(clean(row.select_one(".badges-col .table-info"))),
            "gender_ranking": parse_number(clean(row.select_one(".ranking-col .table-info"))),
            "race_time": time_value,
            "result_status": status,
            "race_score": score,
            "race_score_access": score_access,
            "race_score_raw_display": raw_score,
            "race_url": urljoin(canonical_url or page_url or "https://itra.run", race_link.get("href")) if race_link else None,
            "details": {
                "total_participants": parse_number(detail.get("Total Participants")),
                "finishers_dnf": detail.get("Finishers / DNF"),
                "gender_ranking": detail.get("Gender Ranking"),
                "age_group_ranking": detail.get("Age Group Ranking"),
                "general_ranking": detail.get("General Ranking"),
            },
            "mapping_warnings": (["race_score_locked_placeholder_not_result_status"] if locked and raw_score else []),
        })

    return {
        "page_title": clean(soup.select_one("title")),
        "identity": {
            "runner_id": runner_id_match.group(1) if runner_id_match else None,
            "name": name,
            "country": (re.search(r"\(([^)]+)\) has an ITRA", soup.select_one('meta[name="description"]').get("content", "")) .group(1) if soup.select_one('meta[name="description"]') and re.search(r"\(([^)]+)\) has an ITRA", soup.select_one('meta[name="description"]').get("content", "")) else None),
            "gender": body_field("Gender"),
            "age_group": body_field("Age Category"),
            "profile_url": canonical_url,
        },
        "performance": {
            "general_pi": general_pi,
            "level": level,
            "category_pi": {},
            "finished_races": parse_number(_label_value(soup, "Finished Races")),
            "total_race_time": _label_value(soup, "Total Race Time"),
            "total_distance_km": parse_number(_label_value(soup, "Total Distance"), decimal=True),
            "total_elevation_m": parse_number(_label_value(soup, "Total Elevation")),
        },
        "race_results": races,
    }
