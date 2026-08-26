# Compatibility shim: CV parse skill lives in .codex/skills/cv-parser.
from cv_parser.skill import parse_cv_skill
from cv_parser.service import CVParserService, build_cv_parser_service

__all__ = ["parse_cv_skill", "CVParserService", "build_cv_parser_service"]
