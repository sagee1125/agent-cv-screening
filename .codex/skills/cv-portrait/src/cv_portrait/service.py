# Builds a JD-independent, evidence-cited capability portrait for one CV.
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from screening_core.config import settings
from screening_core.hash_cache import HashCache
from screening_core.llm_client import LLMClient, cv_llm_timeout
from cv_parser.helpers import extract_contact_hints
from cv_parser.local_ner import detect_local_pii
from cv_parser.ocr import extract_local_cv_document
from cv_parser.pii import contact_values_for_redaction, mask_pii_text_aggressive
from cv_parser.service import CVParserService
from cv_portrait.prompts import PORTRAIT_SYSTEM_PROMPT, build_portrait_user_prompt
from word_convert.converter import convert_to_pdf, detect_kind

PORTRAIT_CACHE_VERSION = "portrait-v5"

# Title-conferral words the headline must never contain: a CV line does not
# make someone an expert, and LLMs default to inflated LinkedIn-style titles.
_INFLATED_TITLE_WORDS = (
    "專家",
    "專才",
    "資深",
    "顶尖",
    "頂尖",
    "权威",
    "權威",
    "expert",
    "senior",
    "specialist",
    "guru",
)


def headline_compliant(headline: str) -> bool:
    folded = headline.casefold()
    return not any(word in folded for word in _INFLATED_TITLE_WORDS)


# Deterministic descriptive fallback built from the (grounded) capability tags.
def _fallback_headline(tags: list[str]) -> str:
    top = [tag for tag in tags if tag][:3]
    if not top:
        return "能力畫像見下方明細"
    return "主要涉及:" + "、".join(top)
PORTRAIT_MAX_TOKENS = 1500

# Claim lists are capped so a verbose model cannot balloon the output tokens.
_MAX_OVERVIEW = 5
_MAX_TAGS = 10
_MAX_CLAIMS = 4
_MAX_EVIDENCE = 2
_MAX_PROBES = 3
_MAX_HEADLINE_CHARS = 60
# Quotes shorter than this cannot be matched meaningfully after normalisation.
_MIN_VERIFIABLE_CHARS = 6


# Resolves a submission to a real PDF, converting Word locally when needed.
def _resolve_pdf(file_path: Path, converted_pdf: str | None) -> Path:
    kind = detect_kind(file_path)
    if kind == "pdf":
        return file_path
    if kind not in {"doc", "docx"}:
        raise ValueError("Unsupported CV file type; submit a PDF or a Word document.")
    if converted_pdf and Path(converted_pdf).is_file():
        return Path(converted_pdf)
    target = Path(converted_pdf) if converted_pdf else file_path.with_name(
        f"{file_path.stem}.converted.pdf"
    )
    convert_to_pdf(file_path, target)
    return target


# Masking normaliser shared by quote verification: case-fold, unify the wide
# family of dashes/quotes to spaces, collapse all whitespace.
def _norm_text(text: str) -> str:
    folded = text.casefold()
    folded = re.sub(r"[^\w\u3400-\u9fff]+", " ", folded)
    return " ".join(folded.split())


