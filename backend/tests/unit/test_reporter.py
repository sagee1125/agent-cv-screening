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
    assert "Ref. No.: 260818001" in text
    assert "Application No.: 123456" in text
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


# The board renders resume hyperlinks and explicit application-no. labels in English only.
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
                    {"id": "language_match", "label": "Language Match", "score": 45},
                ],
            },
        ],
    )
    text = out.read_text(encoding="utf-8")
    # Resume column links to the online CV.
    assert "<th>Resume</th>" in text
    assert "href='https://example.test/cvs/260901007.pdf'" in text
    assert ">Resume</a>" in text
    # Labels show the application No. only; the refno lives in the page title.
    assert "Application No.: 260901007" in text
    # Radar spells out full dimension names, wraps them, and pads the viewBox so nothing clips.
    assert "Core Skill" in text
    assert "<tspan" in text
    assert "viewBox=\"-110 -44 500 368\"" in text
    # The board is English-only.
    for ch in "評等候選請以":
        assert ch not in text


# ---------------------------------------------------------------------------
# Option A (PRD-REPORT-GEN-001): radar tooltip payload allow-list and HTML hover trace-back.
# ---------------------------------------------------------------------------


# public_radar_dimensions must keep id/label/score and add allow-listed fields only.
def test_board_tooltip_payload_allowlist() -> None:
    from screening_core.board_tooltip import public_radar_dimensions

    detail = {
        "radar_dimensions": [
            {
                "dimension_id": "core_skill_match",
                "label": "Core Skill Match",
                "score": 90.0,
                "status": "met",
                "confidence": 92.0,
                "reasoning": {
                    "template_id": "DR-CORE-001",
                    "summary": "Core Skill Match: 90/100. Presence 67%; linkage 100%.",
                    "facts": {"presence_pct": 67, "linkage_pct": 100},
                },
                "requirements": [{"requirement_id": "python_1", "text": "Python"}],
                "evidence": [
                    {"section": "experience", "text": "SECRET_RAW_CV_SNIPPET_9981"},
                    {"section": "projects", "text": "SECRET_RAW_CV_SNIPPET_9981"},
                ],
                "gaps": [{"reason_code": "NO_EXPLICIT_CV_EVIDENCE", "text": "No explicit Docker evidence was found."}],
            }
        ]
    }
    axes = public_radar_dimensions(detail)
    assert axes == [
        {
            "id": "core_skill_match",
            "label": "Core Skill Match",
            "score": 90.0,
            "status": "met",
            "confidence": 92.0,
            "summary": "Core Skill Match: 90/100. Presence 67%; linkage 100%.",
            "requirements": ["Python"],
            "gaps": ["No explicit Docker evidence was found."],
            "evidence_sections": {"experience": 1, "projects": 1},
            "evidence_metrics": {"presence_pct": 67.0, "linkage_pct": 100.0},
        }
    ]
    rendered = str(axes)
    assert "SECRET_RAW_CV_SNIPPET_9981" not in rendered
    assert "reasoning" not in rendered
    assert "facts" not in rendered
    assert "template_id" not in rendered

def test_board_tooltip_payload_degrades_gracefully() -> None:
    from screening_core.board_tooltip import public_radar_dimensions

    assert public_radar_dimensions({}) == []
    degraded = public_radar_dimensions({"radar_dimensions": [None, "bad", {"score": None}]})
    assert len(degraded) == 1
    assert degraded[0]["score"] is None


# Long summaries and many gaps must be clipped with an overflow marker.
def test_board_tooltip_payload_truncates_long_text() -> None:
    from screening_core.board_tooltip import public_radar_dimensions

    summary = "x" * 500
    gaps = [{"text": f"gap {i}"} for i in range(5)]
    axes = public_radar_dimensions(
        {
            "radar_dimensions": [
                {
                    "dimension_id": "core_skill_match",
                    "label": "Core Skill Match",
                    "score": 50.0,
                    "status": "partial",
                    "reasoning": {"summary": summary},
                    "gaps": gaps,
                }
            ]
        }
    )
    axis = axes[0]
    assert len(axis["summary"]) <= 240
    assert axis["summary"].endswith("…")
    assert axis["gaps"] == ["gap 0", "gap 1", "gap 2"]
    assert axis["gaps_overflow"] == 2


