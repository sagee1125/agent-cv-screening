# Orchestrates local layout reading, text redaction, and a text-only external parse.
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from cv_parser.providers.base import CVEnrichmentProvider
from cv_parser.refine_merge import draft_needs_hybrid_pass, merge_cv_refinement, retain_skill_mentions

from screening_core.config import settings
from screening_core.hash_cache import HashCache
from screening_core.llm_client import LLMClient, cv_llm_timeout
from cv_parser.local_ner import LocalNERResult, detect_local_pii
from cv_parser.helpers import (
    apply_content_fallback,
    as_list,
    build_compressed_prompt,
    combine_period,
    compress_cv_text,
    concat_text,
    digits_only,
    extract_company_from_text,
    extract_contact_hints,
    extract_date_range_from_text,
    extract_degree_from_text,
    extract_education_fallback,
    extract_experience_fallback,
    extract_institution_from_text,
    extract_major_from_text,
    extract_publications_fallback,
    extract_section_lines,
    extract_skills_fallback,
    extract_title_from_text,
    extract_year_from_text,
    is_valid_education_row,
    looks_like_date_location_line,
    merge_contact_hints,
    merge_fragmented_education_rows,
    merge_fragmented_experience_rows,
    normalize_education_items,
    normalize_education_school,
    normalize_experience_items,
    normalize_publication_items,
    normalize_schema,
    normalize_skill_items,
    prefer_phone_format,
    to_clean_text,
    unique_keep_order,
)
from cv_parser.ocr import LocalCVDocument, extract_local_cv_document
from cv_parser.pdf_utils import (
    extract_with_pdfplumber,
    extract_with_pymupdf,
    extract_with_pypdf,
    render_redacted_pdf_pages_as_data_urls,
    render_pdf_pages_as_data_urls,
)
from cv_parser.pii import (
    mask_pii_text,
    strip_contact_fields,
)
from cv_parser.prompts import PARSER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)
# v12 = 1.2.37: education degree_level is backfilled from the degree label on
# every parse path, so pre-1.2.37 caches (LLM-era entries with degree_level=None)
# must never be served again - they zeroed every LLM-grade CV at the hard filter.
PARSER_CACHE_VERSION = "pii-redaction-v13-degree-hierarchy"

# Markers that mean "the model refused the prompt because it was too long". The JD carries no cap
# (§2.11), so when this happens the failure must be legible: the recorded error names what was sent
# so a human can judge it, and the model's own limit — if its error states one — travels through
# verbatim in the exception text. A silent truncation here would quietly decide which part of the
# job matters, which is exactly the decision the cap removal delegated away.
_LENGTH_REJECTION_MARKERS = (
    "context_length_exceeded",
    "context length",
    "maximum context",
    "prompt too long",
    "too many tokens",
    "input too long",
    "request too large",
    "payload too large",
    "length limit",
    "token limit",
)


