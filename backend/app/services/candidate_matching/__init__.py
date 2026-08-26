# Compatibility shim: candidate matching lives in the scorer skill.
from scorer.matching import *  # noqa: F403
from scorer.matching import (
    ALGORITHM_VERSION,
    CandidateMatchingService,
    DEFAULT_WEIGHTS,
    DIMENSION_IDS,
    EffectiveConfig,
    MatchingConfigError,
    SCHEMA_VERSION,
    build_matching_config,
    match_candidate,
    rank_candidates,
)

__all__ = [
    "ALGORITHM_VERSION",
    "CandidateMatchingService",
    "DEFAULT_WEIGHTS",
    "DIMENSION_IDS",
    "EffectiveConfig",
    "MatchingConfigError",
    "SCHEMA_VERSION",
    "build_matching_config",
    "match_candidate",
    "rank_candidates",
]
