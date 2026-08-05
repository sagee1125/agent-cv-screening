from __future__ import annotations

from typing import Any

import pytest

from app.services.parser import CVParserService


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
