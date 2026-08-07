# to extract the information from the CV and return the structured data
# 1. multimodal parsing
# 2. text parsing
# 3. contact fallback
# 4. content fallback
# 5. cache
# 6. return the structured data


from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
from pypdf import PdfReader

from app.config import settings
from app.core.hash_cache import HashCache
from app.core.llm_client import LLMClient

logger = logging.getLogger(__name__)

KNOWN_SKILLS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "sql",
    "mysql",
    "postgresql",
    "mongodb",
    "redis",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "fastapi",
    "flask",
    "django",
    "pytorch",
    "tensorflow",
    "scikit-learn",
    "react",
    "vue",
    "node.js",
    "nodejs",
    "golang",
    "go",
    "c++",
    "c#",
    "rust",
    "linux",
}

PARSER_SYSTEM_PROMPT = """You are a CV parser. Extract the following fields from the candidate's CV and output valid JSON.

Output schema:
{
  "name": string,
  "email": string,
  "phone": string,
  "skills": [string],          # Extract from tech skills section or mentioned technologies
  "education": [
    {
      "school": string,        # Full institution name only
      "degree": string,        # e.g., "MEng", "BSc", "PhD"
      "major": string,         # Field of study
      "period": string         # Date range as shown (e.g., "09/2018 - 06/2022")
    }
  ],
  "experience": [
    {
      "company": string,
      "job_title": string,
      "period": string,
      "description": string    # Full combined description, not split by lines
    }
  ],
  "publications": [...]
}


Rules:
- Only extract information explicitly stated in the CV. Do not infer.
- For skills, extract exact terms used (do not standardize).
- Each education entry = ONE degree. Merge all info about that degree into ONE object.
- Each experience entry = ONE job. Merge ALL bullet points and descriptions into ONE description string.
- Do NOT split descriptions across multiple objects.
- If you cannot determine a field, use null (not empty string).
- Output valid JSON only.No explanations.
"""

PARSER_VISION_USER_PROMPT = """Parse this CV into the target JSON schema.

Important:
- Read text directly from the provided page images.
- If one field is missing, set it to null or empty array.
- Return JSON only, no markdown fences."""

PARSER_VISION_FOCUS_PROMPT = """Re-read the same CV images and focus on timeline accuracy.

Skills extraction hints - look for these technologies (exact match or similar):
{known_skills}

Important:
- Group experience by job: all bullets under one company belong in ONE experience object.
- Group education by degree: each degree is ONE education object.
- For each experience, combine the full description into a single string.
- Return JSON only, no markdown fences.
""".format(known_skills=", ".join(sorted(KNOWN_SKILLS)[:50]))


class CVParserService:
    def __init__(self, llm_client: LLMClient, cache: HashCache) -> None:
        self.llm_client = llm_client
        self.cache = cache

