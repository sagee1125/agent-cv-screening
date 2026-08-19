# Unit tests for pluggable JD enrichment providers and parser modes.
from __future__ import annotations

import importlib.util
import json
from typing import Any

import pytest

from app.services.jd_parser import (
    JDParserService,
    build_enrichment_provider,
    normalize_mode,
)
from app.services.jd_parser.providers.llm_refiner import LLMRefinerProvider
from app.services.jd_parser.providers.qwen import QwenJDExtractorProvider

SAMPLE_JD = """Senior Backend Engineer

Requirements:
- 3+ years of experience with Python and FastAPI
- Must have Docker
- Nice to have: AWS, Kubernetes
"""


class FakeLLM:
    """Duck-typed stand-in for LLMClient used in hybrid-mode tests."""

    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        """Store a canned payload or an error to raise on call."""
        self.payload = payload
        self.error = error
        self.calls = 0
        self.last_messages: list[dict[str, Any]] = []

    async def chat_completion_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
        temperature: float = 0,
        seed: int = 42,
        allow_json_repair: bool = True,
    ) -> dict[str, Any]:
        """Record the call and return the canned payload or raise the configured error."""
        self.calls += 1
        self.last_messages = messages
        if self.error:
            raise self.error
        return {"model": model or "fake", "parsed": self.payload, "raw_content": json.dumps(self.payload)}


@pytest.mark.asyncio
async def test_rule_mode_default_output() -> None:
    """Rule mode keeps the original deterministic parse path and output."""
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD)
    assert result["parse_path"] == "jd_preprocessed_rule_parser"
    assert result["structured_data"]["must_skills"]
    assert "enrichment_provider" not in result["raw_llm_response"]


@pytest.mark.asyncio
async def test_rule_mode_uses_hit_line_source_sentence() -> None:
    """Rule mode attaches the original hit line, not the JD prefix, per skill."""
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD)
    data = result["structured_data"]
    by_name = {item["display_name"].lower(): item["provenance"]["source_sentence"] for item in data["must_skills"]}
    assert "python" in by_name
    assert by_name["python"] == "3+ years of experience with Python and FastAPI"
    assert "docker" in by_name
    assert by_name["docker"] == "Must have Docker"
    assert by_name["python"] != by_name["docker"]
    python_item = next(item for item in data["must_skills"] if item["display_name"].lower() == "python")
    start = python_item["provenance"]["source_char_start"]
    end = python_item["provenance"]["source_char_end"]
    assert SAMPLE_JD[start:end] == by_name["python"]
    assert data["language_requirements"][0]["provenance"] == ""
    assert data["education_requirement"]["provenance"] == ""
    assert data["visa_requirement"]["provenance"] == ""


@pytest.mark.asyncio
async def test_hybrid_mode_refines_skills_with_llm() -> None:
    """Hybrid mode replaces rule skills with LLM-refined skills and evidence."""
    llm = FakeLLM(
        {
            "must_skills": ["python", "fastapi", "docker"],
            "preferred_skills": ["aws"],
            "reasoning_trace": [
                {
                    "skill": "python",
                    "bucket": "must",
                    "evidence": "3+ years of experience with Python and FastAPI",
                    "confidence": 0.95,
                }
            ],
        }
    )
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD, mode="hybrid", enrichment_provider=LLMRefinerProvider(llm_client=llm))
    assert result["parse_path"] == "jd_hybrid_parser"
    data = result["structured_data"]
    assert [item["display_name"] for item in data["must_skills"]] == ["Python", "Fastapi", "Docker"]
    assert data["must_skills"][0]["provenance"]["confidence"] == 0.95
    assert data["must_skills"][0]["provenance"]["source_sentence"].startswith("3+ years")
    assert data["preferred_skills"][0]["display_name"] == "Aws"
    assert "AWS" in data["preferred_skills"][0]["provenance"]["source_sentence"]
    assert llm.calls == 1
    assert llm.last_messages[0]["role"] == "system"


@pytest.mark.asyncio
async def test_hybrid_uses_premap_phrase_when_not_in_taxonomy() -> None:
    """Unmapped LLM skill names still attach the original JD sentence that mentioned them."""
    jd = SAMPLE_JD + "\n- Experience with distributed systems\n"
    llm = FakeLLM(
        {
            "must_skills": ["python", "distributed systems"],
            "preferred_skills": [],
            "reasoning_trace": [],
        }
    )
    service = JDParserService()
    result = await service.parse_jd(jd, mode="hybrid", enrichment_provider=LLMRefinerProvider(llm_client=llm))
    data = result["structured_data"]
    by_name = {item["display_name"].lower(): item["provenance"]["source_sentence"] for item in data["must_skills"]}
    assert by_name["python"] == "3+ years of experience with Python and FastAPI"
    assert by_name["distributed systems"] == "Experience with distributed systems"


@pytest.mark.asyncio
async def test_hybrid_empty_source_when_skill_not_in_jd() -> None:
    """Skills that cannot be located in the JD leave source_sentence empty."""
    llm = FakeLLM(
        {
            "must_skills": ["python", "telepathy"],
            "preferred_skills": [],
            "reasoning_trace": [{"skill": "telepathy", "bucket": "must", "evidence": "invented", "confidence": 0.9}],
        }
    )
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD, mode="hybrid", enrichment_provider=LLMRefinerProvider(llm_client=llm))
    telepathy = next(item for item in result["structured_data"]["must_skills"] if item["display_name"].lower() == "telepathy")
    assert telepathy["provenance"]["source_sentence"] == ""
    assert telepathy["provenance"]["confidence"] == 0.9
    assert "extracted_name" not in telepathy


