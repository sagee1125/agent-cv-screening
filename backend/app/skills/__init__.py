# Re-exports skill functions for REST; leaf logic is moving into .codex/skills/.
"""Skill orchestration layer.

Single source of truth shared by two entry points:
- REST API routes (backend/app/api/routes/*) -> for the frontend
- Agent CLI scripts (.codex/skills/*/scripts/*) -> for Codex skills / future agent

Both call the same functions here, so HTTP and Skill paths stay compatible.

TODO(agent-migration): Leaf skills (cv-parser, jd-parser, scorer, report-gen, polyu-import)
now own their domain packages. This module re-exports them for REST. JD hybrid/qwen
enrichment remains backend-only.

"""
from app.skills.cv_parse import parse_cv_skill
from app.skills.jd_parse import parse_jd_skill
from app.skills.polyu_import import fetch_and_parse_polyu_job_skill, fetch_polyu_job_skill, list_polyu_catalog_skill
from app.skills.report import generate_candidate_report_skill, generate_comparison_report_skill
from app.skills.score import build_scoring_config_from_jd, rank_candidates_skill, score_candidate_skill

__all__ = [
    "parse_cv_skill",
    "parse_jd_skill",
    "score_candidate_skill",
    "rank_candidates_skill",
    "build_scoring_config_from_jd",
    "generate_candidate_report_skill",
    "generate_comparison_report_skill",
    "list_polyu_catalog_skill",
    "fetch_polyu_job_skill",
    "fetch_and_parse_polyu_job_skill",
]
