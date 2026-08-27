from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.services.reporter import ReporterService


# Wrap PDF body text on word boundaries so Latin words are not split.
def test_pdf_wrap_keeps_latin_words() -> None:
    from reportlab.pdfbase import pdfmetrics
    from report_gen.reporter import ReporterService, _CJK

    text = "No explicit Quality Control evidence was found."
    lines = ReporterService._wrap_to_width(text, _CJK, 8, 160)
    joined = " ".join(lines)
    assert "Quality" in joined
    assert "Qualit" not in joined.replace("Quality", "")
    for line in lines:
        assert pdfmetrics.stringWidth(line, _CJK, 8) <= 160 + 0.5


def test_reporter_generates_candidate_pdf(tmp_path: Path) -> None:
    service = ReporterService()
    out = tmp_path / "candidate.pdf"
    service.generate_candidate_one_pager_pdf(
        str(out),
        display_label="260818001/123456",
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
        interview_suggestions=[],
        radar_dimensions=[
            {
                "label": "Education and Certification",
                "score": None,
                "status": "n_a",
                "weight": 0.1,
                "reasoning": {"summary": "No explicit Quality Control evidence was found."},
                "gaps": ["Facilities Management", "Quality Control"],
            },
            {
                "label": "Core Skill Match",
                "score": 0.0,
                "status": "low",
                "weight": 0.38,
                "reasoning": {
                    "summary": "No dated Quality Control evidence was found in the CV against the required facilities skills."
                },
                "gaps": ["No explicit Php evidence was found."],
            },
        ],
        interview_questions=[{"question": "Walk through a facilities electrical outage you owned.", "priority": "high"}],
        eligibility={"status": "passed", "results": [{"rule_id": "visa", "status": "pass"}]},
        key_gaps=["Facilities Management", "Php", "Quality Control"],
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
                "refno": "260818001",
                "appno": "123456",
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


def test_reporter_generates_html_board_without_names(tmp_path: Path) -> None:
    service = ReporterService()
    out = tmp_path / "screening-board.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Project Associate",
        report_date=datetime(2026, 1, 1),
        refno="260818001",
        rows=[
            {
                "rank": 1,
                "name": "Alice Chen",
                "refno": "260818001",
                "appno": "123456",
                "total_score": 88.5,
                "skill_match": 80,
                "experience_match": 90,
                "education_match": 100,
                "research_quality": 70,
                "experience_quality": 85,
                "tier": "Tier 1",
                "interview_questions": [{"priority": "high", "question": "Walk through a data pipeline you owned."}],
            }
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "260818001/123456" in text
    assert "Alice Chen" not in text
    assert "<svg" in text
    assert "Ranking overview" in text
    assert "Walk through a data pipeline you owned." in text
