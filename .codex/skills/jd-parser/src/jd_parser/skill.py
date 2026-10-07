# Skill entry: parse JD text with rules, and with Zhipu when a real API key is set.
from __future__ import annotations

from typing import Any

from jd_parser.service import JDParserService, build_jd_parser_service


# Parse JD text into structured requirements (LLM when a ZAI key is configured).
async def parse_jd(
    jd_text: str,
    *,
    parser: JDParserService | None = None,
    mode: str | None = None,
    enrichment_provider: Any = None,
) -> dict[str, Any]:
    service = parser or build_jd_parser_service()
    provider = enrichment_provider
    resolved_mode = mode
    if provider is None and (mode or "").strip().lower() != "rule":
        provider = _zai_refiner_or_none()
        if provider is not None and not (mode or "").strip():
            resolved_mode = "hybrid"
    if provider is None:
        resolved_mode = "rule"
    return await service.parse_jd(
        jd_text=jd_text,
        mode=resolved_mode,
        enrichment_provider=provider,
    )


# Use Zhipu when a real API key is configured. Tests and empty installs stay on the rules.
def _zai_refiner_or_none() -> Any:
    try:
        from screening_core.config import settings
    except Exception:
        return None
    key = str(getattr(settings, "zai_api_key", "") or "").strip()
    if not key or key.startswith("<") or "your-api-key" in key or key == "test-key":
        return None
    from jd_parser.providers.zai import ZaiJDRefiner

    return ZaiJDRefiner()


# Backward-compatible alias used by CLI tests.
parse_jd_skill = parse_jd
