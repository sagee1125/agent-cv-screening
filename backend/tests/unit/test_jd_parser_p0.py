# Unit tests for P0: taxonomy injection, Chinese boundary matching, and years ranges.
from __future__ import annotations

from typing import Any

import pytest

from app.core.taxonomy import SkillNode
from app.services.jd_parser import JDParserService


class FakeTaxonomyLoader:
    """In-memory taxonomy loader stand-in with a minimal nodes map."""

    def __init__(self, nodes: dict[str, SkillNode]) -> None:
        self.nodes = nodes


def _fake_loader() -> FakeTaxonomyLoader:
    nodes = {
        "Python": SkillNode("Python", "Programming Language", ["python", "py"], None),
        "Docker": SkillNode("Docker", "DevOps", ["docker", "container"], None),
        "Financial Modeling": SkillNode(
            "Financial Modeling", "Finance & Accounting", ["financial modeling"], None
        ),
    }
    return FakeTaxonomyLoader(nodes)


def test_constructor_accepts_injected_taxonomy_loader() -> None:
    """P0-1: JDParserService builds its matcher from an injected loader."""
    service = JDParserService(taxonomy_loader=_fake_loader())
    candidates = service._extract_candidates_from_line("python docker financial modeling")
    assert candidates == ["docker", "financial modeling", "python"]


@pytest.mark.asyncio
async def test_parser_works_with_injected_loader() -> None:
    """P0-1: full parse path works with an injected in-memory loader."""
    service = JDParserService(taxonomy_loader=_fake_loader())
    result = await service.parse_jd("Requirements: 3+ years of Python and Docker experience")
    must = {item["display_name"].lower() for item in result["structured_data"]["must_skills"]}
    assert "python" in must
    assert "docker" in must


def test_chinese_embedded_skill_matches() -> None:
    """P0-2: ASCII lookaround lets English skills inside Chinese text match."""
    service = JDParserService()
    candidates = service._extract_candidates_from_line("熟悉 python开发经验")
    assert "python" in candidates


@pytest.mark.asyncio
async def test_chinese_jd_extracts_skills_and_years() -> None:
    """Bilingual JD extracts embedded English skills and Chinese year ranges."""
    service = JDParserService()
    jd = "职位要求：3 年以上 Python开发经验，熟悉 Docker部署"
    result = await service.parse_jd(jd)
    data = result["structured_data"]
    must = {item["display_name"].lower() for item in data["must_skills"]}
    assert "python" in must
    assert "docker" in must
    assert data["experience_requirement"]["minimum_years"] == 3


def test_experience_requirement_range() -> None:
    """P0-3: '5-8 years' becomes a min/max range."""
    service = JDParserService()
    req = service._extract_experience_requirement("Requirements: 5-8 years experience")
    assert req == {"minimum_years": 5, "maximum_years": 8, "raw_text": "5-8 years"}


def test_experience_requirement_at_least() -> None:
    """'at least N years' becomes a lower bound."""
    service = JDParserService()
    req = service._extract_experience_requirement("at least 5 years of experience")
    assert req["minimum_years"] == 5
    assert req["maximum_years"] is None


def test_experience_requirement_plus() -> None:
    """'N+ years' becomes a lower bound."""
    service = JDParserService()
    req = service._extract_experience_requirement("3+ years experience required")
    assert req["minimum_years"] == 3
    assert req["maximum_years"] is None


def test_experience_requirement_chinese_above() -> None:
    """Chinese 'N年以上' becomes a lower bound."""
    service = JDParserService()
    req = service._extract_experience_requirement("需要 5 年以上相关经验")
    assert req["minimum_years"] == 5
    assert req["maximum_years"] is None


def test_experience_requirement_plain() -> None:
    """Plain 'N years' sets both bounds to N."""
    service = JDParserService()
    req = service._extract_experience_requirement("2 years of experience")
    assert req["minimum_years"] == 2
    assert req["maximum_years"] == 2


