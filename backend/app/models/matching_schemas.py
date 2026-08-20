# Defines versioned request and response contracts for candidate matching APIs.
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DimensionId = Literal[
    "core_skill_match",
    "relevant_experience",
    "role_seniority_fit",
    "evidence_impact",
    "education_certification",
    "job_specific_match",
]
MatchingStatus = Literal["unscored", "pending", "running", "ready", "stale", "failed"]
EligibilityStatus = Literal["passed", "needs_review", "failed"]
FitBand = Literal["high", "medium", "low"]


class MatchingDimensionConfig(BaseModel):
    """Configure activation and weight for one matching dimension."""

    enabled: bool = True
    weight: float = Field(ge=0)


class MatchingSkillRequirement(BaseModel):
    """Represent one weighted canonical must-skill requirement."""

    skill_id: str
    canonical_skill: str
    weight: float = Field(default=1.0, gt=0)
    minimum_match_strength: float = Field(default=0.7, ge=0, le=1)
    display_name: str | None = None
    provenance: dict[str, Any] | str | None = None


class MatchingEligibilityRule(BaseModel):
    """Represent one independently evaluated eligibility rule."""

    rule_id: str
    mandatory: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)


class JobSpecificRequirement(BaseModel):
    """Represent one weighted requirement in the job-specific dimension."""

    requirement_id: str
    evaluator_type: Literal[
        "preferred_skill",
        "language",
        "research",
        "management",
        "domain",
        "license",
    ]
    weight: float = Field(default=1.0, gt=0)
    mandatory: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] | str | None = None


class MatchingFitBands(BaseModel):
    """Configure fixed total-score thresholds used for fit bands."""

    high_min: float = Field(default=80.0, ge=0, le=100)
    medium_min: float = Field(default=60.0, ge=0, le=100)

    # Ensure the high-fit threshold does not precede the medium threshold.
    @model_validator(mode="after")
    def validate_threshold_order(self) -> MatchingFitBands:
        if self.high_min < self.medium_min:
            raise ValueError("high_min must be greater than or equal to medium_min")
        return self


class InterviewQuestionPolicy(BaseModel):
    """Configure deterministic interview-question count boundaries."""

    min_questions: int = Field(default=3, ge=0, le=6)
    max_questions: int = Field(default=6, ge=1, le=6)

    # Ensure the configured minimum does not exceed the maximum.
    @model_validator(mode="after")
    def validate_question_bounds(self) -> InterviewQuestionPolicy:
        if self.min_questions > self.max_questions:
            raise ValueError("min_questions must be less than or equal to max_questions")
        return self


class MatchingConfig(BaseModel):
    """Define the persisted versioned configuration for one Job Post."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    algorithm_version: str = "candidate-matching-v1"
    dimensions: dict[DimensionId, MatchingDimensionConfig]
    must_skills: list[MatchingSkillRequirement] = Field(default_factory=list)
    eligibility_rules: list[MatchingEligibilityRule] = Field(default_factory=list)
    job_specific_requirements: list[JobSpecificRequirement] = Field(default_factory=list)
    fit_bands: MatchingFitBands = Field(default_factory=MatchingFitBands)
    interview_question_policy: InterviewQuestionPolicy = Field(
        default_factory=InterviewQuestionPolicy
    )

    # Require all and only the fixed six matching dimensions.
    @model_validator(mode="after")
    def validate_dimension_contract(self) -> MatchingConfig:
        required = {
            "core_skill_match",
            "relevant_experience",
            "role_seniority_fit",
            "evidence_impact",
            "education_certification",
            "job_specific_match",
        }
        if set(self.dimensions) != required:
            raise ValueError("dimensions must contain exactly the six fixed dimension IDs")
        return self


class MatchingConfigUpdateRequest(BaseModel):
    """Carry a complete matching configuration replacement."""

    config: MatchingConfig


class LegacyWeightConfigUpdateRequest(BaseModel):
    """Carry the existing frontend skill-weight request shape."""

    weight_config_json: dict[str, Any]


class MatchingConfigResponse(BaseModel):
    """Return configured and normalized effective matching configuration."""

    version: str
    schema_version: str = "1.0.0"
    job_post_id: UUID
    config: dict[str, Any]
    normalized_weights: dict[DimensionId, float]
    config_hash: str
    updated_at: datetime


class MatchingRecalculateRequest(BaseModel):
    """Describe why a matching recalculation was requested."""

    trigger: Literal["manual", "cv_uploaded", "jd_updated", "config_updated", "retry"] = (
        "manual"
    )
    reason: str | None = Field(default=None, max_length=1000)


class MatchingRecalculateResponse(BaseModel):
    """Acknowledge a persisted asynchronous recalculation request."""

    version: str
    schema_version: str = "1.0.0"
    job_post_id: UUID
    recalc_job_id: UUID
    target_score_version: int
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    candidates_queued: int


class MatchingRecalculationStatusResponse(BaseModel):
    """Return current counters and terminal state for a recalculation."""

    version: str
    schema_version: str = "1.0.0"
    recalc_job_id: UUID
    job_post_id: UUID
    target_score_version: int
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    candidates_total: int
    candidates_processed: int
    candidates_failed: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None


class CandidateMatchDetailResponse(BaseModel):
    """Return a complete published candidate match result."""

    version: str
    schema_version: str = "1.0.0"
    job_post_id: UUID
    candidate_id: UUID
    resume_id: UUID
    score_version: int
    algorithm_version: str
    scoring_status: MatchingStatus
    stale: bool
    recommendation_rank: int | None
    match_score: float | None
    fit_band: FitBand | None
    eligibility: dict[str, Any]
    evidence_confidence: float | None
    radar_dimensions: list[dict[str, Any]]
    interview_questions: list[dict[str, Any]]
    metadata: dict[str, Any]


class MatchingErrorEnvelope(BaseModel):
    """Return a stable machine-readable error for matching endpoints."""

    version: str
    schema_version: str = "1.0.0"
    error_code: str
    message: str
    module: Literal["candidate_matching"] = "candidate_matching"
    retryable: bool = False
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class MatchingScoreSnapshot(BaseModel):
    """Describe immutable metadata passed into one candidate score."""

    jd_updated_at: datetime | None
    cv_extracted_at: datetime | None
    reference_date: date
    taxonomy_version: str
