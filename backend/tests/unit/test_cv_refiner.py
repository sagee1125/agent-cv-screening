# Tests hybrid CV refinement merge logic (no live LLM).
from __future__ import annotations

from cv_parser.refine_merge import merge_cv_refinement


def test_merge_prefers_split_dated_experience() -> None:
    base = {
        "summary": "Profile",
        "skills": ["sql"],
        "experience": [
            {
                "company": "Acme",
                "job_title": "Analyst",
                "description": "5 years experience in data governance and SQL.",
            }
        ],
    }
    refined = {
        "skills": ["sql", "data governance", "microsoft excel"],
        "experience": [
            {
                "company": "Acme",
                "job_title": "Business Analyst",
                "start_date": "2020-01",
                "end_date": "2023-06",
                "description": "Data governance and quality.",
                "skills_used": ["sql"],
            },
            {
                "company": "Beta Corp",
                "job_title": "Data Specialist",
                "start_date": "2023-07",
                "end_date": "Present",
                "description": "Metadata and profiling.",
                "skills_used": ["data governance"],
            },
        ],
    }
    merged = merge_cv_refinement(base, refined)
    assert len(merged["experience"]) == 2
    assert merged["experience"][0]["start_date"] == "2020-01"
    assert merged["experience"][1]["end_date"] == "Present"


def test_merge_keeps_base_when_refiner_adds_nothing() -> None:
    base = {
        "experience": [
            {
                "company": "Acme",
                "job_title": "Engineer",
                "start_date": "2021-01",
                "end_date": "2024-01",
                "description": "Python APIs.",
            }
        ],
        "skills": ["python"],
    }
    refined = {"experience": [], "skills": []}
    merged = merge_cv_refinement(base, refined)
    assert len(merged["experience"]) == 1
    assert merged["experience"][0]["start_date"] == "2021-01"