# A quote verifies when its normalised form is contained in the masked page.
def _quote_verified(quote: str, page: Any, masked_pages: list[str]) -> bool:
    try:
        page_no = int(page)
    except (TypeError, ValueError):
        return False
    if not 1 <= page_no <= len(masked_pages):
        return False
    needle = _norm_text(str(quote))
    if len(needle) < _MIN_VERIFIABLE_CHARS:
        return False
    return needle in _norm_text(masked_pages[page_no - 1])


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_evidence(items: Any, masked_pages: list[str]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    evidence: list[dict[str, Any]] = []
    for item in items[:_MAX_EVIDENCE]:
        if not isinstance(item, dict):
            continue
        quote = _clean_text(item.get("quote"))
        if not quote:
            continue
        evidence.append(
            {
                "page": item.get("page"),
                "quote": quote,
                "verified": _quote_verified(quote, item.get("page"), masked_pages),
            }
        )
    return evidence


def _normalize_claims(items: Any, masked_pages: list[str]) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    claims: list[dict[str, Any]] = []
    for item in items[:_MAX_CLAIMS]:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = _clean_text(item.get("text"))
        if not text:
            continue
        claims.append(
            {
                "text": text,
                "evidence": _normalize_evidence(item.get("evidence"), masked_pages),
            }
        )
    return claims


# Bounds the model output to the promised schema and stamps each quote with a
# local verification result, so a fabricated citation is displayed as such.
def normalize_portrait(parsed: dict[str, Any], masked_pages: list[str]) -> dict[str, Any]:
    headline = _clean_text(parsed.get("headline"))[:_MAX_HEADLINE_CHARS]
    overview = [
        _clean_text(line) for line in (parsed.get("overview") or [])[:_MAX_OVERVIEW] if _clean_text(line)
    ]
    tags = [
        _clean_text(tag) for tag in (parsed.get("capability_tags") or [])[:_MAX_TAGS] if _clean_text(tag)
    ]
    flags = [
        _clean_text(flag) for flag in (parsed.get("reliability_flags") or [])[:3] if _clean_text(flag)
    ]
    probes = [
        _clean_text(q) for q in (parsed.get("interview_probes") or [])[:_MAX_PROBES] if _clean_text(q)
    ]
    return {
        "headline": headline,
        "overview": overview,
        "capability_tags": tags,
        "strengths": _normalize_claims(parsed.get("strengths"), masked_pages),
        "gaps": _normalize_claims(parsed.get("gaps"), masked_pages),
        "reliability_flags": flags,
        "interview_probes": probes,
    }


def evidence_stats(portrait: dict[str, Any]) -> dict[str, int]:
    verified = 0
    total = 0
    for key in ("strengths", "gaps"):
        for claim in portrait.get(key) or []:
            for item in claim.get("evidence") or []:
                total += 1
                verified += 1 if item.get("verified") else 0
    return {"verified": verified, "unverified": total - verified}


class PortraitService:
    # Stores the LLM client and hash cache used by build_portrait.
    def __init__(self, llm_client: LLMClient, cache: HashCache) -> None:
        self.llm_client = llm_client
        self.cache = cache

    # Asks the model once to rephrase an inflated headline descriptively.
    async def _rewrite_headline(self, portrait: dict[str, Any]) -> str | None:
        system = (
            "You rephrase CV summary headlines. Output exactly one JSON object "
            '{"headline": "..."} and nothing else. The headline must DESCRIBE '
            "what the person mainly works on (e.g. 主要涉及…, 擅長…, 以…為主), "
            "never confer a title, and must not contain 專家/專才/資深/expert/"
            "senior/specialist. Max ~30 Traditional Chinese characters."
        )
        user = (
            "Capability tags: "
            + ", ".join(portrait.get("capability_tags") or [])
            + "\nCurrent (inflated) headline: "
            + str(portrait.get("headline") or "")
            + "\nOverview: "
            + " / ".join(portrait.get("overview") or [])
            + "\nRewrite the headline descriptively."
        )
        try:
            result = await self.llm_client.chat_completion(
                system,
                user,
                response_format={"type": "json_object"},
                temperature=0,
                seed=42,
                timeout=cv_llm_timeout(),
                max_tokens=120,
            )
        except Exception:
            logger.warning("Headline rewrite call failed; using tag fallback.", exc_info=True)
            return None
        rewritten = _clean_text((result.get("parsed") or {}).get("headline"))[:_MAX_HEADLINE_CHARS]
        return rewritten if rewritten and headline_compliant(rewritten) else None

    # Builds (or reuses from cache) one candidate's capability portrait.
    async def build_portrait(
        self, file_path: str, converted_pdf: str | None = None
    ) -> dict[str, Any]:
        source = Path(file_path)
        file_hash = await self.cache.md5_for_file(str(source))
        cache_key = f"{file_hash}-{PORTRAIT_CACHE_VERSION}"
        cached = await self.cache.get(cache_key)
        if cached:
            return {"file_hash": file_hash, "cache_hit": True, **cached}

        pdf_path = _resolve_pdf(source, converted_pdf)
        document = await _extract_document(pdf_path)
        raw_text = document.raw_text
        if len(raw_text.strip()) < settings.cv_ocr_min_page_chars:
            return {
                "file_hash": file_hash,
                "cache_hit": False,
                "status": "fallback",
                "portrait": None,
                "error_message": "portrait_error=cv_not_readable",
            }

        # Same local PII pipeline as cv-parser: detect the candidate name on the
        # WHOLE document, then mask every page with the same detections. The
        # whole-document name must be passed into each page's masking, because a
        # name reappearing deep inside a later page (e.g. as a publication
        # author) is only found when the candidate comes from outside that page.
        heuristic_hints = extract_contact_hints(raw_text)
        mask_names: list[str] = []
        sensitive: list[str] = []
        if document.ocr_page_indexes or not heuristic_hints.get("name"):
            local_pii = detect_local_pii(raw_text)
            mask_names = list(local_pii.names)
            sensitive = list(local_pii.sensitive_values)
        hint_name = heuristic_hints.get("name")
        if hint_name:
            mask_names = [hint_name] + [n for n in mask_names if n != hint_name]
        masked_pages = [
            mask_pii_text_aggressive(page_text, mask_names, sensitive)
            for page_text in document.page_texts
        ]
        pii_values = contact_values_for_redaction(raw_text, mask_names, sensitive)
        paged_text = "\n\n".join(
            f"[Page {index}]\n{page_masked}"
            for index, page_masked in enumerate(masked_pages, start=1)
            if page_masked.strip()
        )
        user_prompt = build_portrait_user_prompt(paged_text)
        # The same pre-send guard as the parser, scoped to the CV body only:
        # the fixed instruction preamble cannot leak anything, and a detected
        # value that coincidentally matches the schema wording (e.g. a
        # three-character value hitting "2-4 strengths") must not block the
        # portrait on a false positive.
        CVParserService._assert_prompt_clean(paged_text, "\n".join(masked_pages), pii_values)

        llm_result = await self.llm_client.chat_completion(
            PORTRAIT_SYSTEM_PROMPT,
            user_prompt,
            response_format={"type": "json_object"},
            temperature=0,
            seed=42,
            timeout=cv_llm_timeout(),
            max_tokens=PORTRAIT_MAX_TOKENS,
        )
        portrait = normalize_portrait(llm_result["parsed"], masked_pages)
        if not headline_compliant(portrait.get("headline") or ""):
            # One corrective rewrite; if the model still confers a title, fall
            # back to a deterministic descriptive headline from the tags.
            portrait["headline"] = await self._rewrite_headline(portrait) or _fallback_headline(
                portrait.get("capability_tags") or []
            )
        payload = {
            "status": "success",
            "portrait": portrait,
            "evidence_stats": evidence_stats(portrait),
            "model": llm_result["model"],
            "extraction_seed": 42,
        }
        # Only successful portraits are cached; fallbacks retry on a later run.
        await self.cache.set(cache_key, payload)
        return {"file_hash": file_hash, "cache_hit": False, **payload}


async def _extract_document(pdf_path: Path):
    return await asyncio.to_thread(extract_local_cv_document, pdf_path)


# Builds a portrait service with the shared LLM client and on-disk cache.
def build_portrait_service() -> PortraitService:
    return PortraitService(llm_client=LLMClient(), cache=HashCache(settings.cache_dir))
