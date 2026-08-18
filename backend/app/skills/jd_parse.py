"""Skill entry point for the JD Parser service.

Wraps JDParserService so the REST API and the agent CLI scripts share one path.

TODO(agent-migration): When the REST API is deprecated, merge this module into .codex/skills/jd-parser/ so the skill becomes self-contained for the integrated agent.
"""
from __future__ import annotations

from typing import Any

from app.services.jd_parser import JDParserService, build_jd_parser_service


async def parse_jd_skill(
    jd_text: str,
    *,
    parser: JDParserService | None = None,
) -> dict[str, Any]:
    """Parse JD text into structured skill/requirement data.

    Args:
        jd_text: Raw job description text.
        parser: Optional injected JDParserService (used by the REST API);
            a default service is built when omitted (used by CLI scripts).
    """
    service = parser or build_jd_parser_service()
    return await service.parse_jd(jd_text=jd_text)
