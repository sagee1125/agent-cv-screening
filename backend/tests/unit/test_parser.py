from __future__ import annotations

from typing import Any

import pytest

from app.services.cv_parser import CVParserService


class DummyCache:
    def __init__(self, cached: dict[str, Any] | None = None) -> None:
        self.cached = cached
        self.saved_key: str | None = None
        self.saved_value: dict[str, Any] | None = None

    async def md5_for_file(self, _: str) -> str:
        return "abc123"

    async def get(self, _: str) -> dict[str, Any] | None:
        return self.cached

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self.saved_key = key
        self.saved_value = value


class DummyLLM:
    def __init__(self) -> None:
        self.called = False

    async def chat_completion(self, *_: Any, **__: Any) -> dict[str, Any]:
        self.called = True
        return {
            "model": "gpt-4o-mini",
            "parsed": {
                "name": "Alice",
                "email": "alice@example.com",
                "phone": None,
                "education": [],
                "experience": [],
                "skills": ["Python"],
                "publications": [],
            },
        }


@pytest.mark.asyncio
async def test_parse_cv_cache_hit_uses_cached_payload() -> None:
    cache = DummyCache(
        {
            "structured_data": {"name": "Cache User"},
            "raw_llm_response": {"name": "Cache User"},
            "status": "success",
        }
    )
    llm = DummyLLM()
    service = CVParserService(llm_client=llm, cache=cache)

    result = await service.parse_cv("any.pdf")

    assert result["cache_hit"] is True
    assert result["structured_data"]["name"] == "Cache User"
    assert llm.called is False


@pytest.mark.asyncio
async def test_parse_cv_cache_miss_stores_structured_and_raw() -> None:
    cache = DummyCache()
    llm = DummyLLM()
    service = CVParserService(llm_client=llm, cache=cache)
    async def fake_extract(_: str) -> str:
        return "cv text"

    service._extract_pdf_text = fake_extract  # type: ignore[method-assign]

    result = await service.parse_cv("resume.pdf")

    assert result["cache_hit"] is False
    assert result["status"] == "success"
    assert result["structured_data"]["name"] == "Alice"
    assert result["raw_llm_response"]["name"] == "Alice"
    assert cache.saved_key == "abc123"
    assert cache.saved_value is not None
    assert cache.saved_value["structured_data"]["skills"] == ["Python"]


def test_normalize_schema_handles_aliases_and_string_payloads() -> None:
    payload = {
        "name": "Bob",
        "technical_skills": "Python, FastAPI; PostgreSQL",
        "educations": "MSc in Computer Science, MIT 2020",
        "work_experience": {"company": "ACME", "role": "Engineer", "from": "2021-01", "to": "2023-02"},
        "publication": "Efficient CV Parsing 2022",
    }

    normalized = CVParserService._normalize_schema(payload)

    assert normalized["skills"] == ["Python", "FastAPI", "PostgreSQL"]
    assert "MIT 2020" in normalized["education"][0]["school"]
    assert normalized["education"][0]["degree"] == "Master"
    assert normalized["experience"][0]["title"] == "Engineer"
    assert normalized["publications"][0]["title"] == "Efficient CV Parsing 2022"


def test_apply_content_fallback_recovers_sections_when_arrays_empty() -> None:
    service = CVParserService(llm_client=DummyLLM(), cache=DummyCache())
    raw_text = """
    Skills:
    Python, FastAPI, Docker
    Education:
    MPhil in Computer Science, National Taiwan University 2021
    Experience:
    Backend Engineer at ACME 2021-2024
    Publications:
    Practical LLM Systems 2023
    """

    enriched = service._apply_content_fallback(
        raw_text,
        {"skills": [], "education": [], "experience": [], "publications": []},
    )

    assert "Python" in enriched["skills"]
    assert "National Taiwan University" in enriched["education"][0]["school"]
    assert enriched["education"][0]["degree"] == "MPhil"
    assert "ACME" in enriched["experience"][0]["description"]
    assert enriched["publications"][0]["year"] == "2023"


def test_normalize_experience_extracts_fields_from_text_line() -> None:
    payload = {
        "experience": [
            "Senior Backend Engineer at ACME Corp 2021-01 - 2024-03 built APIs and services"
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    first = normalized["experience"][0]
    assert first["title"] is not None
    assert first["company"] == "ACME Corp"
    assert first["start_date"] == "2021-01"
    assert first["end_date"] == "2024-03"


def test_merge_contact_hints_prefers_bracket_phone_format() -> None:
    merged = CVParserService._merge_contact_hints(
        {"phone": "+852 61234567"},
        {"phone": "+852 (6123) 4567", "email": None, "name": None},
    )
    assert merged["phone"] == "+852 (6123) 4567"


def test_normalize_education_uses_major_for_degree_only_line() -> None:
    payload = {
        "education": [
            "Master of Engineering (MEng) in Aerospace Engineering",
            "Imperial College London",
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    assert normalized["education"][0]["school"] == "Aerospace Engineering"
    assert normalized["education"][0]["degree"] == "Master"
    assert normalized["education"][1]["school"] == "Imperial College London"


def test_normalize_education_drops_date_location_only_line() -> None:
    payload = {
        "education": [
            "01/2008 - 01/2012 London",
            "Bachelor of Engineering (BEng) in Mechanical Engineering",
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    schools = [item["school"] for item in normalized["education"]]
    assert "01/2008 - 01/2012 London" not in schools
    assert "Mechanical Engineering" in schools
