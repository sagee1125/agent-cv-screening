# Publishes the stable public API for candidate matching consumers.
from .config_builder import build_matching_config
from .contracts import (
    ALGORITHM_VERSION,
    DEFAULT_WEIGHTS,
    DIMENSION_IDS,
    EffectiveConfig,
    MatchingConfigError,
    SCHEMA_VERSION,
)
from .engine import match_candidate
from .ranker import rank_candidates
from .service import CandidateMatchingService

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
