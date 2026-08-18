"""Skill orchestration layer.

Single source of truth shared by two entry points:
- REST API routes (backend/app/api/routes/*) -> for the frontend
- Agent CLI scripts (.codex/skills/*/scripts/*) -> for Codex skills / future agent

Both call the same functions here, so HTTP and Skill paths stay compatible.

TODO(agent-migration): When the legacy REST API / traditional frontend is
deprecated, make each skill self-contained by moving this orchestration logic
(and the services it wraps in backend/app/services/*) into the corresponding
skill folder (.codex/skills/<name>/). The integrated agent then runs the whole
pipeline in-process without the API.
"""
from app.skills.cv_parse import parse_cv_skill
from app.skills.jd_parse import parse_jd_skill
from app.skills.score import rank_candidates_skill, score_candidate_skill

__all__ = [
    "parse_cv_skill",
    "parse_jd_skill",
    "score_candidate_skill",
    "rank_candidates_skill",
]
