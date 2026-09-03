# Tests deterministic configuration and six-dimension candidate matching behavior.
from __future__ import annotations

import copy
import math

import pytest

from app.services.candidate_matching import (
    DIMENSION_IDS,
    CandidateMatchingService,
    MatchingConfigError,
    build_matching_config,
    match_candidate,
    rank_candidates,
)


# Builds representative current JD parser structured data.
def _jd() -> dict:
    return {
        "must_skills": [
            {"skill_id": "python_1", "canonical_skill": "python", "display_name": "Python", "weight": 2.0},
            {"skill_id": "docker_2", "canonical_skill": "docker", "display_name": "Docker", "weight": 1.0},
        ],
        "preferred_skills": [
            {"skill_id": "aws_1", "canonical_skill": "aws", "display_name": "AWS", "weight": 0.6}
        ],
        "language_requirements": [
            {"language": "English", "level": "business", "is_mandatory": True}
        ],
        "education_requirement": {
            "minimum_degree": "bachelor",
            "field_of_study": "Computer Science",
            "is_mandatory": True,
        },
        "visa_requirement": {
            "requirement_type": "required",
            "target_region": "Hong Kong",
        },
        "experience_requirement": {"minimum_years": 3},
        "jd_overview": {"job_title": "Senior Backend Engineer"},
    }


# Builds representative current CV parser structured data.
def _cv() -> dict:
    return {
        "skills": [
            {"canonical_skill": "python"},
            {"canonical_skill": "aws"},
        ],
        "languages": [{"language": "English", "level": "fluent"}],
        "education": [
            {
                "degree": "BSc",
                "degree_level": "bachelor",
                "major": "Computer Science",
            }
        ],
        "experience": [
            {
                "company": "A",
                "job_title": "Senior Backend Engineer",
                "start_date": "2021-01",
                "end_date": "2024-12",
                "description": "Led Python APIs and reduced latency by 35%.",
                "skills_used": ["python", "aws"],
            }
        ],
        "projects": [],
        "certifications": [],
        "publications": [],
        "work_authorization": {"status": "has_work_permit"},
    }


# Verifies fixed IDs, activation, normalization, and canonical hash stability.
def test_config_is_canonical_and_normalizes_active_weights() -> None:
    first = build_matching_config(_jd())
    reordered = dict(reversed(list(_jd().items())))
    second = build_matching_config(reordered)

    assert tuple(first.config["dimensions"]) == DIMENSION_IDS
    assert first.canonical_json == second.canonical_json
    assert first.config_hash == second.config_hash
    active = [value for value in first.config["dimensions"].values() if value["active"]]
    assert math.isclose(sum(value["normalized_weight"] for value in active), 1.0, abs_tol=1e-9)
    assert len(first.config_hash) == 64


# Verifies duplicate canonical requirements are merged before scoring.
def test_config_merges_duplicate_must_skills() -> None:
    jd = _jd()
    jd["must_skills"].append(
        {"skill_id": "python_duplicate", "canonical_skill": "Python", "weight": 3.0}
    )
    effective = build_matching_config(jd)

    python = next(item for item in effective.config["must_skills"] if item["canonical_skill"] == "python")
    assert python["weight"] == 5.0
    assert len(effective.config["must_skills"]) == 2


# Verifies education is inactive when the JD has no explicit education requirement.
def test_no_education_requirement_returns_inactive_null_dimension() -> None:
    jd = _jd()
    jd["education_requirement"] = {
        "minimum_degree": "none",
        "field_of_study": None,
        "is_mandatory": False,
    }
    effective = build_matching_config(jd)
    result = match_candidate(_cv(), effective, "2026-01-31")
    education = result["radar_dimensions"][3]

    assert effective.config["dimensions"]["education_certification"]["active"] is False
    assert education["score"] is None
    assert education["normalized_weight"] == 0.0


# Verifies explicit matching configuration has precedence over parser defaults.
def test_explicit_config_has_precedence() -> None:
    generated = build_matching_config(_jd()).config
    explicit = copy.deepcopy(generated)
    explicit["dimensions"]["core_skill_match"]["weight"] = 0.9
    explicit["fit_bands"]["high_min"] = 95.0

    effective = build_matching_config(_jd(), explicit_config=explicit)

    assert effective.config["dimensions"]["core_skill_match"]["weight"] == 0.9
    assert effective.config["fit_bands"]["high_min"] == 95.0


