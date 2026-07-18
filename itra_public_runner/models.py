"""Stable output vocabulary shared by browser, parser, and mapper layers."""

STATUSES = {
    "success",
    "needs_user_selection",
    "not_found",
    "blocked",
    "partial",
    "page_changed",
}


def base_result(name: str, runner_id: str | None, retrieved_at: str) -> dict:
    return {
        "schema_name": "runner_profile",
        "schema_version": "1.0.0",
        "generated_at": retrieved_at,
        "generator_version": "0.1.0",
        "source_policy_version": "1.0.0",
        "cache_policy_version": "1.0.0",
        "status": "partial",
        "source": "ITRA",
        "retrieved_at": retrieved_at,
        "safety_notice": {
            "version": "1.0.0",
            "medical_advice": False,
            "replaces_race_rules": False,
            "message": "This tool does not replace race rules, on-site safety, or professional medical judgment.",
        },
        "query": {"runner_name": name, "runner_id": runner_id},
        "candidates": [],
        "identity": {
            "match_method": None,
            "runner_id": None,
            "name": None,
            "country": None,
            "gender": None,
            "age_group": None,
            "profile_url": None,
        },
        "performance": {
            "general_pi": None,
            "level": None,
            "category_pi": {},
            "finished_races": None,
            "total_race_time": None,
            "total_distance_km": None,
            "total_elevation_m": None,
        },
        "race_results": [],
        "unavailable_fields": [],
        "warnings": [],
        "evidence": [],
        "diagnostics": {"parser_version": "1.0.0", "partial_reasons": []},
    }
