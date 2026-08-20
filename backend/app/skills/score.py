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


# Default weights for the five original dimensions (sum to 1.0).
_BASE_WEIGHTS = {
    "skill_match": 0.35,
    "experience_match": 0.2,
    "education_match": 0.15,
    "research_quality": 0.15,
    "experience_quality": 0.15,
}
# Default weight contributed by each new dimension when its requirement is present.
_NEW_DIMENSION_DEFAULT_WEIGHTS = {
    "language_match": 0.1,
    "work_authorization_match": 0.05,
    "location_match": 0.05,
}


# Build a scoring config from a JD parse structured_data, bridging JD requirements
# (skills, languages, visa, location, education, experience) into the scorer contract.
def build_scoring_config_from_jd(
    jd_structured: dict[str, Any],
    *,
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(base_config or {})

    must_skills = [
        item.get("canonical_skill") or item.get("display_name")
        for item in jd_structured.get("must_skills", []) or []
        if isinstance(item, dict) and (item.get("canonical_skill") or item.get("display_name"))
    ]
    preferred_skills = [
        item.get("canonical_skill") or item.get("display_name")
        for item in jd_structured.get("preferred_skills", []) or []
        if isinstance(item, dict) and (item.get("canonical_skill") or item.get("display_name"))
    ]
    config.setdefault("required_skills", must_skills)
    config.setdefault("preferred_skills", preferred_skills)

    experience_req = jd_structured.get("experience_requirement") or {}
    if isinstance(experience_req, dict) and experience_req.get("minimum_years") is not None:
        config.setdefault("target_experience_years", float(experience_req["minimum_years"]))

    education_req = jd_structured.get("education_requirement") or {}
    if isinstance(education_req, dict):
        degree = education_req.get("minimum_degree")
        if degree and degree != "none":
            config.setdefault("target_degrees", [degree])

    language_reqs = jd_structured.get("language_requirements") or []
    if language_reqs:
        config["language_requirements"] = language_reqs

    visa_req = jd_structured.get("visa_requirement") or {}
    if isinstance(visa_req, dict) and visa_req.get("requirement_type"):
        config["visa_requirement"] = visa_req

    jd_location = jd_structured.get("location")
    if isinstance(jd_location, dict) and (jd_location.get("country") or jd_location.get("city")):
        config["location"] = jd_location

    config["weights"] = _build_weights(jd_structured, config.get("weights"))
    config.setdefault("tiers", [])
    config.setdefault("hard_filters", _build_hard_filters(jd_structured, must_skills))
    return config


# Compose effective weights, activating new dimensions only when their requirement is present.
def _build_weights(jd_structured: dict[str, Any], configured: dict[str, Any] | None) -> dict[str, float]:
    weights = dict(_BASE_WEIGHTS)
    if configured:
        weights.update({k: float(v) for k, v in configured.items()})

    active_new: list[str] = []
    if jd_structured.get("language_requirements"):
        active_new.append("language_match")
    visa = jd_structured.get("visa_requirement") or {}
    if isinstance(visa, dict) and visa.get("requirement_type") == "required":
        active_new.append("work_authorization_match")
    if isinstance(jd_structured.get("location"), dict):
        active_new.append("location_match")

    if not active_new:
        return weights

    # Pull weight mass from the original dimensions proportionally to keep sum = 1.0.
    extra_mass = sum(_NEW_DIMENSION_DEFAULT_WEIGHTS[d] for d in active_new)
    base_keys = list(_BASE_WEIGHTS.keys())
    base_total = sum(weights[k] for k in base_keys) or 1.0
    scale = max(0.0, (base_total - extra_mass) / base_total) if base_total > 0 else 0.0
    for k in base_keys:
        weights[k] = round(weights[k] * scale, 4)
    for d in active_new:
        weights[d] = _NEW_DIMENSION_DEFAULT_WEIGHTS[d]
    return weights


# Build hard filters from JD requirements (experience, skills, education).
def _build_hard_filters(jd_structured: dict[str, Any], must_skills: list[str]) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    experience_req = jd_structured.get("experience_requirement") or {}
    if isinstance(experience_req, dict) and experience_req.get("minimum_years") is not None:
        filters["min_experience_years"] = float(experience_req["minimum_years"])
        filters["min_required_skill_hits"] = max(1, len(must_skills) // 2) if must_skills else 0
    if must_skills:
        filters["required_skills"] = must_skills
    education_req = jd_structured.get("education_requirement") or {}
    if isinstance(education_req, dict):
        degree = education_req.get("minimum_degree")
        if degree and degree != "none":
            filters["required_degrees"] = [degree]
    return filters
