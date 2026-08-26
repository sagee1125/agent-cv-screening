# Compatibility shim: ReporterService lives in the report-gen skill.
from report_gen.reporter import ReporterService

__all__ = ["ReporterService"]
