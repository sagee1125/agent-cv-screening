# Pydantic request and response schemas for the REST API.
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VersionedResponse(BaseModel):
    version: str


class CandidateUploadResponse(VersionedResponse):
    id: UUID
    status: str
    extracted_id: UUID


class CandidateDetailResponse(VersionedResponse):
    id: UUID
    email: str
    name: str
    phone: str | None
    extracted_data: dict[str, Any] | None


class CandidateListItem(BaseModel):
    id: UUID
    email: str
    name: str
    phone: str | None
    created_at: datetime | None


class CandidateListResponse(VersionedResponse):
    items: list[CandidateListItem]
    total: int
    page: int
    limit: int


class JobCreateRequest(BaseModel):
    department_name: str
    position_name: str
    jd_text: str
    config: dict[str, Any]
    created_by: str = "system"


class JobConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


class JobResponse(VersionedResponse):
    id: UUID
    department_name: str
    position_name: str
    config_version: str
    config: dict[str, Any]


class JobConfigUpdateResponse(VersionedResponse):
    id: UUID
    config_version: str
    updated_at: datetime | None


class ScoreStartResponse(VersionedResponse):
    job_id: UUID
    status: str
    candidates_queued: int


class ScoringListItem(BaseModel):
    rank: int
    candidate_id: UUID
    total_score: Decimal
    tier: str
    model_config = ConfigDict(from_attributes=True)


class ScoringListResponse(VersionedResponse):
    items: list[ScoringListItem]
    total: int
    page: int
    limit: int


class ScoreDetailResponse(VersionedResponse):
    candidate_id: UUID
    dimension_scores: dict[str, float]
    total_score: Decimal
    tier: str
    skill_match_details: dict[str, Any]
    rank: int


class ReportGenerationRequest(BaseModel):
    job_id: UUID


class ComparisonReportRequest(BaseModel):
    format: str = "excel"


class ReportGenerationResponse(VersionedResponse):
    report_id: str
    download_url: str


class FeedbackLogRequest(BaseModel):
    scoring_result_id: UUID
    action: str
    context: dict[str, Any] | None = None
    user_id: str = "anonymous"


class FeedbackLogResponse(VersionedResponse):
    status: str


class FeedbackAnalyticsResponse(VersionedResponse):
    top_10_hit_rate: float = Field(ge=0, le=1)
    average_score_invited: float
    avg_time_to_hire_days: float


class SkillSchema(BaseModel):
    skill_id: str
    display_name: str
    canonical_skill: str
    priority_order: int
    weight: float
    provenance: dict[str, Any] | None = None


class JobPostCreateRequest(BaseModel):
    title: str
    description: str
    head_count: int = Field(ge=1)
    status: str = "draft"
    start_date: datetime
    closed_date: datetime | None = None


class PolyUCatalogItem(BaseModel):
    job_code: str
    external_ref: str
    title: str
    department: str
    closing_date: datetime | None = None
    detail_url: str
    already_imported: bool = False


class PolyUCatalogResponse(VersionedResponse):
    items: list[PolyUCatalogItem]
    total: int
    new_count: int


class PolyUImportRequest(BaseModel):
    job_code: str
    external_ref: str
    title: str
    department: str = ""
    closing_date: datetime | None = None
    detail_url: str


class JobPostUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    head_count: int | None = Field(default=None, ge=1)
    start_date: datetime | None = None
    closed_date: datetime | None = None


class JobPostStatusUpdateRequest(BaseModel):
    status: str
    closed_date: datetime | None = None


class JDParseRequest(BaseModel):
    jd_text: str


class JobPostItemResponse(BaseModel):
    id: UUID
    title: str
    description: str
    jd_summary_200: str
    head_count: int
    status: str
    start_date: datetime
    closed_date: datetime | None
    jd_parsed_json: dict[str, Any] | None
    weight_config_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class PolyUImportResponse(VersionedResponse):
    action: str
    job: JobPostItemResponse
    parse_error: str | None = None


class JobPostListResponse(VersionedResponse):
    items: list[JobPostItemResponse]
    total: int
    page: int
    limit: int


class JobPostDetailResponse(VersionedResponse):
    job: JobPostItemResponse
    candidates: list[dict[str, Any]]


class JobPostMutationResponse(VersionedResponse):
    id: UUID
    status: str
    updated_at: datetime


class JobPostDuplicateResponse(VersionedResponse):
    new_job_id: UUID


class JDParseResponse(VersionedResponse):
    id: UUID
    jd_parsed_json: dict[str, Any]
    weight_config_json: dict[str, Any]
    updated_at: datetime


class JobCandidateSummaryItem(BaseModel):
    candidate_id: UUID
    resume_id: UUID
    candidate_name: str | None = None
    candidate_email: str | None = None
    original_filename: str
    source_channel: str
    cv_parse_status: str
    extracted_data: dict[str, Any] | None = None
    uploaded_at: datetime | None = None


class JobCandidateListResponse(VersionedResponse):
    items: list[JobCandidateSummaryItem]
    total: int
    page: int
    limit: int


class JobChannelStatItem(BaseModel):
    source_channel: str
    candidate_count: int
    avg_match_score: float


class JobChannelStatsResponse(VersionedResponse):
    job_post_id: UUID
    by_channel: list[JobChannelStatItem]


class JobDiagnosisItem(BaseModel):
    skill: str
    satisfaction_rate: float
    flag_low: bool


class JobDiagnosisResponse(VersionedResponse):
    job_post_id: UUID
    must_skill_satisfaction: list[JobDiagnosisItem]
