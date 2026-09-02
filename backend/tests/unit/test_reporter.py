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
    assert "refno 260818001" in text
    assert "appno 123456" in text
    assert "Alice Chen" not in text
    assert "<svg" in text
    assert "Ranking overview" in text
    assert "Walk through a data pipeline you owned." in text
    # No resume_url on the row -> the resume column renders an em dash, not a link.
    assert ">Resume</a>" not in text


# The all-low advisory must appear when every tier is low and stay absent otherwise.
def test_html_board_all_low_advisory(tmp_path: Path) -> None:
    service = ReporterService()
    out = tmp_path / "board-low.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=[
            {"rank": 1, "refno": "260901004", "appno": "260901007", "total_score": 57.4, "tier": "low"},
            {"rank": 2, "refno": "260901004", "appno": "260901008", "total_score": 55.9, "tier": "low"},
            {"rank": 3, "refno": "260901004", "appno": "260901009", "total_score": 42.0, "tier": "low"},
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "Why every candidate shows the low band" in text
    assert "absolute thresholds" in text
    # Spread is 15.4 points, so the "treat as tied" line must not render.
    assert "treated as tied" not in text

    mixed = tmp_path / "board-mixed.html"
    service.generate_screening_board_html(
        str(mixed),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=[
            {"rank": 1, "refno": "260901004", "appno": "260901007", "total_score": 82.0, "tier": "high"},
            {"rank": 2, "refno": "260901004", "appno": "260901008", "total_score": 55.9, "tier": "low"},
        ],
    )
    mixed_text = mixed.read_text(encoding="utf-8")
    assert "Why every candidate shows the low band" not in mixed_text


# When the all-low pool also has a tiny score spread, add the tie warning.
def test_html_board_all_low_narrow_spread_warning(tmp_path: Path) -> None:
    service = ReporterService()
    out = tmp_path / "board-tight.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=[
            {"rank": 1, "refno": "260901004", "appno": "260901007", "total_score": 57.4, "tier": "low"},
            {"rank": 2, "refno": "260901004", "appno": "260901008", "total_score": 55.9, "tier": "low"},
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "treated as tied" in text


# The board renders resume hyperlinks and explicit refno/appno labels in English only.
def test_html_board_resume_links_and_explicit_labels(tmp_path: Path) -> None:
    service = ReporterService()
    out = tmp_path / "board-links.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=[
            {
                "rank": 1,
                "refno": "260901004",
                "appno": "260901007",
                "total_score": 57.4,
                "tier": "low",
                "resume_url": "https://example.test/cvs/260901007.pdf",
                "radar_dimensions": [
                    {"id": "core_skill_match", "label": "Core Skill Match", "score": 50},
                    {"id": "relevant_experience", "label": "Relevant Experience", "score": 40},
                    {"id": "role_seniority_fit", "label": "Role and Seniority Fit", "score": 30},
                    {"id": "education_certification", "label": "Education and Certification", "score": 60},
                    {"id": "evidence_impact", "label": "Evidence and Impact", "score": 20},
                    {"id": "job_specific_match", "label": "Job-Specific Match", "score": 45},
                ],
            },
        ],
    )
    text = out.read_text(encoding="utf-8")
    # Resume column links to the online CV.
    assert "<th>Resume</th>" in text
    assert "href='https://example.test/cvs/260901007.pdf'" in text
    assert ">Resume</a>" in text
    # Labels spell out which number is the refno and which is the appno.
    assert "refno 260901004 · appno 260901007" in text
    # Radar uses short axis labels and a padded viewBox so nothing clips.
    assert "Core skills" in text
    assert "viewBox=\"-80 0 440 280\"" in text
    # The board is English-only.
    for ch in "評等候選請以":
        assert ch not in text
