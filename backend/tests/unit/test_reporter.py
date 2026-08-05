from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.services.reporter import ReporterService


def test_reporter_generates_candidate_pdf(tmp_path: Path) -> None:
    service = ReporterService()
    out = tmp_path / "candidate.pdf"
    service.generate_candidate_one_pager_pdf(
        str(out),
        candidate_name="Alice",
        position_name="Researcher",
        report_date=datetime(2026, 1, 1),
        total_score=88.5,
        tier="Tier 1",
        rank=1,
        education=[{"school": "NTU", "degree": "PhD", "major": "CS", "year": 2022}],
        experience=[{"company": "ABC", "title": "Engineer", "start_date": "2023-01", "end_date": "2025-01"}],
        skill_hit=["Python"],
        skill_miss=["SQL"],
        hit_rate=80.0,
        dimension_scores={
            "skill_match": 80,
            "experience_match": 90,
            "education_match": 100,
            "research_quality": 70,
            "experience_quality": 85,
        },
        interview_suggestions=[{"rule_id": "R1", "severity": "high", "text": "Probe system design."}],
        version="1.0.0",
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_reporter_generates_comparison_excel(tmp_path: Path) -> None:
    service = ReporterService()
    out = tmp_path / "comparison.xlsx"
    service.generate_comparison_excel(
        str(out),
        position_name="Researcher",
        report_date=datetime(2026, 1, 1),
        rows=[
            {
                "rank": 1,
                "name": "Alice",
                "total_score": 88.5,
                "skill_match": 80,
                "experience_match": 90,
                "education_match": 100,
                "research_quality": 70,
                "tier": "Tier 1",
                "suggestion_summary": "R1:high",
            }
        ],
    )
    assert out.exists()
    assert out.stat().st_size > 0