@pytest.mark.asyncio
async def test_hybrid_falls_back_when_llm_fails() -> None:
    """Hybrid mode keeps rule output when the LLM call raises."""
    llm = FakeLLM(error=RuntimeError("boom"))
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD, mode="hybrid", enrichment_provider=LLMRefinerProvider(llm_client=llm))
    assert result["parse_path"] == "jd_hybrid_fallback_rule_parser"
    assert result["structured_data"]["must_skills"]
    assert result["raw_llm_response"]["enrichment_notes"]


@pytest.mark.asyncio
async def test_hybrid_falls_back_when_llm_returns_no_skills() -> None:
    """Hybrid mode keeps rule output when the LLM returns empty skills."""
    llm = FakeLLM({"must_skills": [], "preferred_skills": [], "reasoning_trace": []})
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD, mode="hybrid", enrichment_provider=LLMRefinerProvider(llm_client=llm))
    assert result["parse_path"] == "jd_hybrid_fallback_rule_parser"
    assert result["structured_data"]["must_skills"]


@pytest.mark.asyncio
async def test_hybrid_dedupes_overlapping_skills() -> None:
    """Preferred skills that overlap must skills are dropped."""
    llm = FakeLLM(
        {
            "must_skills": ["python", "docker"],
            "preferred_skills": ["docker", "aws"],
            "reasoning_trace": [],
        }
    )
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD, mode="hybrid", enrichment_provider=LLMRefinerProvider(llm_client=llm))
    data = result["structured_data"]
    preferred = [item["canonical_skill"] for item in data["preferred_skills"]]
    assert "docker" not in preferred
    assert "aws" in preferred


@pytest.mark.asyncio
async def test_qwen_provider_maps_overview() -> None:
    """Qwen provider adds a rich jd_overview while keeping rule skills."""
    provider = QwenJDExtractorProvider(model_id="fake-model")

    async def fake_generate(_: str) -> dict[str, Any]:
        return {
            "job_titles": ["Senior Data Engineer"],
            "company_name": "Acme",
            "company_website": "https://acme.example.com",
            "technical_skills": ["Python", "Spark"],
            "compensation": {"currency": "HKD", "min": 55000},
            "location": "Hong Kong",
            "work_mode": "Hybrid",
        }

    provider._generate_json = fake_generate  # type: ignore[method-assign]
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD, mode="qwen", enrichment_provider=provider)
    assert result["parse_path"] == "jd_qwen_parser"
    overview = result["structured_data"]["jd_overview"]
    assert overview["job_titles"] == ["Senior Data Engineer"]
    assert overview["company"]["name"] == "Acme"
    assert overview["skills"] == ["Python", "Spark"]
    assert overview["location"] == "Hong Kong"
    assert result["structured_data"]["must_skills"]


@pytest.mark.asyncio
async def test_qwen_falls_back_when_model_fails() -> None:
    """Qwen mode keeps rule output when model inference fails."""
    provider = QwenJDExtractorProvider(model_id="fake-model")

    async def fake_generate(_: str) -> dict[str, Any]:
        raise RuntimeError("model unavailable")

    provider._generate_json = fake_generate  # type: ignore[method-assign]
    service = JDParserService()
    result = await service.parse_jd(SAMPLE_JD, mode="qwen", enrichment_provider=provider)
    assert result["parse_path"] == "jd_qwen_fallback_rule_parser"
    assert "jd_overview" not in result["structured_data"]
    assert result["structured_data"]["must_skills"]


def test_qwen_is_available_false_without_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Availability probe returns False when torch/transformers are missing."""
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name in ("torch", "transformers") else object(),
    )
    assert QwenJDExtractorProvider.is_available() is False


def test_factory_modes() -> None:
    """Factory maps modes to providers and normalizes unknown values."""
    assert normalize_mode("Hybrid") == "hybrid"
    assert normalize_mode(" unknown ") == "rule"
    assert normalize_mode(None) == "rule"
    assert build_enrichment_provider("rule") is None
    assert isinstance(build_enrichment_provider("hybrid", llm_client=object()), LLMRefinerProvider)
    assert isinstance(build_enrichment_provider("qwen"), QwenJDExtractorProvider)


@pytest.mark.asyncio
async def test_empty_input_any_mode() -> None:
    """Empty JD returns invalid_input regardless of mode."""
    service = JDParserService()
    for mode in ("rule", "hybrid", "qwen"):
        result = await service.parse_jd("   ", mode=mode)
        assert result["status"] == "invalid_input"
        assert result["structured_data"] is None


@pytest.mark.asyncio
async def test_alias_skill_keeps_original_mention_line() -> None:
    """Taxonomy aliases locate the pre-map mention in the original JD line."""
    service = JDParserService()
    jd = "Requirements:\n- Must have postgres\n"
    result = await service.parse_jd(jd)
    postgres = next(
        item
        for item in result["structured_data"]["must_skills"]
        if item["canonical_skill"] == "postgresql"
    )
    assert postgres["provenance"]["source_sentence"] == "Must have postgres"


@pytest.mark.asyncio
async def test_requirement_fields_use_cue_lines() -> None:
    """Language, education, and visa provenance use the matching JD line."""
    service = JDParserService()
    jd = """Requirements:
- Python
- Bachelor's degree
- Visa sponsorship required
- English fluency
"""
    result = await service.parse_jd(jd)
    data = result["structured_data"]
    assert "English" in data["language_requirements"][0]["provenance"]
    assert "Bachelor" in data["education_requirement"]["provenance"]
    assert "Visa" in data["visa_requirement"]["provenance"]