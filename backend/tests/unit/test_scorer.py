from __future__ import annotations

from app.core.taxonomy import SkillTaxonomyLoader
from app.services.scorer import ScorerService
from app.services.skill_matcher import SkillMatcherService


def _scorer() -> ScorerService:
    taxonomy = SkillTaxonomyLoader("data/taxonomy/skill_taxonomy.yaml")
    taxonomy.load()
    return ScorerService(SkillMatcherService(taxonomy))


def test_scorer_has_five_dimensions_and_snapshot_schema() -> None:
    scorer = _scorer()
    extracted = {
        "skills": ["Python", "PyTorch"],
        "education": [{"degree": "硕士"}],
        "experience": [{"start_date": "2021-01", "end_date": "2024-01", "description": "主導千万级项目"}],
        "publications": [{"title": "paper", "journal": "NeurIPS"}],
    }
    config = {
        "required_skills": ["Python", "Machine Learning"],
        "target_experience_years": 2,
        "target_degrees": ["硕士"],
        "weights": {
            "skill_match": 0.3,
            "experience_match": 0.2,
            "education_match": 0.2,
            "research_quality": 0.15,
            "experience_quality": 0.15,
        },
        "tiers": [
            {"name": "Tier 1", "min_score": 85, "max_score": 100},
            {"name": "Tier 2", "min_score": 70, "max_score": 84.99},
            {"name": "Tier 3", "min_score": 50, "max_score": 69.99},
            {"name": "Tier 4", "min_score": 0, "max_score": 49.99},
        ],
    }

    result = scorer.score_candidate(extracted, config)
    dims = result["dimension_scores"]
    assert set(dims.keys()) == {
        "skill_match",
        "experience_match",
        "education_match",
        "research_quality",
        "experience_quality",
    }

    snapshot = result["full_snapshot"]
    assert "dimension_scores" in snapshot
    assert "skill_match_details" in snapshot
    assert "interview_suggestions" in snapshot
    assert snapshot["hard_filter_status"] in {"passed", "failed"}
    assert result["tier"] in {"Tier 1", "Tier 2", "Tier 3", "Tier 4"}


def test_tier_uses_min_max_range_from_config() -> None:
    scorer = _scorer()
    extracted = {"skills": [], "education": [], "experience": [], "publications": []}
    config = {
        "weights": {
            "skill_match": 0.0,
            "experience_match": 0.0,
            "education_match": 0.0,
            "research_quality": 0.0,
            "experience_quality": 0.0,
        },
        "tiers": [
            {"name": "A", "min_score": 90, "max_score": 100},
            {"name": "B", "min_score": 0, "max_score": 89.99},
        ],
    }
    result = scorer.score_candidate(extracted, config)
    assert result["tier"] == "B"
