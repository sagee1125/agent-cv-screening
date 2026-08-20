# SQLAlchemy models for job posts, candidates, scoring, and related records.
import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    DECIMAL,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class JobPostStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class FitLevel(enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CVParseStatus(enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


ENUM_VALUE_OPTIONS = {
    "values_callable": lambda enum_cls: [item.value for item in enum_cls],
    "validate_strings": True,
}


class JobPost(Base):
    __tablename__ = "job_posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    head_count = Column(Integer, nullable=False, default=1)
    status = Column(
        SQLEnum(JobPostStatus, name="job_post_status", **ENUM_VALUE_OPTIONS),
        nullable=False,
        default=JobPostStatus.DRAFT,
    )
    start_date = Column(DateTime, nullable=False)
    closed_date = Column(DateTime, nullable=True)
    jd_parsed_json = Column(JSONB, nullable=False, default=dict)
    weight_config_json = Column(JSONB, nullable=False, default=dict)
    matching_config_json = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    matching_schema_version = Column(
        String(20),
        nullable=False,
        default="1.0.0",
        server_default="1.0.0",
    )
    current_score_version = Column(Integer, nullable=False, default=0, server_default="0")
    matching_status = Column(
        String(20),
        nullable=False,
        default="unscored",
        server_default="unscored",
    )
    last_scored_at = Column(DateTime(timezone=True), nullable=True)
    last_matching_error_code = Column(String(64), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    source = Column(String(50), nullable=True)
    external_ref = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    resumes = relationship("Resume", back_populates="job_post", cascade="all, delete-orphan")
    jd_parser_histories = relationship(
        "JDParserHistory",
        back_populates="job_post",
        cascade="all, delete-orphan",
    )
    matching_recalc_jobs = relationship(
        "MatchingRecalcJob",
        back_populates="job_post",
        cascade="all, delete-orphan",
    )
    candidate_match_scores = relationship(
        "CandidateMatchScore",
        back_populates="job_post",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("head_count > 0", name="ck_job_posts_head_count_positive"),
        CheckConstraint(
            "current_score_version >= 0",
            name="ck_job_posts_current_score_version_nonnegative",
        ),
        CheckConstraint(
            "matching_status IN ('unscored', 'pending', 'running', 'ready', 'stale', 'failed')",
            name="ck_job_posts_matching_status",
        ),
        Index("idx_job_posts_status_created_at", "status", "created_at"),
        Index("idx_job_posts_matching_status_updated_at", "matching_status", "updated_at"),
        Index("idx_job_posts_deleted_at", "deleted_at"),
        Index("idx_job_posts_jd_parsed_json", "jd_parsed_json", postgresql_using="gin"),
        Index("idx_job_posts_weight_config_json", "weight_config_json", postgresql_using="gin"),
        Index("uq_job_posts_source_external_ref", "source", "external_ref", unique=True),
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    resumes = relationship("Resume", back_populates="candidate")
    match_scores = relationship("CandidateMatchScore", back_populates="candidate")


## job scoped
class Resume(Base):
    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False, index=True)
    job_post_id = Column(UUID(as_uuid=True), ForeignKey("job_posts.id"), nullable=False, index=True)
    
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=False)
    source_channel = Column(String(64), nullable=False, default="manual_upload")
    uploaded_at = Column(DateTime, server_default=func.now())

    candidate = relationship("Candidate", back_populates="resumes")
    job_post = relationship("JobPost", back_populates="resumes")
    extracted_data = relationship("ExtractedData", back_populates="resume", uselist=False)
    scoring_results = relationship("ScoringResult", back_populates="resume")
    match_scores = relationship("CandidateMatchScore", back_populates="resume")

    __table_args__ = (
        # One resume per (candidate, job): re-uploading overwrites the same row instead of inserting.
        UniqueConstraint("candidate_id", "job_post_id", name="uq_resumes_candidate_job"),
        Index("idx_resumes_job_uploaded", "job_post_id", "uploaded_at"),
    )


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("resumes.id"), unique=True, nullable=False, index=True)
    structured_data = Column(JSONB, nullable=False)
    raw_llm_response = Column(JSONB, nullable=True)
    extraction_model = Column(String(50), nullable=False)
    extraction_seed = Column(Integer, default=42)
    status = Column(String(20), default="pending", nullable=False)
    error_message = Column(Text, nullable=True)
    extracted_at = Column(DateTime, server_default=func.now())

    resume = relationship("Resume", back_populates="extracted_data")

    __table_args__ = (
        Index("idx_extracted_skills", "structured_data", postgresql_using="gin"),
    )


class DepartmentConfig(Base):
    __tablename__ = "department_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_name = Column(String(100), nullable=False, index=True)
    position_name = Column(String(100), nullable=False)
    config_version = Column(String(20), default="v1.0")
    config = Column(JSONB, nullable=False)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    scoring_results = relationship("ScoringResult", back_populates="config")


class ScoringResult(Base):
    __tablename__ = "scoring_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("resumes.id"), nullable=False, index=True)
    config_id = Column(UUID(as_uuid=True), ForeignKey("department_configs.id"), nullable=False, index=True)
    config_version_at_time = Column(String(20), nullable=False)
    dimension_scores = Column(JSONB, nullable=False)
    total_score = Column(DECIMAL(5, 2), nullable=False, index=True)
    tier = Column(String(20), nullable=False)
    rank = Column(Integer, nullable=False)
    full_snapshot = Column(JSONB, nullable=False)
    scored_at = Column(DateTime, server_default=func.now())

    resume = relationship("Resume", back_populates="scoring_results")
    config = relationship("DepartmentConfig", back_populates="scoring_results")
    feedback_logs = relationship("FeedbackLog", back_populates="scoring_result")


class FeedbackLog(Base):
    __tablename__ = "feedback_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scoring_result_id = Column(UUID(as_uuid=True), ForeignKey("scoring_results.id"), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    context = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    scoring_result = relationship("ScoringResult", back_populates="feedback_logs")


class JDParserHistory(Base):
    __tablename__ = "jd_parser_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_post_id = Column(UUID(as_uuid=True), ForeignKey("job_posts.id"), nullable=False, index=True)
    parsed_json = Column(JSONB, nullable=False, default=dict)
    weight_config_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    job_post = relationship("JobPost", back_populates="jd_parser_histories")

    __table_args__ = (
        Index("idx_jd_parser_history_job_post_created_at", "job_post_id", "created_at"),
        Index("idx_jd_parser_history_parsed_json", "parsed_json", postgresql_using="gin"),
    )


class SkillTaxonomy(Base):
    __tablename__ = "skill_taxonomy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    synonyms = Column(ARRAY(String), default=[])
    parent_skill_id = Column(Integer, ForeignKey("skill_taxonomy.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class MatchingRecalcJob(Base):
    """Persist one job-scoped candidate matching recalculation attempt."""

    __tablename__ = "matching_recalc_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_post_id = Column(UUID(as_uuid=True), ForeignKey("job_posts.id"), nullable=False)
    target_score_version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    trigger = Column(String(32), nullable=False)
    reason = Column(Text, nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    config_hash = Column(String(64), nullable=False)
    algorithm_version = Column(String(64), nullable=False)
    candidates_total = Column(Integer, nullable=False, default=0, server_default="0")
    candidates_processed = Column(Integer, nullable=False, default=0, server_default="0")
    candidates_failed = Column(Integer, nullable=False, default=0, server_default="0")
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    requested_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    job_post = relationship("JobPost", back_populates="matching_recalc_jobs")
    scores = relationship(
        "CandidateMatchScore",
        back_populates="recalc_job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "job_post_id",
            "idempotency_key",
            name="uq_matching_recalc_jobs_job_idempotency",
        ),
        UniqueConstraint(
            "job_post_id",
            "target_score_version",
            name="uq_matching_recalc_jobs_job_version",
        ),
        CheckConstraint(
            "target_score_version > 0",
            name="ck_matching_recalc_jobs_target_version_positive",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_matching_recalc_jobs_status",
        ),
        CheckConstraint(
            "trigger IN ('manual', 'cv_uploaded', 'jd_updated', 'config_updated', 'retry')",
            name="ck_matching_recalc_jobs_trigger",
        ),
        CheckConstraint(
            "candidates_total >= 0 AND candidates_processed >= 0 AND candidates_failed >= 0",
            name="ck_matching_recalc_jobs_counters_nonnegative",
        ),
        CheckConstraint(
            "candidates_processed + candidates_failed <= candidates_total",
            name="ck_matching_recalc_jobs_counter_total",
        ),
        Index("idx_matching_recalc_jobs_job_created", "job_post_id", "created_at"),
        Index("idx_matching_recalc_jobs_status_created", "status", "created_at"),
        Index("idx_matching_recalc_jobs_status_heartbeat", "status", "heartbeat_at"),
    )


class CandidateMatchScore(Base):
    """Store an immutable candidate score within one published score version."""

    __tablename__ = "candidate_match_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_post_id = Column(UUID(as_uuid=True), ForeignKey("job_posts.id"), nullable=False)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("resumes.id"), nullable=False)
    recalc_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("matching_recalc_jobs.id"),
        nullable=False,
    )
    score_version = Column(Integer, nullable=False)
    algorithm_version = Column(String(64), nullable=False)
    schema_version = Column(String(20), nullable=False)
    config_hash = Column(String(64), nullable=False)
    cv_file_hash = Column(String(64), nullable=False)
    eligibility_status = Column(String(20), nullable=False)
    total_score = Column(DECIMAL(5, 2), nullable=False)
    fit_band = Column(String(20), nullable=False)
    evidence_confidence = Column(DECIMAL(5, 2), nullable=False)
    recommendation_rank = Column(Integer, nullable=True)
    dimension_results = Column(JSONB, nullable=False)
    eligibility_results = Column(JSONB, nullable=False)
    interview_questions = Column(JSONB, nullable=False)
    config_snapshot = Column(JSONB, nullable=False)
    input_snapshot = Column(JSONB, nullable=False)
    top_strengths = Column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    key_gaps = Column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    is_published = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    scored_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_post = relationship("JobPost", back_populates="candidate_match_scores")
    candidate = relationship("Candidate", back_populates="match_scores")
    resume = relationship("Resume", back_populates="match_scores")
    recalc_job = relationship("MatchingRecalcJob", back_populates="scores")

    __table_args__ = (
        UniqueConstraint(
            "job_post_id",
            "candidate_id",
            "score_version",
            name="uq_candidate_match_scores_job_candidate_version",
        ),
        UniqueConstraint(
            "recalc_job_id",
            "candidate_id",
            name="uq_candidate_match_scores_recalc_candidate",
        ),
        CheckConstraint("score_version > 0", name="ck_candidate_match_scores_version_positive"),
        CheckConstraint(
            "eligibility_status IN ('passed', 'needs_review', 'failed')",
            name="ck_candidate_match_scores_eligibility",
        ),
        CheckConstraint(
            "total_score >= 0 AND total_score <= 100",
            name="ck_candidate_match_scores_total_score",
        ),
        CheckConstraint(
            "evidence_confidence >= 0 AND evidence_confidence <= 100",
            name="ck_candidate_match_scores_confidence",
        ),
        CheckConstraint(
            "fit_band IN ('high', 'medium', 'low')",
            name="ck_candidate_match_scores_fit_band",
        ),
        CheckConstraint(
            "recommendation_rank IS NULL OR recommendation_rank > 0",
            name="ck_candidate_match_scores_rank_positive",
        ),
        Index(
            "idx_match_scores_job_version_rank",
            "job_post_id",
            "score_version",
            "is_published",
            "recommendation_rank",
        ),
        Index(
            "idx_match_scores_job_version_score",
            "job_post_id",
            "score_version",
            "eligibility_status",
            "total_score",
        ),
        Index(
            "idx_match_scores_candidate_latest",
            "job_post_id",
            "candidate_id",
            "score_version",
        ),
    )