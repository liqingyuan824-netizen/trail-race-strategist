"""Candidate selection rules, kept independent from browser mechanics."""

from __future__ import annotations


def select_by_runner_id(candidates: list[dict], runner_id: str) -> tuple[str, dict | None]:
    matches = [item for item in candidates if item and str(item.get("RunnerId")) == str(runner_id)]
    if len(matches) == 1:
        return "matched", matches[0]
    if candidates:
        return "needs_user_selection", None
    return "not_found", None
