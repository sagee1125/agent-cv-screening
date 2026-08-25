# Compatibility shim for CVParserService.
from cv_parser.service import CVParserService, PARSER_CACHE_VERSION, build_cv_parser_service, build_parser_service

__all__ = ["CVParserService", "PARSER_CACHE_VERSION", "build_cv_parser_service", "build_parser_service"]
