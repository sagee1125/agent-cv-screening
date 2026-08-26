# Skill entry: parse JD text with the deterministic rule parser.
from __future__ import annotations

from typing import Any

from jd_parser.service import JDParserService, build_jd_parser_service


# Parse JD text into structured requirements (rule mode unless a provider is injected).
async def parse_jd(
    jd_text: str,
    *,
    parser: JDParserService | None = None,
    mode: str | None = None,
    enrichment_provider: Any = None,
) -> dict[str, Any]:
    service = parser or build_jd_parser_service()
    return await service.parse_jd(
        jd_text=jd_text,
        mode=mode,
        enrichment_provider=enrichment_provider,
    )


# Backward-compatible alias used by CLI tests.
parse_jd_skill = parse_jd
