"""Skill entry point for the CV Parser service.

Wraps CVParserService so the REST API and the agent CLI scripts share one path.

TODO(agent-migration): When the REST API is deprecated, merge this module into .codex/skills/cv-parser/ so the skill becomes self-contained for the integrated agent.
"""
from __future__ import annotations

from typing import Any

from app.services.cv_parser import CVParserService, build_cv_parser_service


async def parse_cv_skill(
    file_path: str,
    jd_text: str | None = None,
    *,
    parser: CVParserService | None = None,
) -> dict[str, Any]:
    """Parse a CV PDF into structured candidate data.

    Args:
        file_path: Absolute or relative path to the CV PDF file.
        jd_text: Optional JD text used as parsing context.
        parser: Optional injected CVParserService (used by the REST API);
            a default service is built when omitted (used by CLI scripts).
    """
    service = parser or build_cv_parser_service()
    return await service.parse_cv(file_path=file_path, jd_text=jd_text)
