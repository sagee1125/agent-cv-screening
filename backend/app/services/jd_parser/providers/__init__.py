# Provider registry and factory for pluggable JD enrichment providers.
from __future__ import annotations

from typing import Any

from app.services.jd_parser.providers.base import (
    JDEnrichmentProvider,
    JDEnrichmentResult,
    build_refined_skill_items,
)
from app.services.jd_parser.providers.llm_refiner import LLMRefinerProvider
from app.services.jd_parser.providers.qwen import QwenJDExtractorProvider

VALID_MODES = ("rule", "hybrid", "qwen")


def normalize_mode(mode: str | None) -> str:
    """Normalize a user-supplied parser mode to a known mode string."""
    normalized = (mode or "").strip().lower()
    return normalized if normalized in VALID_MODES else "rule"


def build_enrichment_provider(mode: str | None, *, llm_client: Any = None) -> JDEnrichmentProvider | None:
    """Build the enrichment provider for a mode; returns None for rule mode."""
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