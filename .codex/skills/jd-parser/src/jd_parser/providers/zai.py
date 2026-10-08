# Zhipu refinement of a JD into the standard requirement structure.
from __future__ import annotations

from typing import Any

from jd_parser.prompts import build_jd_structure_user_prompt
from jd_parser.providers.base import (
    JDEnrichmentProvider,
    JDEnrichmentResult,
    build_refined_skill_items,
)

_STRUCTURE_SYSTEM = (
    "You normalize a job advertisement into one JSON object. "
    "Use only what the advertisement states. Return JSON only, no markdown."
)


# Fill every structured JD bucket (skills, education, years, languages, visa) when a ZAI key is set.
class ZaiJDRefiner(JDEnrichmentProvider):
    name = "hybrid"

    def __init__(self, llm_client: Any | None = None) -> None:
        """Bind an optional client; the shared Zhipu client is used when omitted."""
        self._llm_client = llm_client

    async def refine(
        self,
        *,
        jd_text: str,
        preprocessed_payload: dict[str, Any],
        rule_structured: dict[str, Any],
    ) -> JDEnrichmentResult:
        from screening_core.llm_client import LLMClient

        client = self._llm_client or LLMClient()
        messages = [
            {"role": "system", "content": _STRUCTURE_SYSTEM},
            {"role": "user", "content": build_jd_structure_user_prompt(jd_text, preprocessed_payload)},
        ]
        try:
            response = await client.chat_completion_messages(
                messages,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            return JDEnrichmentResult(
                provider_name=self.name,
                error=str(exc),
                notes=["LLM refinement failed; kept rule output."],
            )

        parsed = response.get("parsed") if isinstance(response, dict) else None
        if not isinstance(parsed, dict):
            return JDEnrichmentResult(
                provider_name=self.name,
                error="LLM returned no JSON object.",
                notes=["LLM returned no JSON; kept rule output."],
                raw_output=response,
            )
        must_names = _string_list(parsed.get("must_skills"))
        preferred_names = _string_list(parsed.get("preferred_skills"))
        trace = parsed.get("reasoning_trace") if isinstance(parsed.get("reasoning_trace"), list) else []
        education = parsed.get("education") if isinstance(parsed.get("education"), dict) else None
        experience = parsed.get("experience") if isinstance(parsed.get("experience"), dict) else None
        languages = parsed.get("languages") if isinstance(parsed.get("languages"), list) else None
        visa = parsed.get("visa") if isinstance(parsed.get("visa"), dict) else None
        if not must_names and not preferred_names and not education and not experience and not languages and not visa:
            return JDEnrichmentResult(
                provider_name=self.name,
                error="LLM returned no requirements.",
                notes=["LLM returned no requirements; kept rule output."],
                raw_output=parsed,
            )
        must_items, preferred_items = build_refined_skill_items(
            must_names, preferred_names, trace, rule_structured
        )
        return JDEnrichmentResult(
            provider_name=self.name,
            must_skills=must_items,
            preferred_skills=preferred_items,
            education=education,
            experience=experience,
            languages=languages,
            visa=visa,
            raw_output=parsed,
            notes=["Requirements filled by the configured LLM."],
        )


def _string_list(value: Any) -> list[str]:
    """Keep only non-empty strings from a model list."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