def _looks_like_length_rejection(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(marker in text for marker in _LENGTH_REJECTION_MARKERS)


class CVParserService:
    # Keep the original private method API as aliases for compatibility.
    _as_list = staticmethod(as_list)
    _normalize_schema = staticmethod(normalize_schema)
    _normalize_skill_items = staticmethod(normalize_skill_items)
    _normalize_education_items = staticmethod(normalize_education_items)
    _normalize_experience_items = staticmethod(normalize_experience_items)
    _normalize_publication_items = staticmethod(normalize_publication_items)
    _compress_cv_text = staticmethod(compress_cv_text)
    _merge_fragmented_experience_rows = staticmethod(merge_fragmented_experience_rows)
    _merge_fragmented_education_rows = staticmethod(merge_fragmented_education_rows)
    _to_clean_text = staticmethod(to_clean_text)
    _concat_text = staticmethod(concat_text)
    _extract_contact_hints = staticmethod(extract_contact_hints)
    _merge_contact_hints = staticmethod(merge_contact_hints)
    _unique_keep_order = staticmethod(unique_keep_order)
    _apply_content_fallback = staticmethod(apply_content_fallback)
    _extract_skills_fallback = staticmethod(extract_skills_fallback)
    _extract_education_fallback = staticmethod(extract_education_fallback)
    _extract_experience_fallback = staticmethod(extract_experience_fallback)
    _extract_publications_fallback = staticmethod(extract_publications_fallback)
    _extract_section_lines = staticmethod(extract_section_lines)
    _extract_degree_from_text = staticmethod(extract_degree_from_text)
    _extract_major_from_text = staticmethod(extract_major_from_text)
    _normalize_education_school = staticmethod(normalize_education_school)
    _extract_institution_from_text = staticmethod(extract_institution_from_text)
    _looks_like_date_location_line = staticmethod(looks_like_date_location_line)
    _is_valid_education_row = staticmethod(is_valid_education_row)
    _extract_year_from_text = staticmethod(extract_year_from_text)
    _extract_date_range_from_text = staticmethod(extract_date_range_from_text)
    _combine_period = staticmethod(combine_period)
    _extract_company_from_text = staticmethod(extract_company_from_text)
    _extract_title_from_text = staticmethod(extract_title_from_text)
    _digits_only = staticmethod(digits_only)
    _prefer_phone_format = staticmethod(prefer_phone_format)
    build_compressed_prompt = staticmethod(build_compressed_prompt)
    _extract_with_pdfplumber = staticmethod(extract_with_pdfplumber)
    _extract_with_pypdf = staticmethod(extract_with_pypdf)
    _extract_with_pymupdf = staticmethod(extract_with_pymupdf)
    _render_pdf_pages_as_data_urls = staticmethod(render_pdf_pages_as_data_urls)
    _render_redacted_pdf_pages_as_data_urls = staticmethod(render_redacted_pdf_pages_as_data_urls)
    _extract_local_cv_document = staticmethod(extract_local_cv_document)
    _detect_local_pii = staticmethod(detect_local_pii)

    # Stores the LLM client, hash cache, and optional hybrid refiner used by parse_cv.
    def __init__(
        self,
        llm_client: LLMClient,
        cache: HashCache,
        enrichment_provider: CVEnrichmentProvider | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.cache = cache
        self._enrichment_provider = enrichment_provider

    # Runs a second Zhipu pass on redacted text when hybrid refinement is enabled.
    async def _apply_hybrid_refiner(
        self,
        structured: dict[str, Any],
        masked_text: str,
        jd_text: str | None,
        parse_path: str,
    ) -> tuple[dict[str, Any], str, str | None]:
        """Merge hybrid refinement into the draft. Page images are never attached."""
        if masked_text.strip():
            structured = retain_skill_mentions(structured, masked_text)
        provider = self._enrichment_provider
        if provider is None or not settings.cv_parser_hybrid_enabled:
            return structured, parse_path, None
        if not masked_text.strip():
            return structured, parse_path, "hybrid_skipped=no_redacted_content"
        if not draft_needs_hybrid_pass(structured):
            return structured, parse_path, "hybrid_skipped=draft_complete"
        try:
            result = await provider.refine(
                masked_cv_text=masked_text,
                jd_text=jd_text,
                draft_structured=structured,
            )
        except Exception as exc:
            logger.exception("CV hybrid refiner failed")
            return structured, parse_path, f"hybrid_refiner={exc}"
        if not result.succeeded or not result.structured:
            reason = result.error or "empty"
            return structured, parse_path, f"hybrid_refiner={reason}"
        merged = merge_cv_refinement(structured, result.structured, evidence_text=masked_text)
        hybrid_path = parse_path if parse_path.endswith("_hybrid") else f"{parse_path}_hybrid"
        return merged, hybrid_path, None

    # Append a hybrid note onto an existing error string without dropping the first cause.
    @staticmethod
    def _note_error(error_message: str | None, note: str | None) -> str | None:
        if not note:
            return error_message
        if error_message:
            return f"{error_message}; {note}"
        return note

    # Parses one CV PDF into structured JSON, using cache when possible.
    async def parse_cv(self, file_path: str, jd_text: str | None = None) -> dict[str, Any]:
        # 1) Check cache first for deterministic replay.
        file_hash = await self.cache.md5_for_file(file_path)
        cache_key = f"{file_hash}-{PARSER_CACHE_VERSION}"
        cached = await self.cache.get(cache_key)
        if cached:
            logger.info("Parser cache hit hash=%s", file_hash)
            return {
                "file_hash": file_hash,
                "cache_hit": True,
                **cached,
            }

        local_document = await self._extract_local_document(file_path)
        raw_text = local_document.raw_text
        if len(raw_text.strip()) < settings.cv_ocr_min_page_chars:
            logger.warning("CV text is too short to send; keeping local rules.")
            structured = self._merge_contact_hints(self._normalize_schema({}), {})
            structured = self._apply_content_fallback(raw_text, structured)
            # Do not cache an empty read. A later screen can try local recognition again.
            cache_payload = {
                "structured_data": structured,
                "raw_llm_response": None,
                "extraction_model": "local-rules",
                "extraction_seed": 42,
                "status": "fallback",
                "parse_path": "local_unreadable",
                "error_message": "scan_unreadable=no_text",
            }
            return {
                "file_hash": file_hash,
                "cache_hit": False,
                **cache_payload,
            }
        heuristic_hints = self._extract_contact_hints(raw_text)
        local_pii = LocalNERResult(names=(), sensitive_values=())
        if local_document.ocr_page_indexes or not heuristic_hints.get("name"):
            local_pii = await asyncio.to_thread(self._detect_local_pii, raw_text)
        local_names = list(local_pii.names)
        sensitive_values = list(local_pii.sensitive_values)
        contact_hints = self._extract_contact_hints(raw_text, local_names, sensitive_values)
        masked_text = mask_pii_text(raw_text, local_names, sensitive_values)
        if not contact_hints.get("name"):
            logger.warning("Local name detection failed; blocking all external parser calls.")
            structured = self._merge_contact_hints(self._normalize_schema({}), contact_hints)
            structured = self._apply_content_fallback(raw_text, structured)
            cache_payload = {
                "structured_data": structured,
                "raw_llm_response": None,
                "extraction_model": "local-rules",
                "extraction_seed": 42,
                "status": "fallback",
                "parse_path": "privacy_rule_fallback",
                "error_message": "privacy_error=local_name_not_detected",
            }
            # Privacy-gated fallback output is never cached: a later run with a
            # repaired environment must get a real extraction, not this fallback.
            return {
                "file_hash": file_hash,
                "cache_hit": False,
                **cache_payload,
            }
        if settings.llm_text_fallback_enabled:
            try:
                user_prompt = self._build_prompt(raw_text=masked_text, jd_text=jd_text)
                llm_result = await self.llm_client.chat_completion(
                    PARSER_SYSTEM_PROMPT,
                    user_prompt,
                    response_format={"type": "json_object"},
                    temperature=0,
                    seed=42,
                    timeout=cv_llm_timeout(),
                )
                safe_llm_payload = strip_contact_fields(llm_result["parsed"])
                structured = self._merge_contact_hints(
                    self._normalize_schema(safe_llm_payload),
                    contact_hints,
                )
                structured = self._apply_content_fallback(raw_text, structured)
                parse_path = "text"
                structured, parse_path, hybrid_note = await self._apply_hybrid_refiner(
                    structured, masked_text, jd_text, parse_path
                )
                cache_payload = {
                    "structured_data": structured,
                    "raw_llm_response": safe_llm_payload,
                    "extraction_model": llm_result["model"],
                    "extraction_seed": 42,
                    "status": "success",
                    "parse_path": parse_path,
                    "error_message": self._note_error(None, hybrid_note),
                }
            except Exception as text_exc:
                logger.exception("Text parse failed; using rule-based contact fallback.")
                # An uncap'd JD can be refused for length. Name what was sent so the recorded
                # error says why instead of reading like a generic API failure; the model's own
                # limit, if its message states one, rides through inside text_exc.
                length_note = ""
                if _looks_like_length_rejection(text_exc):
                    length_note = (
                        "; prompt_rejected_for_length=true"
                        f" cv_chars={len(masked_text)} jd_chars={len(jd_text or '')}"
                    )
                structured = self._merge_contact_hints(self._normalize_schema({}), contact_hints)
                structured = self._apply_content_fallback(raw_text, structured)
                parse_path = "rule_fallback"
                structured, parse_path, hybrid_note = await self._apply_hybrid_refiner(
                    structured, masked_text, jd_text, parse_path
                )
                cache_payload = {
                    "structured_data": structured,
                    "raw_llm_response": None,
                    "extraction_model": settings.llm_model,
                    "extraction_seed": 42,
                    "status": "fallback" if parse_path == "rule_fallback" else "success",
                    "parse_path": parse_path,
                    "error_message": self._note_error(
                        f"text_error={text_exc}{length_note}",
                        hybrid_note,
                    ),
                }
        else:
            logger.info("External text model disabled; using rule-based fallback.")
            structured = self._merge_contact_hints(self._normalize_schema({}), contact_hints)
            structured = self._apply_content_fallback(raw_text, structured)
            parse_path = "rule_fallback"
            structured, parse_path, hybrid_note = await self._apply_hybrid_refiner(
                structured, masked_text, jd_text, parse_path
            )
            cache_payload = {
                "structured_data": structured,
                "raw_llm_response": None,
                "extraction_model": "local-rules",
                "extraction_seed": 42,
                "status": "fallback" if parse_path == "rule_fallback" else "success",
                "parse_path": parse_path,
                "error_message": self._note_error("text_model_disabled=true", hybrid_note),
            }
        # Only fully successful parses are cached. Degraded/truncated results stay
        # out of the cache, so a later run with a working LLM extracts fresh instead
        # of quietly reusing yesterday's fallback.
        if cache_payload["status"] == "success":
            await self.cache.set(cache_key, cache_payload)
        return {
            "file_hash": file_hash,
            "cache_hit": False,
            **cache_payload,
        }

    def _build_prompt(self, *, raw_text: str, jd_text: str | None) -> str:
        return self.build_compressed_prompt(raw_text=raw_text, jd_text=jd_text)

    async def _extract_pdf_text(self, file_path: str) -> str:
        return (await self._extract_local_document(file_path)).raw_text

    # Builds one local text/OCR document while blocking unsupported files.
    async def _extract_local_document(self, file_path: str) -> LocalCVDocument:
        path = Path(file_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError("Only PDF files are currently supported.")
        try:
            return await asyncio.to_thread(self._extract_local_cv_document, path)
        except Exception as exc:
            logger.exception("Failed to extract PDF text or local OCR file=%s", file_path)
            raise ValueError("Failed to extract PDF text with local OCR.") from exc


# Builds a CV parser with the shared LLM client and on-disk hash cache.
def build_cv_parser_service() -> CVParserService:
    from cv_parser.providers.zai import zai_cv_refiner_or_none

    return CVParserService(
        llm_client=LLMClient(),
        cache=HashCache(settings.cache_dir),
        enrichment_provider=zai_cv_refiner_or_none(),
    )


# Backward-compatible alias for existing imports.
def build_parser_service() -> CVParserService:
    return build_cv_parser_service()
