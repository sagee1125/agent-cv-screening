# Unit tests for JD language requirement extraction vs skill buckets.
from __future__ import annotations

import pytest

from app.services.jd_parser import JDParserService
from app.services.jd_parser.providers.llm_refiner import LLMRefinerProvider

from tests.unit.test_jd_parser_providers import FakeLLM, SAMPLE_JD


@pytest.mark.asyncio
async def test_languages_go_to_language_requirements_not_skills() -> None:
    """English, Chinese, and Cantonese fill language_requirements, not must_skills."""
    jd = """Requirements:
- (c) have excellent written and verbal communication skills in both English and Chinese (both Cantonese and Putonghua);
- Must have proficiency in MS Office
"""
    service = JDParserService()
    result = await service.parse_jd(jd)
    data = result["structured_data"]
    languages = {item["language"]: item for item in data["language_requirements"]}
    assert set(languages) == {"English", "Chinese", "Cantonese"}
    assert languages["English"]["is_mandatory"] is True
    assert languages["Chinese"]["is_mandatory"] is True
    assert languages["Cantonese"]["is_mandatory"] is True
    assert languages["English"]["level"] == "fluent"
    assert "Cantonese" in languages["Cantonese"]["provenance"]
    assert "Chinese" in languages["Chinese"]["provenance"]
    skill_names = {
        item["canonical_skill"]
        for bucket in ("must_skills", "preferred_skills")
        for item in data[bucket]
    }
    assert "english" not in skill_names
    assert "chinese" not in skill_names
    assert "cantonese" not in skill_names
    assert "putonghua" not in skill_names


@pytest.mark.asyncio
async def test_no_language_line_yields_empty_language_requirements() -> None:
    """JDs that never mention a language do not emit a placeholder English row."""
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD)
    assert result["structured_data"]["language_requirements"] == []


@pytest.mark.asyncio
async def test_preferred_language_is_not_mandatory() -> None:
    """Languages under a preferred cue are kept but marked optional."""
    jd = """Requirements:
- Must have Python
- Nice to have: Japanese
"""
    service = JDParserService()
    result = await service.parse_jd(jd)
    languages = result["structured_data"]["language_requirements"]
    assert len(languages) == 1
    assert languages[0]["language"] == "Japanese"
    assert languages[0]["is_mandatory"] is False


@pytest.mark.asyncio
async def test_cjk_language_aliases_are_extracted() -> None:
    """Chinese-script language names map onto canonical language_requirements."""
    jd = """职位要求：
- 精通中文及英语
- Nice to have: 粤语
"""
    service = JDParserService()
    result = await service.parse_jd(jd)
    languages = {item["language"]: item for item in result["structured_data"]["language_requirements"]}
    assert set(languages) >= {"Chinese", "English", "Cantonese"}
    assert languages["Chinese"]["level"] == "fluent"
    assert languages["English"]["level"] == "fluent"
    assert languages["Cantonese"]["is_mandatory"] is False
    assert "中文" in languages["Chinese"]["provenance"]


@pytest.mark.asyncio
async def test_hybrid_strips_languages_from_refined_skills() -> None:
    """LLM-refined language labels are dropped from skill buckets."""
    llm = FakeLLM(
        {
            "must_skills": ["python", "chinese", "cantonese"],
            "preferred_skills": ["english"],
            "reasoning_trace": [],
        }
    )
    jd = SAMPLE_JD + "\n- Excellent English and Chinese (Cantonese)\n"
    service = JDParserService()
    result = await service.parse_jd(jd, mode="hybrid", enrichment_provider=LLMRefinerProvider(llm_client=llm))
    data = result["structured_data"]
    skill_names = {
        item["canonical_skill"]
        for bucket in ("must_skills", "preferred_skills")
        for item in data[bucket]
    }
    assert "python" in skill_names
    assert "chinese" not in skill_names
    assert "cantonese" not in skill_names
    assert "english" not in skill_names
    assert {item["language"] for item in data["language_requirements"]} >= {"English", "Chinese", "Cantonese"}
