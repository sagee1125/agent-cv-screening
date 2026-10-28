# Unit tests for the cv-portrait skill: quote verification, normalisation,
# end-to-end build with a stubbed LLM, and the per-CV-file cache.
import asyncio
import json
from pathlib import Path

import pymupdf

from cv_portrait.service import (
    PortraitService,
    _norm_text,
    _quote_verified,
    evidence_stats,
    normalize_portrait,
)
from screening_core.hash_cache import HashCache


# Normalisation collapses case, punctuation and whitespace families.
def test_norm_text_and_quote_verified() -> None:
    page = "Built a multi-agent tutoring platform with Python and FastAPI in 2025."
    assert _quote_verified("multi-agent tutoring platform", 1, [page]) is True
    # Whitespace and punctuation variants still verify.
    assert _quote_verified("multi—agent   TUTORING, platform", 1, [page]) is True
    # A fabricated quote must not verify.
    assert _quote_verified("won a best-paper award at NeurIPS", 1, [page]) is False
    # Wrong page or out-of-range page must not verify.
    assert _quote_verified("multi-agent tutoring platform", 2, [page]) is False
    assert _quote_verified("multi-agent tutoring platform", 0, [page]) is False
    # Too short to verify meaningfully.
    assert _quote_verified("py", 1, [page]) is False
    # CJK text verifies through the same normaliser.
    cjk_page = "負責開發多智能體語言學習平台的核心模組。"
    assert _quote_verified("多智能體語言學習平台", 1, [cjk_page]) is True


# The normaliser caps every list and stamps verified flags per evidence item.
def test_normalize_portrait_caps_and_flags() -> None:
    pages = ["Led a team of five engineers to ship the platform."]
    parsed = {
        "headline": "h" * 200,
        "overview": [f"point {i}" for i in range(10)],
        "capability_tags": [f"tag{i}" for i in range(20)],
        "strengths": [
            {
                "text": "shipped platform",
                "evidence": [
                    {"page": 1, "quote": "ship the platform."},
                    {"page": 1, "quote": "won a Nobel prize"},
                    {"page": 1, "quote": "third ignored"},
                ],
            }
        ]
        + [{"text": f"extra {i}"} for i in range(6)],
        "gaps": [],
        "reliability_flags": [f"f{i}" for i in range(9)],
        "interview_probes": [f"q{i}" for i in range(9)],
    }
    portrait = normalize_portrait(parsed, pages)
    assert len(portrait["headline"]) == 60
    assert len(portrait["overview"]) == 5
    assert len(portrait["capability_tags"]) == 10
    assert len(portrait["strengths"]) == 4
    assert len(portrait["reliability_flags"]) == 3
    assert len(portrait["interview_probes"]) == 3
    evidence = portrait["strengths"][0]["evidence"]
    assert len(evidence) == 2
    assert evidence[0]["verified"] is True
    assert evidence[1]["verified"] is False
    assert evidence_stats(portrait) == {"verified": 1, "unverified": 1}


class _StubLLM:
    """Records calls and returns one canned portrait payload."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def chat_completion(self, *_args, **_kwargs) -> dict:
        self.calls += 1
        return {"model": "glm-4-flash", "parsed": self.payload}


def _write_cv(tmp_path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 90), "Jane Doe Tester")
    page.insert_text((72, 120), "jane.doe@example.com")
    page.insert_text(
        (72, 150),
        "Built a multi-agent tutoring platform with Python and FastAPI in 2025.",
    )
    document.save(tmp_path / "cv.pdf")
    document.close()
    return tmp_path / "cv.pdf"


# End to end: masked input, verified + unverified quotes, cache reuse.
def test_build_portrait_end_to_end_and_cache(tmp_path) -> None:
    cv = _write_cv(tmp_path)
    payload = {
        "headline": "多智能體教學平台開發者",
        "overview": ["有具體平台交付經驗。"],
        "capability_tags": ["LLM應用開發", "Python"],
        "strengths": [
            {
                "text": "親自交付過多智能體教學平台。",
                "evidence": [
                    {"page": 1, "quote": "multi-agent tutoring platform with Python"},
                    {"page": 1, "quote": "managed a 30-person research lab"},
                ],
            }
        ],
        "gaps": [{"text": "CV未展現正式教學經驗。", "evidence": []}],
        "reliability_flags": [],
        "interview_probes": ["請現場演示平台的 agent 編排模組。"],
    }
    stub = _StubLLM(payload)
    service = PortraitService(llm_client=stub, cache=HashCache(str(tmp_path / "cache")))

    result = asyncio.run(service.build_portrait(str(cv)))
    assert result["status"] == "success"
    assert result["cache_hit"] is False
    portrait = result["portrait"]
    evidence = portrait["strengths"][0]["evidence"]
    assert evidence[0]["verified"] is True
    assert evidence[1]["verified"] is False
    # The redacted prompt never carries the candidate's email or name.
    # (Guarded upstream by _assert_prompt_clean; a leak would raise instead.)

    second = asyncio.run(service.build_portrait(str(cv)))
    assert second["cache_hit"] is True
    assert stub.calls == 1  # cached, no second LLM call

    # A changed CV (different bytes) is a new cache entry and re-evaluates.
    cv.write_bytes(cv.read_bytes() + b"%pad\n")
    third = asyncio.run(service.build_portrait(str(cv)))
    assert third["cache_hit"] is False
    assert stub.calls == 2
