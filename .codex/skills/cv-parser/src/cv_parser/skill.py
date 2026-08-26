# Skill entry point for parsing a CV PDF into structured candidate data.
from __future__ import annotations

from typing import Any

from cv_parser.service import CVParserService, build_cv_parser_service


# Parse a CV PDF into structured candidate data (shared by CLI and REST).
async def parse_cv(
    file_path: str,
    jd_text: str | None = None,
    *,
    parser: CVParserService | None = None,
) -> dict[str, Any]:
    service = parser or build_cv_parser_service()
    return await service.parse_cv(file_path=file_path, jd_text=jd_text)


# Backward-compatible alias used by existing CLI tests and REST shims.
parse_cv_skill = parse_cv