# The board HTML must carry per-axis tooltips and never raw CV text or live markup.
def test_html_board_radar_tooltips_present_escaped_no_raw_text(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-tooltips.html"
    raw = "SECRET_RAW_CV_SNIPPET_9981"
    service.generate_screening_board_html(
        str(out),
        position_name="Project Associate",
        report_date=datetime(2026, 1, 1),
        refno="260818001",
        rows=[
            {
                "rank": 1,
                "refno": "260818001",
                "appno": "123456",
                "total_score": 88.5,
                "tier": "high",
                "radar_dimensions": [
                    {
                        "id": "core_skill_match",
                        "label": "Core Skill Match",
                        "score": 90.0,
                        "status": "met",
                        "summary": "Core Skill Match: 90/100. Weighted must-skill coverage is high.",
                        "evidence_sections": {"experience": 1, "skills": 2},
                    },
                    {
                        "id": "education_certification",
                        "label": "Education and Certification",
                        "score": 72.5,
                        "status": "partial",
                        "summary": 'Education and Certification: 72.5/100. <script>alert("x")</script> Field gap.',
                        "gaps": [
                            "No matching field evidence was found.",
                            "Some skill claims are not tied to structured evidence.",
                        ],
                        "evidence_sections": {"education": 2},
                        "raw_leak": raw,
                    },
                    {
                        "id": "relevant_experience",
                        "label": "Relevant Experience",
                        "score": 85.0,
                        "status": "met",
                        "summary": "Relevant Experience: 85/100. Dated coverage is high.",
                        "gaps": ["gap-alpha", "gap-beta", "gap-gamma", "gap-delta"],
                        "gaps_overflow": 1,
                    },
                ],
            }
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert text.count("<title>") == 1  # page title only; tooltips are styled panels
    assert '<div class="radar-tip" data-tip="core_skill_match"' in text
    assert '<div class="radar-tip" data-tip="education_certification"' in text
    assert '<div class="radar-tip" data-tip="relevant_experience"' in text
    assert ">Core Skill Match</span>" in text
    assert "72.5/100" in text
    assert "st-partial" in text
    assert "No matching field evidence was found." in text
    assert "Evidence by CV section: education 2" in text
    assert "+1 more" in text
    assert "Evidence and Impact" not in text
    assert raw not in text
    assert "raw_leak" not in text
    assert "<script>alert" not in text
    assert "<script" not in text
    assert "&lt;script&gt;" in text
    assert "href='http" not in text
    assert "src='http" not in text

def test_html_board_radar_geometry_and_scores_unchanged_by_tooltips(tmp_path: Path) -> None:
    import re

    from app.services.reporter import ReporterService

    service = ReporterService()

    def render(path, enriched):
        dims = [
            {"id": "core_skill_match", "label": "Core Skill Match", "score": 90.0},
            {"id": "relevant_experience", "label": "Relevant Experience", "score": 85.0},
            {"id": "role_seniority_fit", "label": "Role and Seniority Fit", "score": 100.0},
            {"id": "education_certification", "label": "Education and Certification", "score": 60.0},
            {"id": "language_match", "label": "Language Match", "score": 80.0},
        ]
        if enriched:
            for dim in dims:
                dim["status"] = "met" if dim["score"] >= 80 else "partial"
                dim["summary"] = f"{dim['label']}: {dim['score']}/100."
                dim["gaps"] = []
                dim["evidence_sections"] = {"experience": 1}
        row = {
            "rank": 1,
            "refno": "260818001",
            "appno": "123456",
            "total_score": 88.5,
            "tier": "high",
            "radar_dimensions": dims,
        }
        out = tmp_path / path
        service.generate_screening_board_html(
            str(out),
            position_name="Project Associate",
            report_date=datetime(2026, 1, 1),
            refno="260818001",
            rows=[row],
        )
        return out.read_text(encoding="utf-8")

    legacy_text = render("board-legacy.html", enriched=False)
    enriched_text = render("board-enriched.html", enriched=True)

    def polygons(text):
        return re.findall(r'<polygon points="([^"]+)"', text)

    assert polygons(legacy_text) == polygons(enriched_text)
    assert "88.5" in legacy_text and "88.5" in enriched_text
    assert "Application No.: 123456" in legacy_text
    assert legacy_text.count("<title>") == 1
    assert enriched_text.count("<title>") == 1
    assert '<div class="radar-tip" data-tip=' not in legacy_text
    assert '<div class="radar-tip" data-tip=' in enriched_text

def test_html_candidate_match_page_dimension_panel(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "123456.html"
    service.generate_candidate_match_html(
        str(out),
        row={
            "rank": 1,
            "refno": "260818001",
            "appno": "123456",
            "total_score": 88.5,
            "tier": "high",
            "radar_dimensions": [
                {
                    "id": "core_skill_match",
                    "label": "Core Skill Match",
                    "score": 90.0,
                    "status": "met",
                    "summary": "Core Skill Match: 90/100.",
                },
                {
                    "id": "relevant_experience",
                    "label": "Relevant Experience",
                    "score": 85.0,
                    "status": "met",
                    "summary": "Relevant Experience: 85/100.",
                },
                {
                    "id": "language_match",
                    "label": "Language Match",
                    "score": 72.5,
                    "status": "partial",
                    "summary": "Language Match: 72.5/100.",
                    "gaps": ["No sufficient evidence for research governance."],
                    "evidence_sections": {"experience": 2},
                }
            ],
        },
        position_name="Project Associate",
        report_date=datetime(2026, 1, 1),
    )
    text = out.read_text(encoding="utf-8")
    assert text.count("<title>") == 1
    # The match page shows the breakdown beside the radar instead of a hover overlay.
    assert 'class="match-layout"' in text
    assert '<div class="radar-tip" data-tip=' not in text
    assert '<article class="dim-card st-partial" data-dim="language_match"' in text
    assert '<h3 class="dim-label">Language Match</h3>' in text
    assert "st-partial" in text
    assert "Evidence by CV section: experience 2" in text
    # Dimension scores keep one decimal on the page too.
    assert '<p class="dim-score">72.5<span class="dim-total">/100</span></p>' in text

def test_report_fingerprint_version_bumped_for_jd_panel() -> None:
    from screening_core.report_fingerprint import REPORT_FINGERPRINT_VERSION

    assert REPORT_FINGERPRINT_VERSION == "hr-report-v5"


# F1.2: Core/Experience tooltip cards preview Evidence-axis sub-metrics (Option B aid).
def test_html_board_sub_scores_on_core_and_experience_tips(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-subscores.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Project Associate",
        report_date=datetime(2026, 1, 1),
        refno="260818001",
        rows=[
            {
                "rank": 1,
                "refno": "260818001",
                "appno": "123456",
                "total_score": 88.5,
                "tier": "high",
                "radar_dimensions": [
                    {
                        "id": "core_skill_match",
                        "label": "Core Skill Match",
                        "score": 90.0,
                        "status": "met",
                        "summary": "Core Skill Match: 90/100.",
                        "evidence_metrics": {"presence_pct": 90.0, "linkage_pct": 50.0},
                    },
                    {
                        "id": "relevant_experience",
                        "label": "Relevant Experience",
                        "score": 85.0,
                        "status": "met",
                        "summary": "Relevant Experience: 85/100.",
                        "evidence_metrics": {"ownership_pct": 100.0, "impact_pct": 50.0},
                    },
                    {
                        "id": "language_match",
                        "label": "Language Match",
                        "score": 80.0,
                        "status": "met",
                        "summary": "Language Match: 80/100.",
                    },
                ],
            }
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "Option B preview" not in text
    assert "Sub-scores: presence 90% · linkage 50%" in text
    assert "Sub-scores: ownership 100% · impact 50%" in text
    panels = text.split('<div class="radar-tips">', 1)[1]
    core_panel = panels.split('<div class="radar-tip" data-tip="core_skill_match"', 1)[1].split('<div class="radar-tip" data-tip=', 1)[0]
    assert "Sub-scores: presence 90% · linkage 50%" in core_panel
    experience_panel = panels.split('<div class="radar-tip" data-tip="relevant_experience"', 1)[1].split('<div class="radar-tip" data-tip=', 1)[0]
    assert "Sub-scores: ownership 100% · impact 50%" in experience_panel
    job_panel = panels.split('<div class="radar-tip" data-tip="language_match"', 1)[1].split('<div class="radar-tip" data-tip=', 1)[0]
    assert "Sub-scores:" not in job_panel


# ---------------------------------------------------------------------------
# F1.3 / F1.5: full axis names, on-chart scores, and auto-height tooltip cards.
# ---------------------------------------------------------------------------


# Board radar spells out full dimension names and prints every score on the chart.
def test_html_board_full_axis_names_and_on_chart_scores(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-labels.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=[
            {
                "rank": 1,
                "refno": "260901004",
                "appno": "260901008",
                "total_score": 78.7,
                "tier": "medium",
                "radar_dimensions": [
                    {"id": "core_skill_match", "label": "Core Skill Match", "score": 65.14},
                    {"id": "relevant_experience", "label": "Relevant Experience", "score": 100.0},
                    {"id": "education_certification", "label": "Education and Certification", "score": 77.78},
                    {"id": "language_match", "label": "Language Match", "score": 62.5},
                ],
            },
        ],
    )
    text = out.read_text(encoding="utf-8")
    # Full names are used verbatim, never the old abbreviations.
    for full in ("Core Skill Match", "Relevant Experience", "Education and Certification", "Language Match"):
        assert full in text
    for short in ("Core skills", "Job-specific", "Work auth"):
        assert short not in text
    # Long names are wrapped onto tspan lines instead of being truncated.
    assert "<tspan" in text
    # Every axis prints its own score on the chart, to one decimal (F1.3).
    assert 'class="axis-score">65.1</text>' in text
    assert 'class="axis-score">100.0</text>' in text
    assert 'class="axis-score">77.8</text>' in text
    assert 'class="axis-score">62.5</text>' in text


# Hover tooltip cards grow to fit their content instead of scrolling internally (F1.5).
def test_html_board_tooltip_card_has_no_inner_scroll(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-tip-height.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=[
            {
                "rank": 1,
                "refno": "260901004",
                "appno": "260901008",
                "total_score": 78.7,
                "tier": "medium",
                "radar_dimensions": [
                    {"id": "core_skill_match", "label": "Core Skill Match", "score": 65.14},
                    {"id": "relevant_experience", "label": "Relevant Experience", "score": 100.0},
                    {"id": "language_match", "label": "Language Match", "score": 62.5},
                ],
            },
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "max-height: none" in text
    assert "overflow: visible" in text
    assert "max-height: 94%" not in text


# Table links use the same sanitized stem as on-disk match pages, not the raw appno.
def test_html_board_table_link_uses_sanitized_stem(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-stem.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=[
            {
                "rank": 1,
                "refno": "260901004",
                "appno": "260901/007",
                "total_score": 57.4,
                "tier": "low",
                "radar_dimensions": [
                    {"id": "core_skill_match", "label": "Core Skill Match", "score": 50},
                    {"id": "relevant_experience", "label": "Relevant Experience", "score": 40},
                    {"id": "language_match", "label": "Language Match", "score": 45},
                ],
            },
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "href='260901_007.html'" in text
    assert "href='260901/007.html'" not in text
    assert "Application No.: 260901/007" in text


# Unsafe resume URLs are dropped instead of rendered as clickable links.
def test_html_board_rejects_unsafe_resume_url(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-resume-safe.html"
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
                "resume_url": "javascript:alert(1)",
                "radar_dimensions": [
                    {"id": "core_skill_match", "label": "Core Skill Match", "score": 50},
                    {"id": "relevant_experience", "label": "Relevant Experience", "score": 40},
                    {"id": "language_match", "label": "Language Match", "score": 45},
                ],
            },
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "javascript:" not in text
    assert ">Resume</a>" not in text


# Match pages still show dimension cards when rows carry score-only radar axes.
def test_html_candidate_match_page_score_only_dimensions(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "123456.html"
    service.generate_candidate_match_html(
        str(out),
        row={
            "rank": 1,
            "refno": "260818001",
            "appno": "123456",
            "total_score": 88.5,
            "tier": "high",
            "radar_dimensions": [
                {"id": "core_skill_match", "label": "Core Skill Match", "score": 90.0},
                {"id": "relevant_experience", "label": "Relevant Experience", "score": 85.0},
                {"id": "language_match", "label": "Language Match", "score": 72.5},
            ],
        },
        position_name="Project Associate",
        report_date=datetime(2026, 1, 1),
    )
    text = out.read_text(encoding="utf-8")
    assert '<article class="dim-card st-unknown" data-dim="core_skill_match"' in text
    assert '<h3 class="dim-label">Core Skill Match</h3>' in text
    assert '<p class="dim-score">90.0<span class="dim-total">/100</span></p>' in text
    assert '<div class="radar-tip" data-tip=' not in text

# ---------------------------------------------------------------------------
# JD description & parsed-requirements panel (F1.7)
# ---------------------------------------------------------------------------


# Build a sample parsed JD payload used by the JD-panel tests.
def _sample_jd_parsed() -> dict:
    return {
        "must_skills": [
            {
                "skill_id": "python_1",
                "display_name": "Python",
                "canonical_skill": "python",
                "weight": 1.0,
                "provenance": {"source_sentence": "Hands-on Python experience is required."},
            },
            {
                "skill_id": "stata_1",
                "display_name": "Stata",
                "canonical_skill": "stata",
                "weight": 1.0,
                "provenance": {"source_sentence": "Stata for panel-data analysis."},
            },
        ],
        "preferred_skills": [
            {
                "skill_id": "docker_1",
                "display_name": "Docker",
                "canonical_skill": "docker",
                "weight": 0.6,
                "provenance": {"source_sentence": "Containerisation is a plus."},
            }
        ],
        "language_requirements": [
            {"language": "Cantonese", "level": "fluent", "is_mandatory": True, "provenance": "Be fluent in Cantonese."},
            {"language": "English", "level": "fluent", "is_mandatory": False, "provenance": "Write reports in English."},
        ],
        "education_requirement": {
            "minimum_degree": "bachelor",
            "field_of_study": "computer science",
            "is_mandatory": True,
            "provenance": "A bachelor degree in computer science is required.",
        },
        "visa_requirement": {"requirement_type": "unknown", "target_region": None, "provenance": ""},
    }


# The board emits no JD panel when no JD text or parsed payload is supplied.
def test_html_board_jd_panel_omitted_without_jd_inputs(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-no-jd.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        rows=[{"rank": 1, "refno": "260901004", "appno": "260901008", "total_score": 78.7, "tier": "medium"}],
    )
    text = out.read_text(encoding="utf-8")
    assert "<section class='jd-panel'" not in text
    assert "Must Skills" not in text
    assert "No parsed skills yet." not in text


# The JD panel renders all tag groups, language mandatory state, and escaped/scrubbed JD text.
def test_html_board_jd_panel_renders_groups_languages_and_escaping(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-jd.html"
    jd = (
        'Duties: run <script>alert("x")</script> analysis with Python & Stata.\n'
        "Contact: hr@polyu.example for details or phone 2766 1234.\n"
        "Posting date: 2026-08-25\n"
    )
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        rows=[{"rank": 1, "refno": "260901004", "appno": "260901008", "total_score": 78.7, "tier": "medium"}],
        jd_text=jd,
        jd_parsed=_sample_jd_parsed(),
    )
    text = out.read_text(encoding="utf-8")
    assert "class='jd-panel'" in text
    assert "Full job description" in text
    assert "Must Skills (2)" in text
    assert "Preferred Skills (1)" in text
    assert "Language Requirements (2)" in text
    assert ">Python" in text
    assert ">Docker" in text
    assert "Cantonese \u00b7 fluent \u00b7 mandatory" in text
    assert "English \u00b7 fluent" in text
    assert 'title="Mandatory"' in text
    assert "Education:" in text
    # The visa requirement is unknown, so the work-authorisation line stays hidden.
    assert "Work authorisation:" not in text
    # Free JD text is HTML-escaped and never emits live markup.
    assert "&lt;script&gt;" in text
    assert "<script>alert" not in text
    assert "<script" not in text
    # Emails and phone numbers are scrubbed before rendering.
    assert "hr@polyu.example" not in text
    assert "2766 1234" not in text
    # The new panel introduces no scripts and no external references.
    assert "href='http" not in text
    assert "src='http" not in text


# The full JD body sits inside a <details> element collapsed by default.
def test_html_board_jd_panel_collapsed_by_default(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "board-jd-collapsed.html"
    service.generate_screening_board_html(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        rows=[{"rank": 1, "refno": "260901004", "appno": "260901008", "total_score": 78.7, "tier": "medium"}],
        jd_text="Full JD body here.\n",
        jd_parsed=_sample_jd_parsed(),
    )
    text = out.read_text(encoding="utf-8")
    assert "<details class='jd-details'>" in text
    assert "<details open" not in text


# Forwarded candidate match pages show a compact tags-only JD panel (no full JD text).
def test_html_candidate_match_page_jd_compact_tags_only(tmp_path: Path) -> None:
    from app.services.reporter import ReporterService

    service = ReporterService()
    out = tmp_path / "260901008.html"
    service.generate_candidate_match_html(
        str(out),
        row={
            "rank": 1,
            "refno": "260901004",
            "appno": "260901008",
            "total_score": 78.7,
            "tier": "medium",
            "radar_dimensions": [
                {"id": "core_skill_match", "label": "Core Skill Match", "score": 65.14},
                {"id": "relevant_experience", "label": "Relevant Experience", "score": 100.0},
                {"id": "language_match", "label": "Language Match", "score": 62.5},
            ],
        },
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        jd_text="Full JD body that must not appear on a match page.\n",
        jd_parsed=_sample_jd_parsed(),
    )
    text = out.read_text(encoding="utf-8")
    assert "class='jd-panel'" in text
    assert "Must Skills (2)" in text
    assert "Cantonese \u00b7 fluent \u00b7 mandatory" in text
    assert "Full JD body" not in text
    assert "class='jd-text'" not in text
    assert "<details" not in text
