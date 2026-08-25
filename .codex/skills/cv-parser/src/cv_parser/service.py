# Orchestrates privacy-safe local PII extraction and external CV content parsing.
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from screening_core.config import settings
from screening_core.hash_cache import HashCache
from screening_core.llm_client import LLMClient
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
from cv_parser.ocr import LocalCVDocument, OCRLine, extract_local_cv_document
from cv_parser.pdf_utils import (
    extract_with_pdfplumber,
    extract_with_pymupdf,
    extract_with_pypdf,
    render_redacted_pdf_pages_as_data_urls,
    render_pdf_pages_as_data_urls,
)
from cv_parser.pii import (
    contact_values_for_redaction,
    mask_pii_text,
    strip_contact_fields,
)
from cv_parser.prompts import (
    PARSER_SYSTEM_PROMPT,
    PARSER_VISION_FOCUS_PROMPT,
    PARSER_VISION_USER_PROMPT,
)

logger = logging.getLogger(__name__)
PARSER_CACHE_VERSION = "pii-redaction-v4-p1-fields"


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

    # Stores the LLM client and hash cache used by parse_cv.
    def __init__(self, llm_client: LLMClient, cache: HashCache) -> None:
        self.llm_client = llm_client
        self.cache = cache

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
        heuristic_hints = self._extract_contact_hints(raw_text)
        local_pii = LocalNERResult(names=(), sensitive_values=())
        if local_document.ocr_page_indexes or not heuristic_hints.get("name"):
            local_pii = await asyncio.to_thread(self._detect_local_pii, raw_text)
        local_names = list(local_pii.names)
        sensitive_values = list(local_pii.sensitive_values)
        contact_hints = self._extract_contact_hints(raw_text, local_names, sensitive_values)
        masked_text = mask_pii_text(raw_text, local_names, sensitive_values)
        pii_values = contact_values_for_redaction(raw_text, local_names, sensitive_values)
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
            await self.cache.set(cache_key, cache_payload)
            return {
                "file_hash": file_hash,
                "cache_hit": False,
                **cache_payload,
            }
        try:
            llm_result = await self._parse_with_pdf_images(
                file_path=file_path,
                jd_text=jd_text,
                pii_values=pii_values,
                ocr_lines=local_document.ocr_lines,
            )
            safe_llm_payload = strip_contact_fields(llm_result["parsed"])
            structured = self._merge_contact_hints(self._normalize_schema(safe_llm_payload), contact_hints)
            structured = self._apply_content_fallback(raw_text, structured)
            cache_payload = {
                "structured_data": structured,
                "raw_llm_response": safe_llm_payload,
                "extraction_model": llm_result["model"],
                "extraction_seed": 42,
                "status": "success",
                "parse_path": llm_result.get("parse_path", "vision"),
                "error_message": None,
            }
        except Exception as image_exc:
            logger.exception("Vision parse failed; considering text fallback.")
            if not settings.llm_text_fallback_enabled:
                logger.exception("Text fallback disabled; using rule-based fallback.")
                structured = self._merge_contact_hints(self._normalize_schema({}), contact_hints)
                structured = self._apply_content_fallback(raw_text, structured)
                cache_payload = {
                    "structured_data": structured,
                    "raw_llm_response": None,
                    "extraction_model": settings.llm_vision_model,
                    "extraction_seed": 42,
                    "status": "fallback",
                    "parse_path": "rule_fallback",
                    "error_message": f"vision_error={image_exc}; text_fallback_disabled=true",
                }
            else:
                try:
                    user_prompt = self._build_prompt(raw_text=masked_text, jd_text=jd_text)
                    llm_result = await self.llm_client.chat_completion(
                        PARSER_SYSTEM_PROMPT,
                        user_prompt,
                        response_format={"type": "json_object"},
                        temperature=0,
                        seed=42,
                    )
                    safe_llm_payload = strip_contact_fields(llm_result["parsed"])
                    structured = self._merge_contact_hints(
                        self._normalize_schema(safe_llm_payload),
                        contact_hints,
                    )
                    structured = self._apply_content_fallback(raw_text, structured)
                    cache_payload = {
                        "structured_data": structured,
                        "raw_llm_response": safe_llm_payload,
                        "extraction_model": llm_result["model"],
                        "extraction_seed": 42,
                        "status": "success",
                        "parse_path": "text_fallback",
                        "error_message": None,
                    }
                except Exception as text_exc:
                    logger.exception("Text parse also failed; using rule-based contact fallback.")
                    structured = self._merge_contact_hints(self._normalize_schema({}), contact_hints)
                    structured = self._apply_content_fallback(raw_text, structured)
                    cache_payload = {
                        "structured_data": structured,
                        "raw_llm_response": None,
                        "extraction_model": settings.llm_vision_model,
                        "extraction_seed": 42,
                        "status": "fallback",
                        "parse_path": "rule_fallback",
                        "error_message": f"vision_error={image_exc}; text_error={text_exc}",
                    }
        await self.cache.set(cache_key, cache_payload)
        return {
            "file_hash": file_hash,
            "cache_hit": False,
            **cache_payload,
        }

    async def _parse_with_pdf_images(
        self,
        *,
        file_path: str,
        jd_text: str | None,
        pii_values: list[str],
        ocr_lines: tuple[OCRLine, ...],
    ) -> dict[str, Any]:
        image_urls = await asyncio.to_thread(
            self._render_redacted_pdf_pages_as_data_urls,
            file_path,
            settings.llm_vision_max_pages,
            pii_values,
            ocr_lines,
        )
        last_exc: Exception | None = None
        attempts = max(1, settings.llm_vision_retry_attempts)
        for attempt in range(1, attempts + 1):
            try:
                primary_result = await self._run_vision_prompt(
                    image_urls=image_urls,
                    jd_text=jd_text,
                    user_prompt=PARSER_VISION_USER_PROMPT,
                )
                merged_payload = primary_result["parsed"]
                pass_count = 1

                if settings.llm_vision_focus_pass_enabled:
                    primary_structured = self._normalize_schema(merged_payload)
                    if self._needs_focus_pass(primary_structured):
                        focus_result = await self._run_vision_prompt(
                            image_urls=image_urls,
                            jd_text=jd_text,
                            user_prompt=PARSER_VISION_FOCUS_PROMPT,
                        )
                        merged_payload = self._merge_prefer_non_empty(
                            base=merged_payload,
                            preferred=focus_result["parsed"],
                            keys=("education", "experience"),
                        )
                        pass_count = 2
                return {
                    **primary_result,
                    "parsed": merged_payload,
                    "parse_path": "vision_focus" if pass_count == 2 else "vision",
                }
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Vision parse attempt failed attempt=%s/%s error=%s",
                    attempt,
                    attempts,
                    exc,
                )

        assert last_exc is not None
        raise last_exc

    async def _run_vision_prompt(
        self,
        *,
        image_urls: list[str],
        jd_text: str | None,
        user_prompt: str,
    ) -> dict[str, Any]:
        user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        if jd_text:
            user_content.append({"type": "text", "text": f"JD Context:\n{jd_text}"})
        user_content.extend(
            {"type": "image_url", "image_url": {"url": image_url}}
            for image_url in image_urls
        )
        return await self.llm_client.chat_completion_messages(
            [
                {"role": "system", "content": PARSER_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            model=settings.llm_vision_model,
            response_format={"type": "json_object"},
            temperature=0,
            seed=42,
        )

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

    @staticmethod
    def _needs_focus_pass(structured: dict[str, Any]) -> bool:
        education = structured.get("education") or []
        experience = structured.get("experience") or []
        return len(education) == 0 or len(experience) == 0

    @staticmethod
    def _merge_prefer_non_empty(
        *,
        base: dict[str, Any],
        preferred: dict[str, Any],
        keys: tuple[str, ...],
    ) -> dict[str, Any]:
        merged = dict(base) if isinstance(base, dict) else {}
        if not isinstance(preferred, dict):
            return merged
        for key in keys:
            value = preferred.get(key)
            if value not in (None, "", []):
                merged[key] = value
        return merged


# Builds a CV parser with the shared LLM client and on-disk hash cache.
def build_cv_parser_service() -> CVParserService:
    return CVParserService(
        llm_client=LLMClient(),
        cache=HashCache(settings.cache_dir),
    )


# Backward-compatible alias for existing imports.
def build_parser_service() -> CVParserService:
    return build_cv_parser_service()