# Verifies invalid numeric weights and all-inactive configurations fail clearly.
@pytest.mark.parametrize("weight", [-1.0, float("nan"), float("inf")])
def test_invalid_weights_are_rejected(weight: float) -> None:
    explicit = build_matching_config(_jd()).config
    explicit["dimensions"]["core_skill_match"]["weight"] = weight

    with pytest.raises(MatchingConfigError) as error:
        build_matching_config(_jd(), explicit_config=explicit)

    assert error.value.code == "MATCHING_CONFIG_INVALID"


# Verifies protected attributes cannot enter explicit scoring requirements.
def test_protected_attribute_requirement_is_rejected() -> None:
    explicit = build_matching_config(_jd()).config
    explicit["job_specific_requirements"].append(
        {
            "requirement_id": "forbidden",
            "evaluator_type": "domain",
            "weight": 1.0,
            "mandatory": False,
            "parameters": {"domain": "nationality"},
        }
    )

    with pytest.raises(MatchingConfigError):
        build_matching_config(_jd(), explicit_config=explicit)


# Verifies every score returns six complete radar objects in canonical order.
def test_match_returns_complete_six_dimension_contract() -> None:
    result = match_candidate(_cv(), build_matching_config(_jd()), "2026-01-31")

    assert [item["dimension_id"] for item in result["radar_dimensions"]] == list(DIMENSION_IDS)
    assert set(result["radar_summary"]) == set(DIMENSION_IDS)
    assert 0 <= result["match_score"] <= 100
    assert 0 <= result["evidence_confidence"] <= 100
    assert result["fit_band"] in {"high", "medium", "low"}
    for item in result["radar_dimensions"]:
        assert set(item) >= {
            "active",
            "score",
            "configured_weight",
            "normalized_weight",
            "weighted_points",
            "status",
            "requirements",
            "evidence",
            "gaps",
            "reasoning",
            "confidence",
        }


# Verifies same inputs and reference date produce identical business output.
def test_matching_is_fully_deterministic() -> None:
    service = CandidateMatchingService()
    config = service.build_config(_jd())

    first = service.match(_cv(), config, "2026-01-31")
    second = service.match(copy.deepcopy(_cv()), config, "2026-01-31")

    assert first == second
    assert all(len(item["question_id"]) == 24 for item in first["interview_questions"])


# Verifies approved related skills use strength 0.7 rather than exact strength.
def test_related_skill_strength_is_seventy_percent() -> None:
    jd = _jd()
    jd["must_skills"] = [
        {"skill_id": "postgresql_1", "canonical_skill": "postgresql", "weight": 1.0}
    ]
    cv = _cv()
    cv["skills"] = [{"canonical_skill": "sql"}]
    cv["experience"][0]["skills_used"] = ["sql"]

    result = match_candidate(
        cv,
        build_matching_config(jd),
        "2026-01-31",
        relation_resolver=lambda candidate, required: candidate == "sql" and required == "postgresql",
    )

    core = result["radar_dimensions"][0]
    # v2: presence 70 (related) plus full linkage (sql is in experience skills_used) -> 0.8*70 + 0.2*100.
    assert core["score"] == 76.0
    assert core["evidence"][0]["match_type"] == "related"


# Verifies overlapping relevant jobs are unioned and never double counted.
def test_relevant_experience_unions_overlapping_intervals() -> None:
    cv = _cv()
    cv["experience"] = [
        {
            "job_title": "Backend Engineer",
            "start_date": "2020-01",
            "end_date": "2022-12",
            "description": "Built Python services.",
            "skills_used": ["python"],
        },
        {
            "job_title": "Senior Backend Engineer",
            "start_date": "2021-01",
            "end_date": "2023-12",
            "description": "Led Python platform delivery.",
            "skills_used": ["python"],
        },
    ]

    result = match_candidate(cv, build_matching_config(_jd()), "2026-01-31")
    experience = result["radar_dimensions"][1]

    assert experience["reasoning"]["facts"]["relevant_years"] == 4.0


# Verifies mandatory failures do not erase transparent capability scoring.
def test_eligibility_is_separate_from_capability_score() -> None:
    cv = _cv()
    passed = match_candidate(cv, build_matching_config(_jd()), "2026-01-31")
    cv["work_authorization"] = {"status": "requires_sponsorship"}

    result = match_candidate(cv, build_matching_config(_jd()), "2026-01-31")

    assert result["eligibility"]["status"] == "failed"
    assert result["match_score"] == passed["match_score"]
    work_auth = next(item for item in result["eligibility"]["results"] if item["rule_id"] == "work_authorization")
    assert work_auth["status"] == "not_met"


