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
        "language_match",
        "work_authorization_match",
        "location_match",
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


def test_scorer_language_match_rewards_meeting_requirements() -> None:
    scorer = _scorer()
    extracted = {
        "skills": [],
        "education": [],
        "experience": [],
        "publications": [],
        "languages": [
            {"language": "English", "level": "fluent"},
            {"language": "Chinese", "level": "native"},
        ],
    }
    config = {
        "language_requirements": [
            {"language": "English", "level": "business", "is_mandatory": True},
        ],
        "weights": {"language_match": 0.1},
    }
    result = scorer.score_candidate(extracted, config)
    assert result["dimension_scores"]["language_match"] == 100.0


def test_scorer_language_match_partial_for_below_level() -> None:
    scorer = _scorer()
    extracted = {
        "skills": [],
        "education": [],
        "experience": [],
        "publications": [],
        "languages": [{"language": "English", "level": "basic"}],
    }
    config = {
        "language_requirements": [
            {"language": "English", "level": "fluent", "is_mandatory": True},
        ],
        "weights": {},
    }
    result = scorer.score_candidate(extracted, config)
    assert result["dimension_scores"]["language_match"] == 50.0


def test_scorer_work_authorization_match_scores() -> None:
    scorer = _scorer()
    base_extracted = {
        "skills": [],
        "education": [],
        "experience": [],
        "publications": [],
    }
    config = {"visa_requirement": {"requirement_type": "required"}, "weights": {}}

    for status, expected in [
        ("citizen", 100.0),
        ("permanent_resident", 100.0),
        ("has_work_permit", 100.0),
        ("requires_sponsorship", 60.0),
        ("unknown", 80.0),
    ]:
        extracted = dict(base_extracted)
        extracted["work_authorization"] = {"status": status}
        result = scorer.score_candidate(extracted, config)
        assert result["dimension_scores"]["work_authorization_match"] == expected


def test_scorer_location_match_scores() -> None:
    scorer = _scorer()
    base_extracted = {
        "skills": [],
        "education": [],
        "experience": [],
        "publications": [],
    }
    config = {
        "location": {"country": "US", "city": "San Francisco"},
        "weights": {},
    }
    for cv_loc, expected in [
        ({"country": "US", "city": "San Francisco"}, 100.0),
        ({"country": "US", "city": "New York"}, 60.0),
        ({"country": "CN", "city": "Beijing"}, 0.0),
    ]:
        extracted = dict(base_extracted)
        extracted["location"] = cv_loc
        result = scorer.score_candidate(extracted, config)
        assert result["dimension_scores"]["location_match"] == expected


def test_scorer_folds_certification_skills_into_match() -> None:
    scorer = _scorer()
    extracted = {
        "skills": [],
        "education": [],
        "experience": [],
        "publications": [],
        "certifications": [
            {"name": "AWS Certified Solutions Architect"},
            {"name": "Microsoft Certified: Azure Developer Associate"},
        ],
    }
    config = {"required_skills": ["aws"], "weights": {}}
    result = scorer.score_candidate(extracted, config)
    hits = result["skill_match_details"]["hit"]
    hit_skills = {h.get("matched_with") for h in hits} if hits and isinstance(hits[0], dict) else set(hits)
    assert "aws" in hit_skills


def test_build_scoring_config_from_jd_activates_new_dimensions() -> None:
    from app.skills.score import build_scoring_config_from_jd

    jd_structured = {
        "must_skills": [{"canonical_skill": "python"}, {"canonical_skill": "aws"}],
        "preferred_skills": [{"canonical_skill": "kubernetes"}],
        "experience_requirement": {"minimum_years": 3},
        "education_requirement": {"minimum_degree": "master"},
        "language_requirements": [{"language": "English", "level": "business", "is_mandatory": True}],
        "visa_requirement": {"requirement_type": "required"},
        "location": {"country": "US", "city": "San Francisco"},
    }
    config = build_scoring_config_from_jd(jd_structured)
    assert config["required_skills"] == ["python", "aws"]
    assert config["preferred_skills"] == ["kubernetes"]
    assert config["target_experience_years"] == 3.0
    assert config["target_degrees"] == ["master"]
    assert config["language_requirements"] == jd_structured["language_requirements"]
    assert config["visa_requirement"] == jd_structured["visa_requirement"]
    assert config["location"] == jd_structured["location"]
    weights = config["weights"]
    assert weights["language_match"] > 0
    assert weights["work_authorization_match"] > 0
    assert weights["location_match"] > 0
    total_weight = sum(weights.values())
    assert abs(total_weight - 1.0) < 0.01
    assert config["hard_filters"]["min_experience_years"] == 3.0
    assert config["hard_filters"]["required_skills"] == ["python", "aws"]


def test_build_scoring_config_from_jd_no_new_requirements_keeps_base_weights() -> None:
    from app.skills.score import build_scoring_config_from_jd

    jd_structured = {
        "must_skills": [{"canonical_skill": "python"}],
    }
    config = build_scoring_config_from_jd(jd_structured)
    weights = config["weights"]
    assert weights.get("language_match", 0) == 0
    assert weights.get("work_authorization_match", 0) == 0
    assert weights.get("location_match", 0) == 0
    assert abs(sum(weights.values()) - 1.0) < 0.01
