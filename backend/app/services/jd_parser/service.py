# Compatibility shim: JDParserService lives in the jd-parser skill.
from jd_parser.service import JDParserService, build_jd_parser_service, _cn_numeral_to_int

__all__ = ["JDParserService", "build_jd_parser_service", "_cn_numeral_to_int"]
