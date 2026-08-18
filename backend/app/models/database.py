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

    __table_args__ = (
        CheckConstraint("head_count > 0", name="ck_job_posts_head_count_positive"),
        Index("idx_job_posts_status_created_at", "status", "created_at"),
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
    phone = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    resumes = relationship("Resume", back_populates="candidate")


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

    __table_args__ = (
        UniqueConstraint("candidate_id", "file_hash", name="uq_resumes_candidate_file_hash"),
        Index("idx_resumes_candidate_job", "candidate_id", "job_post_id"),
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