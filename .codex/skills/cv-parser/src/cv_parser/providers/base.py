# Base types for pluggable CV enrichment providers.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CVEnrichmentResult:
    """Carries a refined structured CV payload from a hybrid provider."""

    provider_name: str
    structured: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    raw_output: Any = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Return True when the provider returned a usable structured object."""
        return self.error is None and isinstance(self.structured, dict)


class CVEnrichmentProvider(ABC):
    """Base class for CV enrichment (hybrid LLM refinement after vision/text parse)."""

    name: str = "base"

    @abstractmethod
    async def refine(
        self,
        *,
        masked_cv_text: str,
        jd_text: str | None,
        draft_structured: dict[str, Any],
    ) -> CVEnrichmentResult:
        """Refine a draft CV parse using redacted text and optional JD context."""
