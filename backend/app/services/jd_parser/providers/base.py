# Base types and helpers for pluggable JD enrichment providers.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JDEnrichmentResult:
    """Carries enriched JD fields produced by a provider."""

    provider_name: str
    must_skills: list[dict[str, Any]] = field(default_factory=list)
    preferred_skills: list[dict[str, Any]] = field(default_factory=list)
    jd_overview: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    raw_output: Any = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Return True when the provider produced a usable result."""
        return self.error is None


class JDEnrichmentProvider(ABC):
    """Base class for JD enrichment providers (hybrid LLM, local Qwen, ...)."""

    name: str = "base"

    @abstractmethod
    async def refine(
        self,
        *,
        jd_text: str,
        preprocessed_payload: dict[str, Any],
        rule_structured: dict[str, Any],
    ) -> JDEnrichmentResult:
        """Refine rule-parsed JD data into an enriched result."""


def build_refined_skill_items(
    must_names: list[str],
    preferred_names: list[str],
    reasoning_trace: list[dict[str, Any]],
    rule_structured: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert refined skill names into standard skill items; excerpts are filled later."""
    _ = rule_structured
    trace_by_name: dict[str, dict[str, Any]] = {}
    for item in reasoning_trace:
        skill = str(item.get("skill", "")).strip().lower()
        if skill:
            trace_by_name[skill] = item

    def build_item(name: str, order: int, weight: float) -> dict[str, Any]:
        """Build one standard skill item, keeping the pre-map name for excerpt lookup."""
        name = name.strip()
        canonical = name.lower().replace(" ", "_")
        trace_item = trace_by_name.get(name.lower())
        confidence = 0.75
        if trace_item and trace_item.get("confidence") is not None:
            try:
                confidence = float(trace_item["confidence"])
            except (TypeError, ValueError):
                confidence = 0.75
        return {
            "skill_id": f"{canonical}_{order}",
            "display_name": name.title(),
            "canonical_skill": canonical,
            "priority_order": order,
            "weight": weight,
            "extracted_name": name,
            "provenance": {
                "source_sentence": "",
                "source_char_start": 0,
                "source_char_end": 0,
                "confidence": confidence,
            },
        }

    must_items = [build_item(name, idx + 1, 1.0) for idx, name in enumerate(must_names[:10])]
    must_set = {name.strip().lower() for name in must_names}
    kept_preferred = [name for name in preferred_names if name.strip().lower() not in must_set][:10]
    preferred_items = [build_item(name, idx + 1, 0.6) for idx, name in enumerate(kept_preferred)]
    return must_items, preferred_items