# Orders candidate match results and assigns deterministic dense business ranks.
from __future__ import annotations

import copy
from typing import Any


_ELIGIBILITY_ORDER = {"passed": 0, "needs_review": 1, "failed": 2}


# Extracts an eligibility status from detail or flattened result shapes.
def _eligibility_status(item: dict[str, Any]) -> str:
    eligibility = item.get("eligibility")
    if isinstance(eligibility, dict):
        return str(eligibility.get("status") or "needs_review")
    return str(item.get("eligibility_status") or "needs_review")


# Reads one radar score from detail or flattened result shapes.
def _radar_score(item: dict[str, Any], dimension_id: str) -> float:
    summary = item.get("radar_summary")
    if isinstance(summary, dict) and summary.get(dimension_id) is not None:
        return float(summary[dimension_id])
    for dimension in item.get("radar_dimensions") or []:
        if isinstance(dimension, dict) and dimension.get("dimension_id") == dimension_id:
            return float(dimension.get("score") or 0.0)
    return 0.0


# Builds the documented business rank tuple without the stable ID fallback.
def _business_key(item: dict[str, Any]) -> tuple[int, float, float, float, float]:
    return (
        _ELIGIBILITY_ORDER.get(_eligibility_status(item), 1),
        -float(item.get("match_score", item.get("total_score", 0.0))),
        -_radar_score(item, "core_skill_match"),
        -_radar_score(item, "relevant_experience"),
        -float(item.get("evidence_confidence", 0.0)),
    )


# Returns copied rows ordered by recommendation with SQL-style dense ranks.
def rank_candidates(scored_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        (copy.deepcopy(item) for item in scored_items),
        key=lambda item: (_business_key(item), str(item.get("candidate_id") or "")),
    )
    previous_key: tuple[int, float, float, float, float] | None = None
    dense_rank = 0
    for item in ordered:
        business_key = _business_key(item)
        if business_key != previous_key:
            dense_rank += 1
            previous_key = business_key
        item["recommendation_rank"] = dense_rank
    return ordered
