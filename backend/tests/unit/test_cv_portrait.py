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


# The headline must never confer titles; the fallback is tag-derived.
def test_headline_compliance_and_fallback() -> None:
    from cv_portrait.service import _fallback_headline, headline_compliant

    assert headline_compliant("主要涉及LLM應用開發") is True
    for inflated in ("AI與NLP專家", "資深數據分析", "Expert in NLP", "Senior後端開發"):
        assert headline_compliant(inflated) is False
    assert _fallback_headline(["LLM應用開發", "Python", "教學設計"]) == "主要涉及:LLM應用開發、Python、教學設計"
    assert _fallback_headline([]) == "能力畫像見下方明細"


# An inflated headline triggers one corrective rewrite; if the model keeps
# conferring titles, the deterministic tag fallback wins.
def test_inflated_headline_is_corrected_or_falls_back(tmp_path) -> None:
    import asyncio

    import pymupdf

    from cv_portrait.service import PortraitService
    from screening_core.hash_cache import HashCache

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 90), "Ann Lee Tester")
    page.insert_text((72, 130), "Built a tutoring platform with Python in 2025.")
    document.save(tmp_path / "cv2.pdf")
    document.close()

    base = {
        "headline": "AI專家",
        "overview": ["有平台交付經驗。"],
        "capability_tags": ["Python", "教學平台"],
        "strengths": [],
        "gaps": [],
        "reliability_flags": [],
        "interview_probes": [],
    }

    class _QueueStub:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = 0

        async def chat_completion(self, *_args, **_kwargs) -> dict:
            self.calls += 1
            return {"model": "glm-4-flash", "parsed": self.responses.pop(0)}

    # Case 1: rewrite succeeds -> descriptive headline kept.
    stub = _QueueStub([base, {"headline": "主要涉及Python教學平台開發"}])
    service = PortraitService(llm_client=stub, cache=HashCache(str(tmp_path / "c1")))
    result = asyncio.run(service.build_portrait(str(tmp_path / "cv2.pdf")))
    assert result["portrait"]["headline"] == "主要涉及Python教學平台開發"

    # Case 2: rewrite still inflated -> deterministic tag fallback.
    stub2 = _QueueStub([base, {"headline": "還是專家"}])
    service2 = PortraitService(llm_client=stub2, cache=HashCache(str(tmp_path / "c2")))
    result2 = asyncio.run(service2.build_portrait(str(tmp_path / "cv2.pdf")))
    assert result2["portrait"]["headline"] == "主要涉及:Python、教學平台"


# Flags never say the applicant failed to attach something; the system only
# reads the CV, so 未附/未提供 wording is deterministically rescoped.
def test_reliability_flags_are_scoped_to_the_cv() -> None:
    from cv_portrait.service import normalize_portrait

    portrait = normalize_portrait(
        {
            "headline": "ok",
            "reliability_flags": ["未附可驗證連結", "未提供具體的項目成果展示", "CV內未見量化結果"],
        },
        [],
    )
    assert portrait["reliability_flags"] == [
        "CV內未見可驗證連結",
        "CV內未見具體的項目成果展示",
        "CV內未見量化結果",
    ]
