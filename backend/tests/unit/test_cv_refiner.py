# Tests hybrid CV refinement merge logic (no live LLM).
from __future__ import annotations

from typing import Any

import pytest

from cv_parser.helpers import normalize_skill_items
from cv_parser.providers.zai import ZaiCVRefiner
from cv_parser.refine_merge import draft_needs_hybrid_pass, merge_cv_refinement
from cv_parser.service import CVParserService


def test_merge_prefers_split_dated_experience() -> None:
    base = {
        "summary": "Profile",
        "skills": ["sql"],
        "experience": [
            {
                "company": "Acme",
                "job_title": "Analyst",
                "description": "5 years experience in data governance and SQL.",
            }
        ],
    }
    refined = {
        "skills": ["sql", "data governance", "microsoft excel"],
        "experience": [
            {
                "company": "Acme",
                "job_title": "Business Analyst",
                "start_date": "2020-01",
                "end_date": "2023-06",
                "description": "Data governance and quality.",
                "skills_used": ["sql"],
            },
            {
                "company": "Beta Corp",
                "job_title": "Data Specialist",
                "start_date": "2023-07",
                "end_date": "Present",
                "description": "Metadata and profiling.",
                "skills_used": ["data governance"],
            },
        ],
    }
    merged = merge_cv_refinement(base, refined)
    assert len(merged["experience"]) == 2
    assert merged["experience"][0]["start_date"] == "2020-01"
    assert merged["experience"][1]["end_date"] == "Present"


def test_merge_keeps_base_when_refiner_adds_nothing() -> None:
    base = {
        "experience": [
            {
                "company": "Acme",
                "job_title": "Engineer",
                "start_date": "2021-01",
                "end_date": "2024-01",
                "description": "Python APIs.",
            }
        ],
        "skills": ["python"],
    }
    refined = {"experience": [], "skills": []}
    merged = merge_cv_refinement(base, refined)
    assert len(merged["experience"]) == 1
    assert merged["experience"][0]["start_date"] == "2021-01"


# Refined languages replace a wrong first pass, and skills absent from the CV are dropped.
def test_merge_overwrites_languages_and_drops_unmentioned_skills() -> None:
    base = {"languages": [{"language": "French", "level": None}], "skills": ["sql"], "experience": []}
    refined = {
        "languages": [{"language": "English", "level": "fluent"}, {"language": "Chinese", "level": "business"}],
        "skills": ["sql", "telepathy"],
        "experience": [],
    }
    merged = merge_cv_refinement(
        base,
        refined,
        evidence_text="Fluent in English and Chinese. SQL and Excel.",
    )
    names = {item["language"] for item in merged["languages"]}
    assert names == {"French", "English", "Chinese"}
    skill_names = {
        (item.get("canonical_skill") if isinstance(item, dict) else str(item)).casefold()
        for item in merged["skills"]
    }
    assert "telepathy" not in skill_names
    assert any("sql" in name for name in skill_names)


# A complete first pass does not need a second model call.
def test_complete_draft_skips_hybrid() -> None:
    complete = {
        "skills": ["sql", "python"],
        "languages": [{"language": "English"}],
        "experience": [
            {"start_date": "2020-01", "end_date": "2022-01"},
            {"start_date": "2022-02", "end_date": "Present"},
        ],
    }
    assert draft_needs_hybrid_pass(complete) is False


# Missing dates, skills, languages, or jobs still ask for a second pass.
def test_thin_draft_needs_hybrid() -> None:
    assert draft_needs_hybrid_pass({"skills": ["sql"], "languages": [], "experience": []}) is True
    assert draft_needs_hybrid_pass(
        {
            "skills": ["sql", "python"],
            "languages": [{"language": "English"}],
            "experience": [{"start_date": None}, {"start_date": None}, {"start_date": "2020-01"}],
        }
    ) is True
    assert draft_needs_hybrid_pass(
        {
            "skills": ["sql"],
            "languages": [{"language": "English"}],
            "experience": [{"start_date": "2020-01"}],
        }
    ) is True
    assert draft_needs_hybrid_pass(
        {
            "skills": ["sql", "python"],
            "languages": [],
            "experience": [{"start_date": "2020-01"}],
        }
    ) is True


# Sentence-length skill phrases are dropped. Short names stay, including duplicates.
def test_skill_phrases_longer_than_five_words_are_dropped() -> None:
    skills = normalize_skill_items(
        [
            "Python",
            "Python",
            "data governance",
            "responsible for data quality management across teams",
        ]
    )
    names = [item["canonical_skill"] for item in skills]
    assert names.count("python") == 1
    assert any("governance" in name for name in names)
    assert all(len(item["raw"].split()) <= 5 for item in skills)


class _RecordingClient:
    """Records the refinement request and returns a small JSON object."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] | None = None
        self.model: str | None = None

    # Stores the outgoing messages without calling Zhipu.
    async def chat_completion_messages(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.messages = messages
        self.model = kwargs.get("model")
        return {"parsed": {"skills": ["python"], "experience": [], "languages": []}, "model": self.model}


# Hybrid refinement sends redacted text only, even if a caller still passes image URLs.
@pytest.mark.asyncio
async def test_refiner_ignores_page_images() -> None:
    client = _RecordingClient()
    refiner = ZaiCVRefiner(llm_client=client)
    result = await refiner.refine(
        masked_cv_text="Python engineer from 2019 to 2023.",
        jd_text=None,
        draft_structured={"skills": []},
        redacted_image_urls=["data:image/png;base64,AAAA"],
    )
    assert result.succeeded
    assert client.messages is not None
    assert isinstance(client.messages[1]["content"], str)
    assert "data:image" not in client.messages[1]["content"]
    assert client.model != "glm-4v-flash"

    empty = await refiner.refine(
        masked_cv_text="   ",
        jd_text=None,
        draft_structured={},
        redacted_image_urls=["data:image/png;base64,AAAA"],
    )
    assert empty.error == "empty_redacted_content"


# A draft that already has dates, skills, and a language does not call the second model.
@pytest.mark.asyncio
async def test_complete_draft_does_not_call_the_refiner(monkeypatch: pytest.MonkeyPatch) -> None:
    from cv_parser import service as service_mod

    monkeypatch.setattr(service_mod.settings, "cv_parser_hybrid_enabled", True)

    class BoomProvider:
        """Fails the test if the second pass is invoked."""

        # Records that the second pass must not be called.
        async def refine(self, **_: Any) -> Any:
            raise AssertionError("second pass should not run")

    service = CVParserService(llm_client=object(), cache=object(), enrichment_provider=BoomProvider())
    structured = {
        "skills": ["python", "sql"],
        "languages": [{"language": "English"}],
        "experience": [{"start_date": "2020-01", "end_date": "2021-06"}],
    }
    merged, path, note = await service._apply_hybrid_refiner(structured, "python sql English", None, "text")
    assert path == "text"
    assert note == "hybrid_skipped=draft_complete"
    assert merged["skills"] == structured["skills"]
