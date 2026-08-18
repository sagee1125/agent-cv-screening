"""Skill entry point for the Scorer service.

Wraps ScorerService so the REST API and the agent CLI scripts share one path.

TODO(agent-migration): When the REST API is deprecated, merge this module into .codex/skills/scorer/ so the skill becomes self-contained for the integrated agent.
"""
from __future__ import annotations

from typing import Any

from app.core.taxonomy import SkillTaxonomyLoader
from app.services.scorer import ScorerService
from app.services.skill_matcher import SkillMatcherService


def score_candidate_skill(
    extracted_data: dict[str, Any],
    config: dict[str, Any],
    *,
    scorer: ScorerService | None = None,
) -> dict[str, Any]:
    """Score one candidate against a scoring config.

    Args:
        extracted_data: CV Parser structured_data output.
        config: Scoring config (required_skills / weights / tiers / hard_filters ...).
        scorer: Optional injected ScorerService (used by the REST API);
            a default service is built when omitted (used by CLI scripts).
    """
    service = scorer or _build_default_scorer()
    return service.score_candidate(extracted_data, config)


def rank_candidates_skill(
    scored_items: list[dict[str, Any]],
    *,
    scorer: ScorerService | None = None,
) -> list[dict[str, Any]]:
    """Rank scored candidate items by total_score (adds a rank field).

    Args:
        scored_items: Items with candidate_id and total_score.
        scorer: Optional injected ScorerService; a default is built when omitted.
    """
    service = scorer or _build_default_scorer()
    return service.rank(scored_items)


def _build_default_scorer() -> ScorerService:
    taxonomy = SkillTaxonomyLoader("data/taxonomy/skill_taxonomy.yaml")
    taxonomy.load()
    return ScorerService(SkillMatcherService(taxonomy))