# Verifies unknown mandatory evidence produces needs_review rather than failure.
def test_unknown_mandatory_evidence_needs_review() -> None:
    cv = _cv()
    cv["work_authorization"] = {"status": "unknown"}

    result = match_candidate(cv, build_matching_config(_jd()), "2026-01-31")

    assert result["eligibility"]["status"] == "needs_review"
    assert result["interview_questions"][0]["template_id"] == "IQ-ELIGIBILITY-001"


# Verifies protected attributes, location, and identity never influence output.
def test_protected_and_location_fields_do_not_affect_matching() -> None:
    config = build_matching_config(_jd())
    base = _cv()
    changed = copy.deepcopy(base)
    changed.update(
        {
            "name": "Different Name",
            "email": "different@example.com",
            "phone": "+1 555 0100",
            "date_of_birth": "1950-01-01",
            "gender": "different",
            "photo": "binary",
            "location": {"country": "Different Country"},
        }
    )

    assert match_candidate(base, config, "2026-01-31") == match_candidate(
        changed, config, "2026-01-31"
    )


# Verifies all questions use approved templates and respect the hard limit.
def test_interview_questions_use_only_fixed_templates() -> None:
    cv = _cv()
    cv["skills"] = []
    cv["experience"] = []
    cv["education"] = []
    cv["languages"] = []
    cv["work_authorization"] = {"status": "unknown"}

    result = match_candidate(cv, build_matching_config(_jd()), "2026-01-31")
    approved = {
        "IQ-SKILL-DEPTH-001",
        "IQ-JD-REQUIREMENT-001",
        "IQ-MISSING-001",
        "IQ-IMPACT-001",
        "IQ-DURATION-001",
        "IQ-SENIORITY-001",
        "IQ-ELIGIBILITY-001",
    }

    assert 3 <= len(result["interview_questions"]) <= 6
    assert {item["template_id"] for item in result["interview_questions"]} <= approved


# Verifies fewer than three questions are allowed when fewer triggers exist.
def test_questions_may_be_below_minimum_when_triggers_are_exhausted() -> None:
    jd = {
        "must_skills": [
            {"skill_id": "python_1", "canonical_skill": "python", "weight": 1.0}
        ],
        "preferred_skills": [],
        "language_requirements": [],
        "education_requirement": {"minimum_degree": "none", "is_mandatory": False},
        "visa_requirement": {"requirement_type": "unknown"},
        "experience_requirement": {},
    }
    cv = {
        "skills": [{"canonical_skill": "python"}],
        "experience": [
            {
                "job_title": "Engineer",
                "start_date": "2025-01",
                "end_date": "Present",
                "description": "Built Python APIs with 20% lower latency.",
                "skills_used": ["python"],
            }
        ],
    }

    result = match_candidate(cv, build_matching_config(jd), "2026-01-31")

    assert len(result["interview_questions"]) < 3


# Verifies eligibility-first ordering, stable IDs, and dense business ties.
def test_ranking_uses_business_order_and_dense_ties() -> None:
    tied_result = match_candidate(_cv(), build_matching_config(_jd()), "2026-01-31")
    failed_result = copy.deepcopy(tied_result)
    failed_result["eligibility"]["status"] = "failed"
    rows = [
        {"candidate_id": "b", **copy.deepcopy(tied_result)},
        {"candidate_id": "c", **failed_result},
        {"candidate_id": "a", **copy.deepcopy(tied_result)},
    ]

    ranked = rank_candidates(rows)

    assert [item["candidate_id"] for item in ranked] == ["a", "b", "c"]
    assert [item["recommendation_rank"] for item in ranked] == [1, 1, 2]


# Verifies certification titles contribute canonical skills such as aws.
def test_certification_name_matches_canonical_must_skill() -> None:
    jd = {
        "must_skills": [{"skill_id": "aws_1", "canonical_skill": "aws", "weight": 1.0}],
        "preferred_skills": [],
        "language_requirements": [],
        "education_requirement": {"minimum_degree": "none", "is_mandatory": False},
        "visa_requirement": {"requirement_type": "unknown"},
        "experience_requirement": {},
    }
    cv = {
        "skills": [],
        "experience": [],
        "education": [],
        "certifications": [{"name": "AWS Certified Data Engineer"}],
        "projects": [],
        "publications": [],
    }
    result = match_candidate(cv, build_matching_config(jd), "2026-01-31")
    assert result["radar_dimensions"][0]["score"] == 100.0


