# Compatibility shim: LLM client lives in screening_core.
from screening_core.llm_client import LLMClient

__all__ = ["LLMClient"]
