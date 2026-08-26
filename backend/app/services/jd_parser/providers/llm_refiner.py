# LLM-based JD enrichment provider backed by the project's shared LLM client.
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.core.llm_client import LLMClient
from jd_parser.prompts import (
    JD_SKILL_REFINER_SYSTEM_PROMPT,
    build_jd_skill_refiner_user_prompt,
)
from jd_parser.providers.base import (
    JDEnrichmentProvider,
    JDEnrichmentResult,
    build_refined_skill_items,
)

logger = logging.getLogger(__name__)


class LLMRefinerProvider(JDEnrichmentProvider):
    """Refines JD must/preferred skills with the configured LLM API."""

    name = "hybrid"

    def __init__(self, llm_client: Any | None = None, model: str | None = None) -> None:
        """Bind the shared LLM client and optional model override."""
        self._llm_client = llm_client or LLMClient()
        self._model = model or settings.jd_parser_llm_model

    async def refine(
        self,
        *,
        jd_text: str,
        preprocessed_payload: dict[str, Any],
        rule_structured: dict[str, Any],
    ) -> JDEnrichmentResult:
        llm_input = preprocessed_payload.get("preprocessed_for_llm", {})
        messages = [
            {"role": "system", "content": JD_SKILL_REFINER_SYSTEM_PROMPT},
            {"role": "user", "content": build_jd_skill_refiner_user_prompt(llm_input)},
        ]
        try:
            response = await self._llm_client.chat_completion_messages(
                messages,
                model=self._model,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.warning("JD LLM skill refinement failed: %s", exc)
            return JDEnrichmentResult(
                provider_name=self.name,
                error=str(exc),
                notes=["LLM refinement failed; kept rule output."],
            )

        parsed = response.get("parsed") or {}
        must_names = _as_string_list(parsed.get("must_skills"))
        preferred_names = _as_string_list(parsed.get("preferred_skills"))
        trace = parsed.get("reasoning_trace") if isinstance(parsed.get("reasoning_trace"), list) else []
        if not must_names and not preferred_names:
            return JDEnrichmentResult(
                provider_name=self.name,
                error="LLM returned no skills.",
                notes=["LLM returned no skills; kept rule output."],
                raw_output=parsed,
            )

        must_items, preferred_items = build_refined_skill_items(
            must_names, preferred_names, trace, rule_structured
        )
        return JDEnrichmentResult(
            provider_name=self.name,
            must_skills=must_items,
            preferred_skills=preferred_items,
            raw_output=parsed,
            notes=[f"Skills refined with {self._model or 'default LLM'}."],
        )


def _as_string_list(value: Any) -> list[str]:
    """Convert an LLM list value into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]