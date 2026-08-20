# Unit tests for the all-industry skill taxonomy and taxonomy-driven JD extraction.
from __future__ import annotations

import pytest
import yaml

from app.core.taxonomy import SkillTaxonomyLoader
from app.services.jd_parser import JDParserService

TAXONOMY_PATH = "data/taxonomy/skill_taxonomy.yaml"


def _loader() -> SkillTaxonomyLoader:
    loader = SkillTaxonomyLoader(TAXONOMY_PATH)
    loader.load()
    return loader


def test_taxonomy_covers_major_industries() -> None:
    """The taxonomy contains categories spanning all major industries."""
    loader = _loader()
    categories = {node.category for node in loader.nodes.values()}
    expected = {
        "Finance & Accounting",
        "Healthcare & Clinical",
        "Marketing & Advertising",
        "Supply Chain & Logistics",
        "Retail & E-commerce",
        "Education & Training",
        "Design & Creative",
        "Legal & Compliance",
        "Human Resources",
        "Hospitality & Tourism",
    }
    assert expected <= categories


def test_taxonomy_has_no_duplicate_canonical_skills() -> None:
    """Every canonical skill name appears exactly once in the YAML."""
    payload = yaml.safe_load(open(TAXONOMY_PATH, encoding="utf-8-sig")) or []
    names = [item["skill"] for item in payload]
    assert len(names) == len(set(names))


def test_taxonomy_normalizes_aliases_across_industries() -> None:
    """Synonyms resolve to canonical skills across different industries."""
    loader = _loader()
    assert loader.normalize_skill("financial modeling") == "Financial Modeling"
    assert loader.normalize_skill("SEO") == "SEO"
    assert loader.normalize_skill("clinical trials") == "Clinical Trials"
    assert loader.normalize_skill("hubspot") == "Marketing Automation"
    assert loader.normalize_skill("postgres") == "PostgreSQL"


@pytest.mark.asyncio
async def test_rule_parser_extracts_finance_skills() -> None:
    """Finance JD requirements are extracted via the taxonomy."""
    jd = """Financial Analyst

Requirements:
- 3+ years of experience with financial modeling and Excel
- Must have IFRS and budgeting knowledge
- Nice to have: Tableau
"""
    service = JDParserService()
    result = await service.parse_jd(jd)
    data = result["structured_data"]
    must = {item["display_name"].lower() for item in data["must_skills"]}
    assert "financial modeling" in must
    assert "excel" in must
    assert "ifrs" in must
    preferred = {item["display_name"].lower() for item in data["preferred_skills"]}
    assert "tableau" in preferred


@pytest.mark.asyncio
async def test_rule_parser_extracts_healthcare_skills() -> None:
    """Healthcare JD requirements are extracted via the taxonomy."""
    jd = """Registered Nurse

Requirements:
- Bachelor degree in Nursing
- 2+ years of patient care experience
- Must hold CPR and infection control certification
- Preferred: telemedicine and electronic health records experience
"""
    service = JDParserService()
    result = await service.parse_jd(jd)
    data = result["structured_data"]
    skills = {item["display_name"].lower() for item in data["must_skills"]}
    assert "nursing" in skills
    assert "patient care" in skills
    assert "cpr" in skills
    assert "infection control" in skills


@pytest.mark.asyncio
async def test_rule_parser_extracts_marketing_and_soft_skills() -> None:
    """Marketing JD requirements including soft skills are extracted."""
    jd = """SEO Manager

Requirements:
- 4+ years of SEO and content marketing experience
- Must have strong communication and teamwork skills
"""
    service = JDParserService()
    result = await service.parse_jd(jd)
    data = result["structured_data"]
    skills = {item["display_name"].lower() for item in data["must_skills"]}
    assert "seo" in skills
    assert "content marketing" in skills
    assert "communication" in skills
    assert "teamwork" in skills


@pytest.mark.asyncio
async def test_rule_parser_extracts_frontend_and_database_stack() -> None:
    """Soft frontend familiarity lines map to preferred; API/DB lines map to must."""
    jd = """Familiarity with frontend technologies: React, JavaScript/TypeScript, HTML/CSS.
Experience building RESTful APIs and working with relational databases (PostgreSQL, MySQL).
Experience with Flask and Git."""
    service = JDParserService()
    result = await service.parse_jd(jd)
    data = result["structured_data"]
    must = {item["display_name"].lower() for item in data["must_skills"]}
    preferred = {item["display_name"].lower() for item in data["preferred_skills"]}
    assert {"flask", "git", "mysql", "postgresql", "rest api"} <= must
    assert {"css", "html", "javascript", "react", "typescript"} <= preferred
    assert must.isdisjoint(preferred)
