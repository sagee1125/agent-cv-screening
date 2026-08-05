from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, DECIMAL, Text, Boolean, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import declarative_base, relationship
import uuid

Base = declarative_base()

class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    resumes = relationship("Resume", back_populates="candidate")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), unique=True, nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now())

    candidate = relationship("Candidate", back_populates="resumes")
    extracted_data = relationship("ExtractedData", back_populates="resume", uselist=False)
    scoring_results = relationship("ScoringResult", back_populates="resume")


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


class SkillTaxonomy(Base):
    __tablename__ = "skill_taxonomy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    synonyms = Column(ARRAY(String), default=[])
    parent_skill_id = Column(Integer, ForeignKey("skill_taxonomy.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())