def test_experience_requirement_missing() -> None:
    """No year phrase returns null bounds."""
    service = JDParserService()
    req = service._extract_experience_requirement("No specific experience required")
    assert req["minimum_years"] is None
    assert req["maximum_years"] is None
    assert req["raw_text"] is None


@pytest.mark.asyncio
async def test_parse_jd_includes_experience_range() -> None:
    """P0-3: parse_jd surfaces the structured range in experience_requirement."""
    service = JDParserService()
    result = await service.parse_jd("Requirements: 5-8 years of Python experience")
    req = result["structured_data"]["experience_requirement"]
    assert req["minimum_years"] == 5
    assert req["maximum_years"] == 8
    assert req["raw_text"] == "5-8 years"


def test_cn_numeral_conversion() -> None:
    """Chinese numeral phrases convert to integers correctly (incl. 11-19)."""
    from app.services.jd_parser.service import _cn_numeral_to_int

    assert _cn_numeral_to_int("三") == 3
    assert _cn_numeral_to_int("十") == 10
    assert _cn_numeral_to_int("十二") == 12
    assert _cn_numeral_to_int("二十一") == 21
    assert _cn_numeral_to_int("三十五") == 35
    assert _cn_numeral_to_int("两") == 2


def test_experience_requirement_chinese_no_less_than() -> None:
    """'不少於N年' with a Chinese numeral becomes a lower bound."""
    service = JDParserService()
    req = service._extract_experience_requirement("不少於三年的 Java 經驗")
    assert req["minimum_years"] == 3
    assert req["maximum_years"] is None
    assert req["raw_text"] == "不少於三年"


def test_experience_requirement_chinese_at_least_numeral() -> None:
    """'至少三年' with a Chinese numeral becomes a lower bound."""
    service = JDParserService()
    req = service._extract_experience_requirement("至少三年 Java 經驗")
    assert req["minimum_years"] == 3
    assert req["maximum_years"] is None


def test_experience_requirement_chinese_range_numeral() -> None:
    """'五至八年' with Chinese numerals becomes a range."""
    service = JDParserService()
    req = service._extract_experience_requirement("五至八年 Java 經驗")
    assert req["minimum_years"] == 5
    assert req["maximum_years"] == 8


def test_experience_requirement_chinese_above_numeral() -> None:
    """'十二年以上' with a Chinese numeral becomes a lower bound."""
    service = JDParserService()
    req = service._extract_experience_requirement("十二年以上 Java")
    assert req["minimum_years"] == 12
    assert req["maximum_years"] is None


@pytest.mark.asyncio
async def test_chinese_no_less_than_full_parse() -> None:
    """A full parse of '不少於三年 Java' surfaces min 3 and the Java skill."""
    service = JDParserService()
    result = await service.parse_jd("要求：不少於三年的 Java 經驗")
    data = result["structured_data"]
    assert data["experience_requirement"]["minimum_years"] == 3
    assert data["experience_requirement"]["maximum_years"] is None
    skills = {item["display_name"].lower() for item in data["must_skills"]}
    assert "java" in skills


POLYU_STYLE_JD = """
Ref no.: 2608001
Job group: Research / Project Posts
Unit: School of Accounting and Finance
Post title: Research Assistant

Duties
The appointee will assist in research projects and working papers.

Requirements
A recognised bachelor degree in a business-related discipline (for example finance, economics, accounting, actuarial studies, data analytics or a related discipline)
Experience with Python, R, Stata, Git and PostgreSQL
"""


@pytest.mark.asyncio
async def test_job_metadata_is_not_promoted_to_must_skills() -> None:
    """Job group / unit / title tokens must not become core must-skills."""
    service = JDParserService()
    result = await service.parse_jd(POLYU_STYLE_JD)
    must = {item["canonical_skill"] for item in result["structured_data"]["must_skills"]}
    assert "research" not in must
    assert "accounting" not in must
    assert {"python", "r", "stata", "git", "postgresql"} <= must


