from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pdfplumber
from pypdf import PdfReader

from app.config import settings
from app.core.hash_cache import HashCache
from app.core.llm_client import LLMClient

logger = logging.getLogger(__name__)

PARSER_SYSTEM_PROMPT = """You are a CV parser. Extract the following fields from the candidate's CV and output valid JSON.

Fields:
- name: string
- email: string
- phone: string (optional)
- education: array of {school, degree, major, year}
- experience: array of {company, title, start_date, end_date, description}
- skills: array of string (tech skills only)
- publications: array of {title, journal, year} (optional)

Rules:
- Only extract information explicitly stated in the CV. Do not infer.
- For skills, extract exact terms used (do not standardize).
- If a field is not found, use null or empty array.

Output valid JSON only. No explanations."""


class CVParserService:
    def __init__(self, llm_client: LLMClient, cache: HashCache) -> None:
        self.llm_client = llm_client
        self.cache = cache

    async def parse_cv(self, file_path: str, jd_text: str | None = None) -> dict[str, Any]:
        file_hash = await self.cache.md5_for_file(file_path)
        cached = await self.cache.get(file_hash)
        if cached:
            logger.info("Parser cache hit hash=%s", file_hash)
            return {
                "file_hash": file_hash,
                "cache_hit": True,
                **cached,
            }

        raw_text = await self._extract_pdf_text(file_path)
        user_prompt = self._build_prompt(raw_text=raw_text, jd_text=jd_text)
        llm_result = await self.llm_client.chat_completion(
            PARSER_SYSTEM_PROMPT,
            user_prompt,
            response_format={"type": "json_object"},
            temperature=0,
            seed=42,
        )
        structured = self._normalize_schema(llm_result["parsed"])
        cache_payload = {
            "structured_data": structured,
            "raw_llm_response": llm_result["parsed"],
            "extraction_model": llm_result["model"],
            "extraction_seed": 42,
            "status": "success",
        }
        await self.cache.set(file_hash, cache_payload)
        return {
            "file_hash": file_hash,
            "cache_hit": False,
            **cache_payload,
        }

    def _build_prompt(self, *, raw_text: str, jd_text: str | None) -> str:
        jd_segment = f"\nJD Context:\n{jd_text}\n" if jd_text else ""
        return f"CV Text:\n{raw_text}\n{jd_segment}\nOutput valid JSON only."

    async def _extract_pdf_text(self, file_path: str) -> str:
        path = Path(file_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError("Only PDF files are currently supported.")
        try:
            text = await asyncio.to_thread(self._extract_with_pdfplumber, path)
            if text.strip():
                return text
            return await asyncio.to_thread(self._extract_with_pypdf, path)
        except Exception as exc:
            logger.exception("Failed to extract PDF text file=%s", file_path)
            raise ValueError("Failed to extract PDF text.") from exc

    @staticmethod
    def _extract_with_pdfplumber(path: Path) -> str:
        chunks: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                chunks.append(page.extract_text() or "")
        return "\n".join(chunks).strip()

    @staticmethod
    def _extract_with_pypdf(path: Path) -> str:
        reader = PdfReader(str(path))
        chunks: list[str] = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks).strip()

    @staticmethod
    def _normalize_schema(payload: dict[str, Any]) -> dict[str, Any]:
        def force_list(value: Any) -> list[Any]:
            return value if isinstance(value, list) else []

        return {
            "name": payload.get("name"),
            "email": payload.get("email"),
            "phone": payload.get("phone"),
            "education": force_list(payload.get("education")),
            "experience": force_list(payload.get("experience")),
            "skills": [str(skill) for skill in force_list(payload.get("skills")) if str(skill).strip()],
            "publications": force_list(payload.get("publications")),
        }


def build_parser_service() -> CVParserService:
    return CVParserService(
        llm_client=LLMClient(),
        cache=HashCache(settings.cache_dir),
    )
