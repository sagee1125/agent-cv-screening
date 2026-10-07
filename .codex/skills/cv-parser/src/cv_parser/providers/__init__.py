# Pluggable CV enrichment providers (hybrid LLM refinement).
from cv_parser.providers.base import CVEnrichmentProvider, CVEnrichmentResult
from cv_parser.providers.zai import ZaiCVRefiner

__all__ = ["CVEnrichmentProvider", "CVEnrichmentResult", "ZaiCVRefiner"]