@pytest.mark.asyncio
async def test_degree_examples_go_to_field_of_study() -> None:
    """Parenthetical degree majors are stored as education fields, not must-skills."""
    service = JDParserService()
    result = await service.parse_jd(POLYU_STYLE_JD)
    field = (result["structured_data"]["education_requirement"].get("field_of_study") or "").lower()
    must = {item["canonical_skill"] for item in result["structured_data"]["must_skills"]}
    assert "actuarial science" in field or "actuarial" in field
    assert "accounting" in field
    assert "data analysis" in field or "data analytics" in field
    assert "actuarial_science" not in must
    assert "data_analysis" not in must


@pytest.mark.asyncio
async def test_degree_line_still_extracts_tools_on_same_line() -> None:
    """A requirement that mixes degree wording and tools must keep the tools."""
    service = JDParserService()
    jd = """Requirements:
- Bachelor degree and 3+ years of Python experience
- Experience with Master Data Management and SQL
"""
    result = await service.parse_jd(jd)
    must = {item["canonical_skill"] for item in result["structured_data"]["must_skills"]}
    assert "python" in must
    assert "sql" in must


# --- JD-parser regressions: discourse words, majors, headings, footer boilerplate ---


@pytest.mark.asyncio
async def test_discourse_word_not_swallowed_into_skill_name() -> None:
    """'including' must never become part of a preferred-skill canonical name."""
    service = JDParserService()
    result = await service.parse_jd(
        "Qualifications: experience with Python;\n"
        "Preferred: experience with research governance, including ethics submissions and data-sharing agreements, would be a definite advantage;"
    )
    preferred = {item["canonical_skill"] for item in result["structured_data"]["preferred_skills"]}
    assert "including_ethics_submissions" not in preferred
    assert "ethics_submissions" in preferred
    assert "research_governance" in preferred
    assert "data-sharing_agreements" in preferred


@pytest.mark.asyncio
async def test_field_of_study_keeps_explicit_non_taxonomy_majors() -> None:
    """Degree majors without a taxonomy node (finance/economics) must be kept."""
    service = JDParserService()
    result = await service.parse_jd(
        "Qualifications: a recognised degree in a business-related discipline "
        "(for example finance, economics, accounting, actuarial studies, business analytics or a related quantitative field);"
    )
    field = (result["structured_data"]["education_requirement"].get("field_of_study") or "").lower()
    assert "finance" in field
    assert "economics" in field
    assert "accounting" in field
    assert "actuarial" in field
    assert "business analytics" in field
    assert "related quantitative" in field
    assert "related quantitative field" not in field
    assert "related discipline" not in field


@pytest.mark.asyncio
async def test_preferred_qualifications_heading_keeps_preferred_bucket() -> None:
    """A 'Preferred qualifications' heading must not demote its items to must."""
    service = JDParserService()
    result = await service.parse_jd(
        "Qualifications: experience with Python;\n"
        "Preferred qualifications: experience with Tableau;"
    )
    data = result["structured_data"]
    must = {item["canonical_skill"] for item in data["must_skills"]}
    preferred = {item["canonical_skill"] for item in data["preferred_skills"]}
    assert "python" in must
    assert "tableau" in preferred
    assert "tableau" not in must


@pytest.mark.asyncio
async def test_footer_boilerplate_never_becomes_must_skills() -> None:
    """Posting/conditions/contact footer lines must not promote tool names."""
    service = JDParserService()
    result = await service.parse_jd(
        "Reference number: 999\n"
        "Job group: Research / Project Posts\n"
        "Post title: Analyst\n"
        "Qualifications: experience with Python;\n"
        "Conditions of service (display to external ads only): remuneration package, Excel support;\n"
        "List in external/internal: External Advertisement\n"
        "Posting date: 2026-08-25\n"
        "For further information, please contact Dr Sample at sample@example.test;"
    )
    must = {item["canonical_skill"] for item in result["structured_data"]["must_skills"]}
    assert "excel" not in must
    assert must == {"python"}
