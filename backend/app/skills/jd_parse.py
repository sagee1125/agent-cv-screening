# Compatibility shim: REST injects hybrid/qwen providers; the skill itself is rule-only.
from __future__ import annotations

from typing import Any

from screening_core.config import settings
from jd_parser.service import JDParserService, build_jd_parser_service
from app.services.jd_parser.providers import build_enrichment_provider


# Parse JD text; REST may enable hybrid/qwen via settings or an explicit mode.
async def parse_jd_skill(
    jd_text: str,
    *,
    parser: JDParserService | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    service = parser or build_jd_parser_service()
    resolved_mode = mode or settings.jd_parser_mode
    provider = build_enrichment_provider(resolved_mode)
    return await service.parse_jd(
        jd_text=jd_text,
        mode=resolved_mode,
        enrichment_provider=provider,
    )
