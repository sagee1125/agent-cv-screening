# Zhipu hybrid refinement of a draft CV parse (experience, skills, dates).
from __future__ import annotations

from typing import Any

from cv_parser.prompts import CV_REFINER_SYSTEM_PROMPT, build_cv_refiner_user_prompt
from cv_parser.providers.base import CVEnrichmentProvider, CVEnrichmentResult
from cv_parser.refine_merge import normalize_refiner_payload


class ZaiCVRefiner(CVEnrichmentProvider):
    """Second-pass CV structuring via Zhipu when a real API key is configured."""

    name = "hybrid"

    def __init__(self, llm_client: Any | None = None) -> None:
        """Bind an optional client; the shared Zhipu client is used when omitted."""
        self._llm_client = llm_client

    async def refine(
        self,
        *,
        masked_cv_text: str,
        jd_text: str | None,
        draft_structured: dict[str, Any],
        redacted_image_urls: list[str] | None = None,
    ) -> CVEnrichmentResult:
        from screening_core.config import settings
        from screening_core.llm_client import LLMClient, cv_llm_timeout

        # Page images stay on the machine even if a caller still passes URLs.
        if not masked_cv_text.strip():
            note = "No redacted CV text to refine."
            if redacted_image_urls:
                note = "No redacted CV text to refine. Page images are not sent."
            return CVEnrichmentResult(
                provider_name=self.name,
                error="empty_redacted_content",
                notes=[note],
            )

        client = self._llm_client or LLMClient()
        user_prompt = build_cv_refiner_user_prompt(masked_cv_text, draft_structured, jd_text)
        text_model = getattr(settings, "cv_parser_llm_model", None) or settings.llm_model
        model = text_model
        try:
            response = await client.chat_completion_messages(
                [
                    {"role": "system", "content": CV_REFINER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
                response_format={"type": "json_object"},
                temperature=0,
                seed=42,
                timeout=cv_llm_timeout(),
            )
        except Exception as exc:
            return CVEnrichmentResult(
                provider_name=self.name,
                error=str(exc),
                notes=["LLM refinement failed; kept first-pass parse."],
            )

        parsed = response.get("parsed") if isinstance(response, dict) else None
        if not isinstance(parsed, dict):
            return CVEnrichmentResult(
                provider_name=self.name,
                error="LLM returned no JSON object.",
                notes=["LLM returned no JSON; kept first-pass parse."],
                raw_output=response,
            )

        structured = normalize_refiner_payload(parsed)
        experience = structured.get("experience") if isinstance(structured.get("experience"), list) else []
        skills = structured.get("skills") if isinstance(structured.get("skills"), list) else []
        languages = structured.get("languages") if isinstance(structured.get("languages"), list) else []
        if not experience and not skills and not languages:
            return CVEnrichmentResult(
                provider_name=self.name,
                error="LLM returned no experience or skills.",
                notes=["Empty refinement; kept first-pass parse."],
                raw_output=parsed,
            )

        return CVEnrichmentResult(
            provider_name=self.name,
            structured=structured,
            raw_output=parsed,
            notes=["Applied hybrid CV refinement."],
        )


# Use Zhipu hybrid refinement when a real API key is configured.
def zai_cv_refiner_or_none() -> ZaiCVRefiner | None:
    try:
        from screening_core.config import settings
    except Exception:
        return None
    if not settings.cv_parser_hybrid_enabled:
        return None
    key = str(getattr(settings, "zai_api_key", "") or "").strip()
    if not key or key.startswith("<") or "your-api-key" in key or key == "test-key":
        return None
    return ZaiCVRefiner()
