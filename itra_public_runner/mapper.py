"""Map parsed page facts into the stable output schema and classify uncertainty."""

from __future__ import annotations

from .models import base_result


def map_profile(parsed: dict, *, name: str, runner_id: str, retrieved_at: str, evidence: list[str]) -> dict:
    out = base_result(name, runner_id, retrieved_at)
    out["identity"].update(parsed["identity"])
    out["performance"].update(parsed["performance"])
    out["race_results"] = parsed["race_results"]
    out["evidence"] = evidence
    actual_id = out["identity"]["runner_id"]
    if actual_id != str(runner_id):
        out["status"] = "needs_user_selection"
        out["diagnostics"]["partial_reasons"].append("profile_runner_id_mismatch")
        return out
    out["identity"]["match_method"] = "runner_id_exact"
    required = {
        "identity.name": out["identity"]["name"],
        "identity.profile_url": out["identity"]["profile_url"],
        "performance.general_pi": out["performance"]["general_pi"],
        "race_results": out["race_results"],
    }
    missing = [key for key, value in required.items() if value in (None, [], "")]
    locked_scores = sum(r["race_score_access"] == "locked" for r in out["race_results"])
    if locked_scores:
        out["unavailable_fields"].append("race_results[].race_score (subscriber-locked)")
        out["warnings"].append(
            f"{locked_scores} race-score cells display DNF inside subscription-lock markup; treated as locked placeholders, not result status."
        )
    out["unavailable_fields"].append("category_performance_indices (not mapped from current capture)")
    if missing:
        out["diagnostics"]["partial_reasons"].extend(f"missing:{x}" for x in missing)
    out["diagnostics"]["partial_reasons"].append("subscriber_locked_fields") if locked_scores else None
    out["status"] = "partial" if out["diagnostics"]["partial_reasons"] else "success"
    return out
