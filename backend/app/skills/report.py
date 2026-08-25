# Compatibility shim: report skill functions live in the report-gen skill.
from report_gen.skill import generate_candidate_report_skill, generate_comparison_report_skill
from report_gen.reporter import ReporterService

__all__ = [
    "ReporterService",
    "generate_candidate_report_skill",
    "generate_comparison_report_skill",
]
