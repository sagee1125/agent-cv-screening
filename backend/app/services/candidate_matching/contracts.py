# Defines stable contracts and constants for deterministic candidate matching.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


SCHEMA_VERSION = "1.0.0"
ALGORITHM_VERSION = "candidate-matching-v1"
DIMENSION_IDS = (
    "core_skill_match",
    "relevant_experience",
    "role_seniority_fit",
    "evidence_impact",
    "education_certification",
    "job_specific_match",
)
DEFAULT_WEIGHTS = {
    "core_skill_match": 0.30,
    "relevant_experience": 0.25,
    "role_seniority_fit": 0.15,
    "evidence_impact": 0.15,
    "education_certification": 0.05,
    "job_specific_match": 0.10,
}
DIMENSION_LABELS = {
    "core_skill_match": "Core Skill Match",
    "relevant_experience": "Relevant Experience",
    "role_seniority_fit": "Role and Seniority Fit",
    "evidence_impact": "Evidence and Impact",
    "education_certification": "Education and Certification",
    "job_specific_match": "Job-Specific Match",
}

SkillRelationResolver = Callable[[str, str], bool]


@dataclass(frozen=True)
class EffectiveConfig:
    """Carries an immutable canonical matching configuration and its identity."""

    config: dict[str, Any]
    canonical_json: str
    config_hash: str


class MatchingConfigError(ValueError):
    """Reports a stable validation failure for matching configuration."""

    # Initializes a validation error with its machine-readable code.
    def __init__(self, message: str, code: str = "MATCHING_CONFIG_INVALID") -> None:
        super().__init__(message)
        self.code = code
