# Compatibility shim: scoring skill functions live in the scorer skill.
from scorer.skill import (
    build_scoring_config_from_jd,
    rank_candidates_skill,
    score_candidate_skill,
)
from scorer.service import ScorerService

__all__ = [
    "ScorerService",
    "build_scoring_config_from_jd",
    "rank_candidates_skill",
    "score_candidate_skill",
]
