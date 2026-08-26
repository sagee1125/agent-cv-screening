# Compatibility shim: CV parser implementation lives in .codex/skills/cv-parser.
from cv_parser import CVParserService, build_cv_parser_service, build_parser_service

__all__ = ["CVParserService", "build_cv_parser_service", "build_parser_service"]
