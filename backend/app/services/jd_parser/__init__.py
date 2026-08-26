# Compatibility shim: JD parser rule engine lives in .codex/skills/jd-parser.
from jd_parser.service import JDParserService, build_jd_parser_service
from jd_parser.mode import VALID_MODES, normalize_mode
from app.services.jd_parser.providers import (
    JDEnrichmentProvider,
    JDEnrichmentResult,
    LLMRefinerProvider,
    QwenJDExtractorProvider,
    build_enrichment_provider,
)

__all__ = [
    "JDParserService",
    "JDEnrichmentProvider",
    "JDEnrichmentResult",
    "LLMRefinerProvider",
    "QwenJDExtractorProvider",
    "VALID_MODES",
    "build_enrichment_provider",
    "build_jd_parser_service",
    "normalize_mode",
]
