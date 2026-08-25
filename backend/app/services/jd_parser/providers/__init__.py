# Provider registry: hybrid/qwen LLM backup stays in backend, rule types come from the skill.
from __future__ import annotations

from typing import Any

from jd_parser.mode import VALID_MODES, normalize_mode
from jd_parser.providers.base import (
    JDEnrichmentProvider,
    JDEnrichmentResult,
    build_refined_skill_items,
)
from app.services.jd_parser.providers.llm_refiner import LLMRefinerProvider
from app.services.jd_parser.providers.qwen import QwenJDExtractorProvider


# Build the enrichment provider for a mode; returns None for rule mode.
def build_enrichment_provider(mode: str | None, *, llm_client: Any = None) -> JDEnrichmentProvider | None:
    normalized = normalize_mode(mode)
    if normalized == "hybrid":
        return LLMRefinerProvider(llm_client=llm_client)
    if normalized == "qwen":
        return QwenJDExtractorProvider()
    return None


__all__ = [
    "JDEnrichmentProvider",
    "JDEnrichmentResult",
    "LLMRefinerProvider",
    "QwenJDExtractorProvider",
    "VALID_MODES",
    "build_enrichment_provider",
    "build_refined_skill_items",
    "normalize_mode",
]