# 1. check the cache first
# 2. extract the raw text from the PDF
# 3. extract the contact information hints(email, phone, name)
# 4. main path (Vision): render the first N pages as image URLs, and parse with multimodal LLM
# 5. normalize the schema
# 6. merge the contact information hints
# 7. content fallback: fill the empty arrays from the raw text when the LLM left them blank
# 8. exception downgrade
# 9. write the cache and return the result (include status/model/raw_llm_response/cache_hit)
 
    async def parse_cv(self, file_path: str, jd_text: str | None = None) -> dict[str, Any]:
        # check the cache first
        file_hash = await self.cache.md5_for_file(file_path)
        cached = await self.cache.get(file_hash)
        if cached:
            # MD5 hash
            logger.info("Parser cache hit hash=%s", file_hash)
            return {
                "file_hash": file_hash,
                "cache_hit": True,
                **cached,
            }

        raw_text = await self._extract_pdf_text(file_path)
        contact_hints = self._extract_contact_hints(raw_text)
        try:
            # Attempt multimodal extraction first for layout-heavy CVs.
            llm_result = await self._parse_with_pdf_images(file_path=file_path, jd_text=jd_text)
            # Primary path: vision parse, then normalize to stable schema.
            structured = self._merge_contact_hints(self._normalize_schema(llm_result["parsed"]), contact_hints)
            structured = self._apply_content_fallback(raw_text, structured)
            cache_payload = {
                "structured_data": structured,
                "raw_llm_response": llm_result["parsed"],
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
                    # Fallback to text-only parsing when image path is unavailable/unstable.
                    user_prompt = self._build_prompt(raw_text=raw_text, jd_text=jd_text)
                    llm_result = await self.llm_client.chat_completion(
                        PARSER_SYSTEM_PROMPT,
                        user_prompt,
                        response_format={"type": "json_object"},
                        temperature=0,
                        seed=42,
                    )
                    # Secondary path: text parse fallback when vision fails.
                    structured = self._merge_contact_hints(self._normalize_schema(llm_result["parsed"]), contact_hints)
                    structured = self._apply_content_fallback(raw_text, structured)
                    cache_payload = {
                        "structured_data": structured,
                        "raw_llm_response": llm_result["parsed"],
                        "extraction_model": llm_result["model"],
                        "extraction_seed": 42,
                        "status": "success",
                        "parse_path": "text_fallback",
                        "error_message": None,
                    }
                except Exception as text_exc:
                    logger.exception("Text parse also failed; using rule-based contact fallback.")
                    structured = self._merge_contact_hints(self._normalize_schema({}), contact_hints)
                    # Last resort: recover minimum structured content from raw text.
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
        await self.cache.set(file_hash, cache_payload)
        return {
            "file_hash": file_hash,
            "cache_hit": False,
            **cache_payload,
        }

    async def _parse_with_pdf_images(self, *, file_path: str, jd_text: str | None) -> dict[str, Any]:
        image_urls = await asyncio.to_thread(
            self._render_pdf_pages_as_data_urls,
            file_path,
            settings.llm_vision_max_pages,
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

    def build_compressed_prompt(self, *, raw_text: str, jd_text: str | None, max_chars: int = 12000) -> str:
        compressed_cv_text = self._compress_cv_text(raw_text=raw_text, max_chars=max_chars)
        segments = [
            "Task: Parse the CV text below into the target JSON schema from system prompt.",
            "Rules: Use explicit facts only. Merge one job into one experience object. Merge one degree into one education object.",
            f"CV Text (compressed):\n{compressed_cv_text}",
        ]
        if jd_text:
            compressed_jd_text = self._compress_cv_text(raw_text=jd_text, max_chars=3000)
            segments.append(f"JD Context (compressed):\n{compressed_jd_text}")
        segments.append("Return valid JSON only.")
        return "\n\n".join(segments)

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
    def _render_pdf_pages_as_data_urls(file_path: str, max_pages: int) -> list[str]:
        # Render PDF pages to high-fidelity images for multimodal parsing.
        document = pdfium.PdfDocument(file_path)
        total_pages = len(document)
        if total_pages == 0:
            raise ValueError("PDF has no pages.")

        page_count = min(max_pages, total_pages)
        image_urls: list[str] = []
        image_format = settings.llm_vision_image_format.strip().upper()
        if image_format not in {"PNG", "JPEG"}:
            image_format = "PNG"
        for page_index in range(page_count):
            page = document[page_index]
            pil_image = page.render(scale=settings.llm_vision_render_scale).to_pil()
            buffer = io.BytesIO()
            if image_format == "JPEG":
                pil_image.save(buffer, format="JPEG", quality=settings.llm_vision_jpeg_quality)
                mime_type = "jpeg"
            else:
                pil_image.save(buffer, format="PNG")
                mime_type = "png"
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            image_urls.append(f"data:image/{mime_type};base64,{encoded}")
            page.close()
            pil_image.close()
        return image_urls

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

    @staticmethod
    def _normalize_schema(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}

        def pick_first(*keys: str) -> Any:
            # Models can rename keys across runs; we accept the first non-empty alias.
            for key in keys:
                if key in payload and payload.get(key) not in (None, ""):
                    return payload.get(key)
            return None

        return {
            "name": payload.get("name"),
            "email": payload.get("email"),
            "phone": payload.get("phone"),
            "education": CVParserService._normalize_education_items(
                pick_first("education", "educations", "academic_background", "academics")
            ),
            "experience": CVParserService._normalize_experience_items(
                pick_first("experience", "experiences", "work_experience", "employment_history")
            ),
            "skills": CVParserService._normalize_skill_items(
                pick_first("skills", "technical_skills", "tech_skills", "skill_set")
            ),
            "publications": CVParserService._normalize_publication_items(
                pick_first("publications", "publication", "papers", "research_publications")
            ),
        }

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        # Normalize arbitrary LLM outputs into list form.
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        if isinstance(value, str):
            items = [item.strip(" -\t") for item in re.split(r"[,\n;|/]+", value) if item.strip()]
            return items
        return [value]

    @staticmethod
    def _normalize_skill_items(value: Any) -> list[str]:
        normalized: list[str] = []
        for item in CVParserService._as_list(value):
            if isinstance(item, dict):
                # Accept common key variants from different model outputs.
                raw = item.get("name") or item.get("skill") or item.get("technology") or item.get("value")
            else:
                raw = item
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            normalized.append(text)
        return CVParserService._unique_keep_order(normalized)

    @staticmethod
    def _normalize_education_items(value: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in CVParserService._as_list(value):
            if isinstance(item, dict):
                school = item.get("school") or item.get("institution") or item.get("university") or item.get("college")
                degree = (
                    item.get("degree")
                    or item.get("qualification")
                    or item.get("education_level")
                )
                major = item.get("major") or item.get("field") or item.get("field_of_study")
                period = item.get("period") or item.get("year") or item.get("graduation_year")
                if not degree:
                    # Only infer from local context when the explicit degree field is missing.
                    context = " ".join(
                        str(part).strip()
                        for part in (school, major, item.get("description"), item.get("summary"))
                        if part not in (None, "")
                    )
                    degree = CVParserService._extract_degree_from_text(context)
                if not period:
                    context = " ".join(
                        str(part).strip()
                        for part in (school, major, item.get("description"), item.get("summary"))
                        if part not in (None, "")
                    )
                    period = CVParserService._extract_year_from_text(context)
                school = CVParserService._normalize_education_school(str(school).strip() if school else None, degree, major)
                rows.append(
                    {
                        "school": school,
                        "degree": degree,
                        "major": major,
                        "period": period,
                    }
                )
            else:
                text = str(item).strip()
                if text:
                    # String items usually come from compressed list outputs; split semantics here.
                    if CVParserService._looks_like_date_location_line(text):
                        # Skip timeline-only rows like "01/2008 - 01/2012 London".
                        continue
                    degree = CVParserService._extract_degree_from_text(text)
                    major = CVParserService._extract_major_from_text(text)
                    school = CVParserService._normalize_education_school(text, degree, major)
                    rows.append(
                        {
                            "school": school,
                            "degree": degree,
                            "major": major,
                            "period": CVParserService._extract_year_from_text(text),
                        }
                    )
        rows = [
            row
            for row in rows
            if any(value not in (None, "") for value in row.values()) and CVParserService._is_valid_education_row(row)
        ]
        return CVParserService._merge_fragmented_education_rows(rows)

    @staticmethod
    def _normalize_experience_items(value: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in CVParserService._as_list(value):
            if isinstance(item, dict):
                company = item.get("company") or item.get("employer") or item.get("organization")
                job_title = item.get("job_title") or item.get("title") or item.get("role") or item.get("position")
                start_date = item.get("start_date") or item.get("start") or item.get("from")
                end_date = item.get("end_date") or item.get("end") or item.get("to") or item.get("until")
                period = item.get("period")
                description = item.get("description") or item.get("summary") or item.get("responsibilities")
                context = " ".join(
                    str(part).strip()
                    for part in (description, item.get("company"), item.get("role"), item.get("position"), item.get("duration"))
                    if part not in (None, "")
                )
                if not company:
                    company = CVParserService._extract_company_from_text(context)
                if not job_title:
                    job_title = CVParserService._extract_title_from_text(context)
                if not period and not start_date and not end_date:
                    start_date, end_date = CVParserService._extract_date_range_from_text(context)
                if not period:
                    period = CVParserService._combine_period(start_date, end_date)
                rows.append(
                    {
                        "company": company,
                        "job_title": job_title,
                        "period": period,
                        "description": description,
                    }
                )
            else:
                text = str(item).strip()
                if text:
                    # Keep raw line in description so we do not lose information.
                    start_date, end_date = CVParserService._extract_date_range_from_text(text)
                    rows.append(
                        {
                            "company": CVParserService._extract_company_from_text(text),
                            "job_title": CVParserService._extract_title_from_text(text),
                            "period": CVParserService._combine_period(start_date, end_date),
                            "description": text,
                        }
                    )
        rows = [row for row in rows if any(value not in (None, "") for value in row.values())]
        return CVParserService._merge_fragmented_experience_rows(rows)

    @staticmethod
    def _normalize_publication_items(value: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in CVParserService._as_list(value):
            if isinstance(item, dict):
                rows.append(
                    {
                        "title": item.get("title") or item.get("name"),
                        "journal": item.get("journal") or item.get("venue") or item.get("publisher"),
                        "year": item.get("year") or item.get("published_year"),
                    }
                )
            else:
                text = str(item).strip()
                if text:
                    rows.append({"title": text, "journal": None, "year": None})
        return [row for row in rows if any(value not in (None, "") for value in row.values())]

    @staticmethod
    def _compress_cv_text(*, raw_text: str, max_chars: int) -> str:
        lines = [" ".join(line.split()) for line in raw_text.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            return ""

        selected: list[str] = []
        seen: set[str] = set()
        for line in lines:
            key = line.casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append(line)

        joined = "\n".join(selected)
        if len(joined) <= max_chars:
            return joined

        priority_pattern = re.compile(
            r"(experience|employment|work history|education|university|college|skills|projects|publications|email|phone|@|\b\d{4}\b)",
            re.IGNORECASE,
        )
        priority_lines = [line for line in selected if priority_pattern.search(line)]
        fallback_lines = [line for line in selected if line not in priority_lines]
        ordered = priority_lines + fallback_lines

        result: list[str] = []
        current_len = 0
        for line in ordered:
            candidate_len = len(line) + (1 if result else 0)
            if current_len + candidate_len > max_chars:
                continue
            result.append(line)
            current_len += candidate_len
            if current_len >= max_chars:
                break
        return "\n".join(result)

    @staticmethod
    def _merge_fragmented_experience_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []

        merged: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for raw_item in rows:
            item = {
                "company": CVParserService._to_clean_text(raw_item.get("company")),
                "job_title": CVParserService._to_clean_text(raw_item.get("job_title")),
                "period": CVParserService._to_clean_text(raw_item.get("period")),
                "description": CVParserService._to_clean_text(raw_item.get("description")),
            }
            has_company = bool(item.get("company"))
            has_description = bool(item.get("description"))
            has_period = bool(item.get("period"))
            has_job_title = bool(item.get("job_title"))

            if has_company:
                if current:
                    merged.append(current)
                current = dict(item)
                continue

            if current and has_description:
                current["description"] = CVParserService._concat_text(
                    current.get("description"),
                    item["description"],
                )
                if has_job_title and not current.get("job_title"):
                    current["job_title"] = item["job_title"]
                if has_period and not current.get("period"):
                    current["period"] = item["period"]
                continue

            if current and has_period and not current.get("period"):
                current["period"] = item["period"]
                if has_job_title and not current.get("job_title"):
                    current["job_title"] = item["job_title"]
                continue

            if current:
                current["description"] = CVParserService._concat_text(
                    current.get("description"),
                    item.get("description"),
                )
                if not current.get("job_title") and has_job_title:
                    current["job_title"] = item["job_title"]
                if not current.get("period") and has_period:
                    current["period"] = item["period"]
            else:
                merged.append(item)

        if current:
            merged.append(current)

        return [
            item
            for item in merged
            if item.get("company") or item.get("job_title") or item.get("description")
        ]

    @staticmethod
    def _merge_fragmented_education_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []

        merged_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        pass_through: list[dict[str, Any]] = []

        for raw_item in rows:
            item = {
                "school": CVParserService._to_clean_text(raw_item.get("school")),
                "degree": CVParserService._to_clean_text(raw_item.get("degree")),
                "major": CVParserService._to_clean_text(raw_item.get("major")),
                "period": CVParserService._to_clean_text(raw_item.get("period")),
            }
            key = (
                (item.get("school") or "").casefold(),
                (item.get("degree") or "").casefold(),
            )
            if not key[0] and not key[1]:
                pass_through.append(item)
                continue
            if key in merged_by_key:
                existing = merged_by_key[key]
                for field in ("major", "period", "school", "degree"):
                    if item.get(field) and not existing.get(field):
                        existing[field] = item[field]
            else:
                merged_by_key[key] = dict(item)

        return [*merged_by_key.values(), *pass_through]

    @staticmethod
    def _to_clean_text(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        return " ".join(text.split())

    @staticmethod
    def _concat_text(left: Any, right: Any) -> str | None:
        left_text = CVParserService._to_clean_text(left)
        right_text = CVParserService._to_clean_text(right)
        if left_text and right_text:
            return f"{left_text} {right_text}".strip()
        return left_text or right_text

    @staticmethod
    # to extract the contact information from the raw text
    # email, phone, name
    def _extract_contact_hints(raw_text: str) -> dict[str, str | None]:
        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", raw_text)
        phone_matches = re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", raw_text)
        phone = None
        for candidate in phone_matches:
            digit_count = sum(ch.isdigit() for ch in candidate)
            if digit_count >= 8:
                phone = candidate.strip()
                break

        name = None
        for raw_line in raw_text.splitlines():
            line = " ".join(raw_line.split()).strip()
            if not line:
                continue
            lower_line = line.lower()
            if "email" in lower_line or "phone" in lower_line or "resume" in lower_line or "curriculum vitae" in lower_line:
                continue
            if "@" in line or ":" in line:
                continue
            if len(line) > 64:
                continue
            token_count = len(line.split())
            if token_count > 8:
                continue
            name = line
            break

        return {
            "name": name,
            "email": email_match.group(0) if email_match else None,
            "phone": phone,
        }

    @staticmethod
    def _merge_contact_hints(structured: dict[str, Any], hints: dict[str, str | None]) -> dict[str, Any]:
        merged = dict(structured)
        if not merged.get("email") and hints.get("email"):
            merged["email"] = hints["email"]
        if hints.get("phone"):
            if not merged.get("phone"):
                merged["phone"] = hints["phone"]
            else:
                # Keep original punctuation format when both values describe same number.
                merged["phone"] = CVParserService._prefer_phone_format(str(merged["phone"]), hints["phone"])
        if not merged.get("name") and hints.get("name"):
            merged["name"] = hints["name"]
        return merged

    @staticmethod
    def _unique_keep_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    def _apply_content_fallback(self, raw_text: str, structured: dict[str, Any]) -> dict[str, Any]:
        # Fill empty arrays from deterministic text heuristics only when LLM left them blank.
        enriched = dict(structured)
        if not enriched.get("skills"):
            enriched["skills"] = self._extract_skills_fallback(raw_text)
        if not enriched.get("education"):
            enriched["education"] = self._extract_education_fallback(raw_text)
        if not enriched.get("experience"):
            enriched["experience"] = self._extract_experience_fallback(raw_text)
        if not enriched.get("publications"):
            enriched["publications"] = self._extract_publications_fallback(raw_text)
        return enriched

    def _extract_skills_fallback(self, raw_text: str) -> list[str]:
        # Strategy: union of known-token scan + explicit Skills section parsing.
        matches = [token for token in re.findall(r"[A-Za-z0-9.+#-]{2,}", raw_text) if token.casefold() in KNOWN_SKILLS]
        section_lines = self._extract_section_lines(
            raw_text,
            ("skills", "technical skills", "tech stack"),
            ("education", "experience", "projects", "publications", "languages", "certifications"),
        )
        section_tokens: list[str] = []
        for line in section_lines:
            section_tokens.extend(
                piece.strip()
                for piece in re.split(r"[,\u3001;/|]+", line)
                if piece.strip()
            )
        return self._unique_keep_order(matches + section_tokens)

    def _extract_education_fallback(self, raw_text: str) -> list[dict[str, Any]]:
        # Keep education lines intact and extract degree/period conservatively.
        lines = self._extract_section_lines(
            raw_text,
            ("education", "academic background", "academics"),
            ("experience", "skills", "projects", "publications", "certifications"),
        )
        output: list[dict[str, Any]] = []
        for line in lines:
            output.append(
                {
                    "school": line,
                    "degree": self._extract_degree_from_text(line),
                    "major": self._extract_major_from_text(line),
                    "period": self._extract_year_from_text(line),
                }
            )
        return output

    def _extract_experience_fallback(self, raw_text: str) -> list[dict[str, Any]]:
        # Preserve chronology text even if company/job_title cannot be reliably split.
        lines = self._extract_section_lines(
            raw_text,
            ("experience", "work experience", "employment history"),
            ("education", "skills", "projects", "publications", "certifications"),
        )
        output: list[dict[str, Any]] = []
        for line in lines:
            output.append(
                {
                    "company": None,
                    "job_title": None,
                    "period": None,
                    "description": line,
                }
            )
        return output

    def _extract_publications_fallback(self, raw_text: str) -> list[dict[str, Any]]:
        # Publication details vary widely; keep title text first, then optional year.
        lines = self._extract_section_lines(
            raw_text,
            ("publications", "publication", "research", "papers"),
            ("education", "experience", "skills", "projects", "certifications"),
        )
        output: list[dict[str, Any]] = []
        for line in lines:
            year_match = re.search(r"(19|20)\d{2}", line)
            output.append(
                {
                    "title": line,
                    "journal": None,
                    "year": year_match.group(0) if year_match else None,
                }
            )
        return output

    @staticmethod
    def _extract_section_lines(raw_text: str, headers: tuple[str, ...], stop_headers: tuple[str, ...]) -> list[str]:
        # Lightweight section slicer: collect lines after target header until next section.
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            return []

        header_pattern = re.compile(r"^[A-Za-z][A-Za-z\s]{1,40}:?$")
        active = False
        result: list[str] = []
        for line in lines:
            line_lower = line.casefold().rstrip(":")
            if any(line_lower == header.casefold() for header in headers):
                active = True
                continue

            if active:
                # Stop when next all-caps/simple title-like section begins.
                if any(line_lower == header.casefold() for header in stop_headers):
                    break
                if header_pattern.match(line) and len(result) >= 2:
                    break
                result.append(line)
                if len(result) >= 10:
                    break

        return result

    @staticmethod
    def _extract_degree_from_text(text: str | None) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        # Ordered from most specific to broad to avoid early generic matches.
        patterns: list[tuple[str, str]] = [
            (r"\b(ph\.?\s?d|doctor\s+of\s+philosophy|doctoral?)\b", "PhD"),
            (r"\b(m\.?\s?phil|master\s+of\s+philosophy)\b", "MPhil"),
            (r"\b(mba)\b", "MBA"),
            (r"\b(m\.?\s?sc|m\.?\s?a|m\.?\s?eng|master(?:'s)?(?:\s+degree)?)\b", "Master"),
            (r"\b(b\.?\s?sc|b\.?\s?a|b\.?\s?eng|bachelor(?:'s)?(?:\s+degree)?)\b", "Bachelor"),
            (r"\b(associate(?:'s)?(?:\s+degree)?)\b", "Associate"),
        ]
        for pattern, label in patterns:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return label
        return None

    @staticmethod
    def _extract_major_from_text(text: str | None) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        # Heuristic: capture phrase after "in/of", e.g. "Master in Computer Science".
        match = re.search(r"\b(?:in|of)\s+([A-Za-z][A-Za-z\s&/-]{2,60})", normalized, flags=re.IGNORECASE)
        if not match:
            return None
        candidate = match.group(1).strip(" .,-;:")
        if len(candidate) < 3:
            return None
        return candidate

    @staticmethod
    def _normalize_education_school(text: str | None, degree: str | None, major: str | None) -> str | None:
        if not text:
            return major
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        institution = CVParserService._extract_institution_from_text(normalized)
        if institution:
            return institution
        # If the row is degree-centric, keep the major as the primary school-like value.
        if degree and major:
            return major
        if major and not CVParserService._looks_like_date_location_line(normalized):
            return major
        return normalized

    @staticmethod
    def _extract_institution_from_text(text: str | None) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        pattern = (
            r"\b([A-Z][A-Za-z&'., -]{2,}"
            r"(?:University|College|Institute|School|Polytechnic|Academy)"
            r"(?:[A-Za-z&'., -]{0,40})?)\b"
        )
        match = re.search(pattern, normalized)
        if match:
            return match.group(1).strip(" .,-;:")
        return None

    @staticmethod
    def _looks_like_date_location_line(text: str | None) -> bool:
        if not text:
            return False
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        date_range = re.search(
            r"^\d{1,2}[/-](?:19|20)\d{2}\s*(?:-|–|—|to)\s*\d{1,2}[/-](?:19|20)\d{2}(?:\s+[A-Za-z][A-Za-z .'-]{1,40})?$",
            normalized,
            flags=re.IGNORECASE,
        )
        if date_range:
            return True
        year_range = re.search(
            r"^(?:19|20)\d{2}\s*(?:-|–|—|to)\s*(?:19|20)\d{2}(?:\s+[A-Za-z][A-Za-z .'-]{1,40})?$",
            normalized,
            flags=re.IGNORECASE,
        )
        return bool(year_range)

    @staticmethod
    def _is_valid_education_row(row: dict[str, Any]) -> bool:
        school = str(row.get("school") or "").strip()
        degree = str(row.get("degree") or "").strip()
        major = str(row.get("major") or "").strip()
        if not school and not degree and not major:
            return False
        if school and CVParserService._looks_like_date_location_line(school) and not degree and not major:
            return False
        return True

    @staticmethod
    def _extract_year_from_text(text: str | None) -> str | None:
        if not text:
            return None
        match = re.search(r"(19|20)\d{2}", str(text))
        return match.group(0) if match else None

    @staticmethod
    def _extract_date_range_from_text(text: str | None) -> tuple[str | None, str | None]:
        if not text:
            return None, None
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        # Accept common CV date ranges: 2021-01 - 2023-06, 2020 to Present, 2019–2021.
        match = re.search(
            r"((?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?)\s*(?:-|–|—|to)\s*((?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?|present|current|now)",
            normalized,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        start_raw = match.group(1)
        end_raw = match.group(2)
        end_value = "Present" if end_raw.lower() in {"present", "current", "now"} else end_raw
        return start_raw, end_value

    @staticmethod
    def _combine_period(start_date: str | None, end_date: str | None) -> str | None:
        if start_date and end_date:
            return f"{start_date} - {end_date}"
        if start_date:
            return start_date
        if end_date:
            return end_date
        return None

    @staticmethod
    def _extract_company_from_text(text: str | None) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        patterns = [
            r"\bat\s+([A-Z][A-Za-z0-9&.,'()/-]{1,80}?)(?=\s+(?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?\b|$)",
            r"\bwith\s+([A-Z][A-Za-z0-9&.,'()/-]{1,80}?)(?=\s+(?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?\b|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return match.group(1).strip(" .,-;:")
        return None

    @staticmethod
    def _extract_title_from_text(text: str | None) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        title_patterns = [
            r"\b(senior|lead|principal|staff)?\s*(software|backend|frontend|full[- ]stack|data|machine learning|research|devops|product)?\s*(engineer|developer|scientist|manager|analyst|consultant|intern)\b",
            r"\b(research assistant|teaching assistant|project manager|product manager)\b",
        ]
        for pattern in title_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None

    @staticmethod
    def _digits_only(value: str | None) -> str:
        if not value:
            return ""
        return "".join(ch for ch in value if ch.isdigit())

    @staticmethod
    def _prefer_phone_format(existing: str, hinted: str) -> str:
        existing_digits = CVParserService._digits_only(existing)
        hinted_digits = CVParserService._digits_only(hinted)
        if existing_digits and existing_digits == hinted_digits:
            # Prefer the version that preserves brackets from original CV text.
            if "(" in hinted or ")" in hinted:
                return hinted
            return existing
        return existing


def build_parser_service() -> CVParserService:
    return CVParserService(
        llm_client=LLMClient(),
        cache=HashCache(settings.cache_dir),
    )