# Verifies compound skill ids are split with the taxonomy token matcher.
def test_compound_skill_token_expands_to_canonical_skill() -> None:
    jd = {
        "must_skills": [{"skill_id": "aws_1", "canonical_skill": "aws", "weight": 1.0}],
        "preferred_skills": [],
        "language_requirements": [],
        "education_requirement": {"minimum_degree": "none", "is_mandatory": False},
        "visa_requirement": {"requirement_type": "unknown"},
        "experience_requirement": {},
    }
    cv = {"skills": [{"canonical_skill": "aws_s3_ec2"}], "experience": [], "education": []}
    result = match_candidate(cv, build_matching_config(jd), "2026-01-31")
    # v2: skill listed only in the free-text skills section counts presence but not linkage.
    assert result["radar_dimensions"][0]["score"] == 80.0


# Verifies job titles and majors can supply taxonomy skill evidence.
def test_job_title_and_major_count_as_skill_evidence() -> None:
    jd = {
        "must_skills": [
            {"skill_id": "python_1", "canonical_skill": "python", "weight": 1.0},
            {"skill_id": "actuarial_1", "canonical_skill": "actuarial_science", "weight": 1.0},
        ],
        "preferred_skills": [],
        "language_requirements": [],
        "education_requirement": {"minimum_degree": "none", "is_mandatory": False},
        "visa_requirement": {"requirement_type": "unknown"},
        "experience_requirement": {},
    }
    cv = {
        "skills": [],
        "experience": [{"job_title": "Python Developer", "description": "", "skills_used": []}],
        "education": [{"major": "Actuarial Studies"}],
    }
    result = match_candidate(cv, build_matching_config(jd), "2026-01-31")
    assert result["radar_dimensions"][0]["score"] == 100.0


# Verifies any listed acceptable major can satisfy the education field component.
def test_education_field_accepts_any_listed_major() -> None:
    jd = _jd()
    jd["education_requirement"]["field_of_study"] = "finance, accounting, actuarial science"
    cv = _cv()
    cv["education"] = [{"degree": "BSc", "degree_level": "bachelor", "major": "Actuarial Studies"}]
    result = match_candidate(cv, build_matching_config(jd), "2026-01-31")
    education = result["radar_dimensions"][3]
    assert education["reasoning"]["facts"]["components"]["field"] == 100.0


# Verifies R&D job titles do not satisfy an R language must-skill.
def test_rd_job_title_does_not_match_r_must_skill() -> None:
    jd = {
        "must_skills": [{"skill_id": "r_1", "canonical_skill": "r", "weight": 1.0}],
        "preferred_skills": [],
        "language_requirements": [],
        "education_requirement": {"minimum_degree": "none", "is_mandatory": False},
        "visa_requirement": {"requirement_type": "unknown"},
        "experience_requirement": {},
    }
    cv = {
        "skills": [],
        "experience": [
            {
                "job_title": "R&D Engineer",
                "description": "Led R&D projects and working papers.",
                "skills_used": [],
            }
        ],
        "education": [],
    }
    result = match_candidate(cv, build_matching_config(jd), "2026-01-31")
    assert result["radar_dimensions"][0]["score"] == 0.0


# Verifies free-text CV prose does not invent computer-vision evidence.
def test_cv_prose_does_not_match_computer_vision_must_skill() -> None:
    jd = {
        "must_skills": [{"skill_id": "cv_1", "canonical_skill": "computer_vision", "weight": 1.0}],
        "preferred_skills": [],
        "language_requirements": [],
        "education_requirement": {"minimum_degree": "none", "is_mandatory": False},
        "visa_requirement": {"requirement_type": "unknown"},
        "experience_requirement": {},
    }
    cv = {
        "skills": [],
        "experience": [
            {
                "job_title": "Research Assistant",
                "description": "Updated the CV and supporting documents for the lab.",
                "skills_used": [],
            }
        ],
        "education": [],
    }
    result = match_candidate(cv, build_matching_config(jd), "2026-01-31")
    assert result["radar_dimensions"][0]["score"] == 0.0
