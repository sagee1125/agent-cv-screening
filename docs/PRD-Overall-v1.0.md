# Agent-CV-Screening Product Requirements Document (PRD)

**Version:** 2.0.0  
**Status:** Active Draft  
**Last Updated:** 2026-08-03  
**Related Docs:** `docs/IMPLEMENTATION_PLAN.md`, `docs/FUNCTIONAL_REQUIREMENTS_SPECIFICATION.md`

---

## 1. Product Overview

### 1.1 Background

University departments need a faster and more consistent way to screen large numbers of CVs. Manual review is slow, subjective, and hard to scale when deadlines are tight.

### 1.2 Product Goal

Build a deterministic AI-assisted CV screening system that can:

- ingest CVs in bulk
- extract structured candidate profiles
- rank candidates with transparent scoring logic
- support reviewer decisions with clear insights and interview guidance

### 1.3 Product Positioning

This is the first vertical use case of a broader direction: a future general-purpose evaluation and ranking platform.  
Therefore, modules must be designed for future reuse and service extraction.

---

## 2. Objectives and Success Metrics

### 2.1 Business Objectives

- Reduce initial screening time per hiring cycle
- Improve consistency of shortlist decisions
- Provide a clear audit trail for review actions

### 2.2 Demo Objectives (1 Full-Time Engineer, 4 Weeks)

- Deliver an end-to-end usable demo workflow
- Support mixed-format batch upload (PDF/DOC/DOCX)
- Show ranking, status, candidate insight visualization, and export

### 2.3 Success Metrics

- 200 CV files can be uploaded in one batch (staging/demo target)
- Deterministic ranking stability for repeated runs with same input/config
- 90%+ of uploads complete successfully under normal file quality conditions
- End-to-end demo flow can be completed without manual data patching

---

## 3. Users and Roles

### 3.1 Recruiter / Reviewer (Primary)

- creates or selects job config
- uploads CVs
- triggers scoring
- reviews ranking and candidate details
- logs review actions

### 3.2 Operator (Secondary)

- monitors batch progress
- retries failed files
- validates demo environment readiness

---

## 4. Scope

### 4.1 In Scope

- Job and rubric configuration
- Batch CV upload (`pdf`, `doc`, `docx`)
- Deterministic profile extraction
- Deterministic scoring and ranking
- Candidate status labeling and filtering
- Candidate insight page with 8-dimension radar chart
- Overall assessment summary
- Recommended interview questions
- Comparison report export (`.xlsx` minimum)

### 4.2 Out of Scope (Current Phase)

- Full enterprise authentication and SSO integration
- Complex multi-tenant permission matrix
- Advanced BI dashboards
- Multi-region deployment

---

## 5. Product Principles

1. **Deterministic by Default**  
   Scoring and ranking must be reproducible.
2. **Human-in-the-Loop**  
   AI assists, humans decide.
3. **Explainable Output**  
   Ranking and insights must be understandable to reviewers.
4. **Modular Design**  
   Core modules should be reusable for future generalized ranking systems.
5. **Operational Practicality**  
   Bulk upload visibility, status tracking, and retry are mandatory.

---

## 6. High-Level Product Architecture

### 6.1 Frontend

- React + TypeScript + Tailwind
- ECharts for radar visualization
- Primary pages:
  - job setup
  - upload workbench
  - ranking board
  - candidate insight
  - report/export actions

### 6.2 Backend

- API service for upload, parsing, scoring, ranking, insight, reports, feedback
- deterministic scoring engine
- profile extraction pipeline with cache

### 6.3 Data Layer

- relational storage for candidates, jobs, results, feedback
- structured JSON fields for extracted profiles and insight payloads

### 6.4 Deployment

- Docker-based runtime for local/staging demo
- CI checks for type safety, tests, and build validity

---

## 7. Required Repository Structure (Product-Level)

The product requires explicit frontend and backend structure at repository level.

- `frontend/`
  - UI application and reusable presentation modules
  - typed API clients and frontend data models
- `backend/`
  - API endpoints and business modules
  - parsing, scoring, reporting, feedback logic
- `data/`
  - uploads, reports, cache, taxonomy/reference resources
- `docs/`
  - PRD, implementation plan, FRS, and related product/engineering docs

---

## 8. End-to-End User Journey

1. Recruiter creates/selects a job and scoring rubric.
2. Recruiter uploads CVs in bulk (mixed formats supported).
3. System parses files and updates file-level processing statuses.
4. System validates minimum identity fields (name required).
5. Eligible candidates are scored and ranked.
6. Recruiter views ranking list and status labels.
7. Recruiter opens candidate details:
   - radar chart
   - overall assessment
   - recommended interview questions
8. Recruiter exports comparison report and logs actions.

---

## 9. Functional Requirements (Product View)

Detailed IDs and traceability are defined in `docs/FUNCTIONAL_REQUIREMENTS_SPECIFICATION.md`.  
This PRD keeps requirements at product level.

### 9.1 Job and Rubric

- Create and update job configurations
- Support configurable scoring dimensions and weights

### 9.2 Batch Upload and Parsing

- Support PDF/DOC/DOCX
- Show per-file status (`queued`, `processing`, `success`, `failed`)
- Support retry on failed files
- Enforce `name` as minimum rank-eligibility field

### 9.3 Ranking and Status

- Deterministic ranking order
- Candidate status labels:
  - `shortlisted`
  - `recommended`
  - `not_recommended`
  - `invalid_profile`
  - `manual_review`

### 9.4 Candidate Insight

- 8-dimension radar chart
- overall assessment (strengths, risks, rationale)
- recommended interview questions

### 9.5 Reporting and Feedback

- comparison export (xlsx)
- feedback action logging for future quality analysis

---

## 10. Candidate Insight Model (Product Definition)

### 10.1 Radar Dimensions (8)

- `skill_match`
- `experience_match`
- `education_match`
- `research_quality`
- `communication_signal`
- `leadership_signal`
- `domain_relevance`
- `project_impact`

### 10.2 Insight Content Blocks

- score summary
- strengths
- risks/gaps
- rationale
- recommended interview questions

---

## 11. Canonical Status and Field Naming

Single source of truth for enum values and core contract names:

- See `docs/FUNCTIONAL_REQUIREMENTS_SPECIFICATION.md` and implementation contracts
- Frontend and backend must use identical enum values and field names

Required status sets:

- processing: `queued | processing | success | failed`
- recommendation: `shortlisted | recommended | not_recommended | invalid_profile | manual_review`

---

## 12. Non-Functional Requirements

### 12.1 Determinism and Reproducibility

- Same input + same configuration should yield same ranking outcome.

### 12.2 Performance Targets (Demo Baseline)

- Handle up to 200 uploads per batch in staging conditions
- Ranking list remains usable for 500+ rows

### 12.3 Reliability

- Failures are visible at file level
- Failed files can be retried without full batch restart

### 12.4 Usability

- Clear status-driven UX for upload and ranking pages
- Fast drill-down from ranking to candidate insight

---

## 13. Reusability and Future Platform Direction

To support future generalized evaluation/ranking use cases:

- Keep parsing, scoring, insight, and reporting as separable modules
- Keep scoring model input generic (not CV-only specific)
- Keep rubric/config externalized and versionable
- Keep frontend modules reusable:
  - `upload-workbench`
  - `ranking-board`
  - `candidate-insight`
  - `config-studio`

---

## 14. Risks and Mitigations

### 14.1 Parsing Variability Across File Formats

- Risk: DOC/DOCX quality varies.
- Mitigation: parser adapters + explicit invalid-profile handling.

### 14.2 Scope Creep During Demo Window

- Risk: one-month timeline slips.
- Mitigation: protect core demo path and strict feature freeze.

### 14.3 Contract Drift Between Frontend and Backend

- Risk: enum/field mismatches break UI integration.
- Mitigation: shared contract definitions and consistency checks.

---

## 15. Demo Acceptance Criteria

Demo is accepted when all are true:

- Mixed-format batch upload works (`pdf/doc/docx`)
- Missing-name candidates are flagged as `invalid_profile`
- Ranking board shows deterministic order and statuses
- Candidate detail page shows:
  - 8-axis radar chart
  - overall assessment
  - recommended interview questions
- Comparison report export works
- End-to-end flow runs successfully in Docker environment

---

## 16. Release Plan Summary

- Target mode: rapid demo release
- Team model: one full-time engineer
- Target schedule: four weeks
- Detailed plan: `docs/IMPLEMENTATION_PLAN.md`

---

## 17. Change Management

Any product-level change to statuses, required fields, or core workflow must update:

1. This PRD
2. `docs/FUNCTIONAL_REQUIREMENTS_SPECIFICATION.md`
3. Backend and frontend contracts in the same implementation cycle

# Agent-CV-Screening: AI-Powered CV Screening System

> **Version:** 1.0.0 | **Status:** Draft | **Date:** 2026-07-27

## 1. Project Overview

### 1.1 Goal

Build a production-ready, multi-tenant AI-powered CV screening system for university departments. Each department can upload job descriptions (JD) and candidate CVs (PDFs), and the system automatically ranks candidates based on skill matching with **deterministic, reproducible outputs**.

### 1.2 Key Requirements

- Multi-department support with configurable scoring weights
- LLM-based CV parsing with **deterministic output** (`temperature=0`, `seed=42`)
- No LLM used in scoring/ranking — pure deterministic calculations
- Every extraction result is cached (hash-based) to ensure reproducibility
- Exportable reports (PDF, Excel, JSON)
- Comprehensive audit trail via feedback logging
- Fully containerized with Docker Compose

### 1.3 Technology Stack

| Layer       | Technology                         | Version        |
| :---------- | :--------------------------------- | :------------- |
| Backend     | Python / FastAPI                   | 3.11+ / 0.115+ |
| Database    | PostgreSQL (with JSONB)            | 15+            |
| ORM         | SQLAlchemy + Alembic               | 2.0+ / 1.14+   |
| LLM         | OpenAI GPT-4o-mini                 | -              |
| PDF Parsing | PyPDF2 + pdfplumber                | 3.0+ / 0.11+   |
| Reports     | ReportLab (PDF) + openpyxl (Excel) | 4.2+ / 3.1+    |
| Deployment  | Docker + Docker Compose            | -              |

### 1.4 Critical Constraint

**Scoring logic must be 100% deterministic.** No LLM calls are allowed in Modules 2 (skill matching) or 3 (scoring/ranking). The LLM is used exclusively in Module 1 for extracting structured data from unstructured CV text.

---

## 2. Directory Structure

```
agent-cv-screening/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app entry
│   │   ├── config.py               # Pydantic Settings
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── database.py         # SQLAlchemy ORM models
│   │   │   └── schemas.py          # Pydantic request/response schemas
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── cv_parser/
│   │   │   ├── skill_matcher.py    # Module 2: Deterministic skill matching
│   │   │   ├── scorer.py           # Module 3: Deterministic scoring & ranking
│   │   │   ├── reporter.py         # Report generation (PDF/Excel/JSON)
│   │   │   └── feedback.py         # Module 4: Feedback logging & analytics
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── dependencies.py     # Dependency injection
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       ├── candidates.py
│   │   │       ├── jobs.py
│   │   │       ├── scoring.py
│   │   │       ├── reports.py
│   │   │       └── feedback.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── llm_client.py       # OpenAI wrapper with seed/temp=0
│   │   │   ├── hash_cache.py       # MD5-based caching for LLM outputs
│   │   │   └── taxonomy.py         # Skill taxonomy loader
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── file_handlers.py    # PDF/DOCX parsing utilities
│   │       └── validators.py       # JSON schema validation
│   ├── migrations/                 # Alembic migrations
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── test_parser.py
│   │   │   ├── test_skill_matcher.py
│   │   │   └── test_scorer.py
│   │   └── integration/
│   │       ├── test_api.py
│   │       └── test_e2e.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── data/
│   ├── uploads/                     # Uploaded PDFs
│   ├── reports/                     # Generated reports
│   ├── cache/                       # LLM response cache
│   └── taxonomy/
│       └── skill_taxonomy.yaml      # Hand-curated skill taxonomy
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## 3. Database Schema (SQLAlchemy Models)

### 3.1 ER Diagram

```
candidates (1) --- (N) resumes (1) --- (1) extracted_data
                              |
                              | (N)
                              V
                      scoring_results (N) --- (1) department_configs
                              |
                              | (N)
                              V
                      feedback_logs (N) --- (1) user_id (external SSO)

skill_taxonomy (N) --- (1) skill_taxonomy (self-referential, parent-child)
```

### 3.2 Models Definition

```python
# app/models/database.py

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

    resumes = relationship("Resume", back_populates="candidate", cascade="all, delete-orphan")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), unique=True, nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now())

    candidate = relationship("Candidate", back_populates="resumes")
    extracted_data = relationship("ExtractedData", back_populates="resume", uselist=False, cascade="all, delete-orphan")
    scoring_results = relationship("ScoringResult", back_populates="resume", cascade="all, delete-orphan")


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("resumes.id"), unique=True, nullable=False, index=True)
    structured_data = Column(JSONB, nullable=False)
    raw_llm_response = Column(JSONB, nullable=True)
    extraction_model = Column(String(50), nullable=False)
    extraction_seed = Column(Integer, default=42)
    status = Column(String(20), default="pending")  # pending | success | failed
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
    config = Column(JSONB, nullable=False)  # See Section 4.2 for schema
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
    dimension_scores = Column(JSONB, nullable=False)  # {"skill_match": 85, "experience_match": 72}
    total_score = Column(DECIMAL(5, 2), nullable=False, index=True)
    tier = Column(String(20), nullable=False)  # Tier 1 | Tier 2 | Tier 3 | Tier 4
    rank = Column(Integer, nullable=False)
    full_snapshot = Column(JSONB, nullable=False)  # Complete context for report generation
    scored_at = Column(DateTime, server_default=func.now())

    resume = relationship("Resume", back_populates="scoring_results")
    config = relationship("DepartmentConfig", back_populates="scoring_results")
    feedback_logs = relationship("FeedbackLog", back_populates="scoring_result", cascade="all, delete-orphan")


class FeedbackLog(Base):
    __tablename__ = "feedback_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scoring_result_id = Column(UUID(as_uuid=True), ForeignKey("scoring_results.id"), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)  # External SSO ID
    action = Column(String(50), nullable=False)  # view | download | star | invite | reject | hire
    context = Column(JSONB, nullable=True)  # {"ai_rank_at_time": 3, "ai_score_at_time": 78.5}
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

    parent = relationship("SkillTaxonomy", remote_side=[id], uselist=False)
```

---

## 4. API Specification

### 4.1 Base URL

```
http://localhost:8000/api/v1
```

### 4.2 Endpoints

#### Candidates

| Method | Endpoint             | Description                     | Request Body                                       | Response                                                           |
| :----- | :------------------- | :------------------------------ | :------------------------------------------------- | :----------------------------------------------------------------- |
| `POST` | `/candidates/upload` | Upload CV (PDF/DOCX)            | `multipart/form-data`: `file`, `job_id` (optional) | `{ "id": "uuid", "status": "processing", "extracted_id": "uuid" }` |
| `GET`  | `/candidates/{id}`   | Get candidate + extracted data  | -                                                  | `{ "id": "uuid", "email": "...", "extracted_data": {...} }`        |
| `GET`  | `/candidates`        | List all candidates (paginated) | Query: `page`, `limit`, `search`                   | `{ "items": [...], "total": 10, "page": 1 }`                       |

#### Jobs / JD

| Method | Endpoint            | Description            | Request Body                                                                              | Response                                                          |
| :----- | :------------------ | :--------------------- | :---------------------------------------------------------------------------------------- | :---------------------------------------------------------------- |
| `POST` | `/jobs`             | Create job + upload JD | `{ "department_name": "...", "position_name": "...", "jd_text": "...", "config": {...} }` | `{ "id": "uuid", "config_version": "v1.0" }`                      |
| `GET`  | `/jobs/{id}`        | Get job details        | -                                                                                         | `{ "id": "uuid", "department_name": "...", "config": {...} }`     |
| `PUT`  | `/jobs/{id}/config` | Update scoring weights | `{ "config": {...} }`                                                                     | `{ "id": "uuid", "config_version": "v1.1", "updated_at": "..." }` |

#### Scoring

| Method | Endpoint                                | Description                          | Request Body                              | Response                                                                                                                    |
| :----- | :-------------------------------------- | :----------------------------------- | :---------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------- |
| `POST` | `/jobs/{job_id}/score`                  | Run scoring for all candidates       | - (async, returns immediately)            | `{ "job_id": "uuid", "status": "scoring_started", "candidates_queued": 45 }`                                                |
| `GET`  | `/jobs/{job_id}/results`                | Get ranked list (paginated)          | Query: `page`, `limit`, `tier` (optional) | `{ "items": [{"rank": 1, "candidate_id": "...", "total_score": 92.3, "tier": "Tier 1"}], "total": 47 }`                     |
| `GET`  | `/jobs/{job_id}/results/{candidate_id}` | Get candidate's full score breakdown | -                                         | `{ "candidate_id": "...", "dimension_scores": {...}, "total_score": 78.5, "tier": "Tier 2", "skill_match_details": {...} }` |

#### Reports

| Method | Endpoint                            | Description                        | Request Body            | Response                                                                                 |
| :----- | :---------------------------------- | :--------------------------------- | :---------------------- | :--------------------------------------------------------------------------------------- |
| `POST` | `/reports/candidate/{candidate_id}` | Generate PDF one-pager             | `{ "job_id": "uuid" }`  | `{ "report_id": "uuid", "download_url": "/reports/download/{report_id}" }`               |
| `POST` | `/reports/comparison/{job_id}`      | Generate comparison report (Excel) | `{ "format": "excel" }` | `{ "report_id": "uuid", "download_url": "/reports/download/{report_id}" }`               |
| `GET`  | `/reports/download/{report_id}`     | Download generated report          | -                       | `application/pdf` or `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

#### Feedback

| Method | Endpoint                       | Description                    | Request Body                                                            | Response                                                                                   |
| :----- | :----------------------------- | :----------------------------- | :---------------------------------------------------------------------- | :----------------------------------------------------------------------------------------- |
| `POST` | `/feedback`                    | Log user action                | `{ "scoring_result_id": "uuid", "action": "invite", "context": {...} }` | `{ "status": "logged" }`                                                                   |
| `GET`  | `/feedback/analytics/{job_id}` | Get system performance metrics | -                                                                       | `{ "top_10_hit_rate": 0.82, "average_score_invited": 86.3, "avg_time_to_hire_days": 2.3 }` |

---

## 5. Core Service Implementations

### 5.1 Module 1: CV Parser (`services/cv_parser/service.py`)

**Purpose:** Extract structured data from unstructured CV text using LLM.

**Input:** PDF file path + optional JD context
**Output:** Standardized JSON with `name`, `email`, `education`, `experience`, `skills`, `publications`

**Key Behaviors:**

- Compute MD5 hash of PDF → check cache before calling LLM
- Use `temperature=0`, `seed=42` for deterministic output
- Use `response_format={"type": "json_object"}` to enforce JSON
- Validate and normalize the output schema
- Store both `structured_data` and `raw_llm_response`

**LLM Prompt Template:**

```
You are a CV parser. Extract the following fields from the candidate's CV and output valid JSON.

Fields:
- name: string
- email: string
- phone: string (optional)
- education: array of {school, degree, major, year}
- experience: array of {company, title, start_date, end_date, description}
- skills: array of string (tech skills only)
- publications: array of {title, journal, year} (optional)

Rules:
- Only extract information explicitly stated in the CV. Do not infer.
- For skills, extract exact terms used (do not standardize).
- If a field is not found, use null or empty array.

CV Text:
{raw_text}

Output valid JSON only. No explanations.
```

### 5.2 Module 2: Skill Matcher (`services/skill_matcher.py`)

**Purpose:** Match candidate skills against JD requirements using deterministic logic.

**Input:** Candidate skills (list), JD requirements (dict), Skill taxonomy
**Output:** Match score (0-100), hit/miss lists, quality score

**Key Behaviors:**

- Normalize skills using synonym mapping from `skill_taxonomy.yaml`
- Check both exact matches and hierarchical matches (parent-child relationships)
- Calculate hit rate: `len(hits) / len(required_skills) * 100`
- Evaluate experience quality using rule-based scoring (project scale, role keywords)

**Quality Scoring Rules (rule-based):**

- Keywords like "百萬" (+20), "千萬" (+30), "億" (+40)
- Role keywords: "主導" (+15), "負責" (+10), "參與" (+5)
- Max score per skill: 100

### 5.3 Module 3: Scorer & Ranker (`services/scorer.py`)

**Purpose:** Calculate multi-dimensional scores and rank candidates.

**Input:** Extracted data (from Module 1), Department config (from DB)
**Output:** Dimension scores, total score (weighted), tier, rank

**Key Behaviors:**

1. Apply hard filters first (education level, experience years, required skills)
2. Calculate each dimension independently (skill_match, experience_match, education_match, etc.)
3. Compute weighted total: `Σ(dimension_score × dimension_weight)`
4. Assign tier based on config.tiers thresholds
5. Sort by total_score descending, assign rank

**NO LLM calls anywhere in this module.**

### 5.4 Core: Hash Cache (`core/hash_cache.py`)

**Purpose:** Cache LLM responses by file hash for reproducibility.

**Key Behaviors:**

- Store cache as JSON files in `data/cache/{hash}.json`
- On parse: compute MD5 of PDF → check cache → return if exists
- On cache miss: call LLM → store result → return

### 5.5 Core: LLM Client (`core/llm_client.py`)

**Purpose:** Wrapper for OpenAI API with deterministic settings.

**Key Behaviors:**

- Always use `temperature=0`, `seed=42`
- Use `gpt-4o-mini` as default model (configurable via env)
- Include retry logic (tenacity: 3 attempts, exponential backoff)
- Log token usage and latency for monitoring

---

## 6. Environment Variables

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Database
DATABASE_URL=postgresql://user:pass@db:5432/agent_cv

# Storage
UPLOAD_DIR=./data/uploads
REPORT_DIR=./data/reports
CACHE_DIR=./data/cache

# LLM
LLM_MODEL=gpt-4o-mini
LLM_TEMPERATURE=0
LLM_SEED=42

# App
DEBUG=true
SECRET_KEY=your-secret-key-here
CORS_ORIGINS=http://localhost:3000,http://localhost:8000
```

---

## 7. Docker Setup

### 7.1 docker-compose.yml

```yaml
version: "3.8"

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: agent_cv
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://user:pass@db:5432/agent_cv
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      LLM_MODEL: ${LLM_MODEL:-gpt-4o-mini}
      LLM_TEMPERATURE: ${LLM_TEMPERATURE:-0}
      LLM_SEED: ${LLM_SEED:-42}
      DEBUG: ${DEBUG:-true}
    volumes:
      - ./data:/app/data
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

volumes:
  postgres_data:
```

### 7.2 backend/Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run as non-root for security
RUN useradd -m -u 1000 appuser
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 8. Testing Requirements

### 8.1 Unit Tests (`tests/unit/`)

| Test File               | Coverage Target                                                               |
| :---------------------- | :---------------------------------------------------------------------------- |
| `test_parser.py`        | Mock LLM responses, test cache hit/miss, test validation, test error handling |
| `test_skill_matcher.py` | Test synonym mapping, hierarchical matching, edge cases (empty skills)        |
| `test_scorer.py`        | Test weighted scoring, hard filters, tier assignment, rejection logic         |
| `test_hash_cache.py`    | Test cache read/write, hash computation, file operations                      |

### 8.2 Integration Tests (`tests/integration/`)

| Test File     | Coverage Target                                                    |
| :------------ | :----------------------------------------------------------------- |
| `test_api.py` | Test all API endpoints with real test database (not production)    |
| `test_e2e.py` | End-to-end: upload CV → parse → score → generate report → download |

### 8.3 Golden Test Set

- Place 5-10 sample CV PDFs in `tests/fixtures/cvs/`
- Place expected JSON outputs in `tests/fixtures/expected/`
- Run validation: `pytest tests/integration/test_golden.py --golden`

---

## 9. Performance Requirements

| Metric                   | Target                     |
| :----------------------- | :------------------------- |
| PDF parsing (LLM call)   | < 5s per CV                |
| Scoring (100 candidates) | < 2s (no LLM in this path) |
| Report generation (PDF)  | < 3s                       |
| API latency (P95)        | < 500ms                    |
| Concurrent users         | 5 simultaneous             |

---

## 10. Code Quality & Conventions

- **Python 3.11+** with type hints on all functions
- **Ruff** for linting and formatting (or `black` + `flake8`)
- **Pytest** for testing with `pytest-asyncio` for async tests
- **Alembic** for database migrations
- **All scoring logic must be deterministic** → no LLM in Module 2 or 3
- All API responses must include `version` metadata

---

## 11. File Descriptions: Data Models

### 11.1 `app/models/database.py`

**What:** SQLAlchemy ORM models defining all database tables.
**Key Tables:** `Candidate`, `Resume`, `ExtractedData`, `DepartmentConfig`, `ScoringResult`, `FeedbackLog`, `SkillTaxonomy`.
**Dependencies:** SQLAlchemy, asyncpg, UUID.

### 11.2 `app/models/schemas.py`

**What:** Pydantic models for request/response validation.
**Key Schemas:**

- `CandidateUploadResponse`
- `JobCreateRequest`
- `ScoringResultResponse`
- `ReportGenerationRequest`
- `FeedbackLogRequest`

### 11.3 `data/taxonomy/skill_taxonomy.yaml`

**What:** Hand-curated skill taxonomy with synonyms and parent-child relationships.
**Format:**

```yaml
- skill: "Python"
  category: "Programming Language"
  synonyms: ["python", "py"]
  parent: null
```

---

## 12. Development Workflow

### 12.1 Initial Setup

```bash
# Clone and setup
git clone {}
cd agent-cv-screening
cp .env.example .env
# Edit .env → add OPENAI_API_KEY

docker-compose up -d
docker-compose exec backend alembic upgrade head

# Verify
curl http://localhost:8000/health
```

### 12.2 Running Tests

```bash
# Unit tests
docker-compose exec backend pytest tests/unit/

# Integration tests
docker-compose exec backend pytest tests/integration/

# With coverage
docker-compose exec backend pytest --cov=app tests/
```

### 12.3 Code Review Process

1. Create a feature branch: `git checkout -b feature/name`
2. Write code and tests
3. Commit with conventional commit messages (`feat:`, `fix:`, `docs:`, etc.)
4. Push to GitHub and create a Pull Request
5. Request review from team members
6. Address feedback and merge

---

## 13. Instructions for Cursor

> **IMPORTANT: The following section is specifically for Cursor AI**

### 13.1 Context Loading

Before generating code, Cursor should load:

1. This PRD document
2. `data/taxonomy/skill_taxonomy.yaml`
3. Existing code in the repository

### 13.2 Code Generation Order

Cursor should generate files in the following order:

1. **Phase 1: Core Infrastructure**

   - `backend/app/config.py`
   - `backend/app/core/llm_client.py`
   - `backend/app/core/hash_cache.py`
   - `backend/app/core/taxonomy.py`

2. **Phase 2: Database & Models**

   - `backend/app/models/database.py`
   - `backend/app/models/schemas.py`
   - `backend/migrations/` (initial migration)

3. **Phase 3: Services**

   - `backend/app/services/cv_parser/service.py`
   - `backend/app/services/skill_matcher.py`
   - `backend/app/services/scorer.py`
   - `backend/app/services/reporter.py`
   - `backend/app/services/feedback.py`

4. **Phase 4: API Routes**

   - `backend/app/api/routes/candidates.py`
   - `backend/app/api/routes/jobs.py`
   - `backend/app/api/routes/scoring.py`
   - `backend/app/api/routes/reports.py`
   - `backend/app/api/routes/feedback.py`

5. **Phase 5: Main App & Tests**
   - `backend/app/main.py`
   - `backend/app/api/dependencies.py`
   - `backend/tests/unit/*.py`
   - `backend/tests/integration/*.py`

### 13.3 Critical Code Review Points

When Cursor generates code, it must ensure:

1. **No LLM calls in scoring logic** — verify `scorer.py` never imports or calls `LLMClient`
2. **All LLM calls use `temperature=0` and `seed=42`** — check `cv_parser/service.py` calls `llm_client.chat_completion(..., temperature=0, seed=42)`
3. **Hash-based caching is implemented** — check `cv_parser/service.py` calls `cache.get()` before `llm_client.chat_completion()`
4. **All functions have type hints** — verify with `mypy` compatibility
5. **All API responses include version metadata** — check `app/main.py` response wrappers

### 13.4 Example: Expected Parser Output

```json
{
  "name": "張三",
  "email": "zhangsan@example.com",
  "phone": "0912-345-678",
  "education": [
    {
      "school": "國立臺灣大學",
      "degree": "博士",
      "major": "資訊工程",
      "year": 2022
    }
  ],
  "experience": [
    {
      "company": "中央研究院",
      "title": "博士後研究員",
      "start_date": "2022-09",
      "end_date": "2026-06",
      "description": "NLP 模型研究，發表 NeurIPS 論文"
    }
  ],
  "skills": ["Python", "PyTorch", "Machine Learning", "SQL"],
  "publications": [
    {
      "title": "Attention is All You Need",
      "journal": "NeurIPS",
      "year": 2017
    }
  ]
}
```

---

## 14. Frontend Product Requirements (React + TypeScript + Tailwind)

### 14.1 Scope and Stack

The frontend application must be implemented with:

- React 18+
- TypeScript
- Tailwind CSS
- ECharts (for capability visualization)

UI page visual style is **TBD** (to be finalized later), but functional behavior and data contracts defined below are mandatory for the demo.

### 14.2 Primary User Flow

1. User creates/selects a job configuration.
2. User uploads CV files in bulk (PDF/DOC/DOCX).
3. System parses CVs, validates required identity fields, and computes ranking.
4. User views ranking list with status labels.
5. User clicks a candidate to view detailed analysis:
   - capability visualization (octagonal radar chart)
   - overall assessment summary
   - recommended interview questions

### 14.3 Bulk CV Upload Requirements

- Must support batch upload of **large candidate sets** (target: 200 files per batch for demo/staging validation).
- Supported file formats: `.pdf`, `.doc`, `.docx`.
- Upload result must be shown per file:
  - queued
  - processing
  - success
  - failed (with reason)
- CV parsing output must include candidate `name`.
  - If `name` is missing after parsing, mark candidate as `invalid_profile`.
  - `invalid_profile` entries are excluded from final ranking by default.
- Frontend must provide:
  - batch progress indicator
  - retry failed files action
  - downloadable failed-file/error list (CSV or JSON)

### 14.4 Ranking List and Status Requirements

Frontend ranking table must include:

- rank
- candidate name
- total score
- status
- key dimensions snapshot
- action entry to detail page

Candidate status labels:

- `shortlisted`
- `recommended`
- `not_recommended`
- `invalid_profile` (missing required fields such as name)
- `manual_review` (optional operator override)

Default sorting:

- Primary: `total_score` descending
- Secondary: deterministic tie-breaker (candidate_id or upload timestamp)

### 14.5 Candidate Detail Requirements

Each candidate detail page must contain:

1. Capability Visualization

- Use ECharts radar chart (8-axis/octagonal view).
- Default 8 dimensions for demo:
  - skill_match
  - experience_match
  - education_match
  - research_quality
  - communication_signal
  - leadership_signal
  - domain_relevance
  - project_impact
- If some dimensions are unavailable, display 0 with clear tooltip explanation.

2. Overall Assessment

- Show concise deterministic summary generated from scoring snapshot.
- Include:
  - strengths (top dimensions)
  - risks/gaps (low dimensions)
  - final tier and ranking rationale

3. Recommended Interview Questions

- Show structured, practical interview questions mapped to weak or critical dimensions.
- Each question includes:
  - target dimension
  - difficulty level (easy/medium/hard)
  - intent (what signal interviewer should validate)

### 14.6 Frontend Module Design (Future Reuse)

To support future expansion into a general evaluation/ranking platform, frontend modules must be separable:

- `upload-workbench` (generic file ingestion UI)
- `ranking-board` (generic ranked-list viewer with statuses)
- `candidate-insight` (radar + assessment + interview prompts)
- `config-studio` (rubric and weight configuration)

Each module should consume typed API contracts and avoid hard-coded CV-only assumptions in reusable components.

### 14.7 API Contract Additions (Frontend-Driven)

In addition to existing endpoints, frontend integration should support:

- Batch upload status query endpoint:
  - `GET /jobs/{job_id}/uploads/{batch_id}/status`
- Candidate status update endpoint (manual override):
  - `PUT /jobs/{job_id}/candidates/{candidate_id}/status`
- Candidate insight endpoint (aggregated for detail page):
  - `GET /jobs/{job_id}/results/{candidate_id}/insight`
  - Returns radar dimensions, overall assessment, interview questions, and status history

### 14.8 Frontend Non-Functional Requirements

- Large-list performance:
  - ranking table with virtualization/pagination
  - target smooth interaction for 500+ rows
- UX resilience:
  - clear empty/loading/error states for every page
  - retry and recover flows for transient failures
- Deterministic display:
  - same input dataset and config must render same ranking/order
- Accessibility baseline:
  - keyboard navigation for table and detail page
  - sufficient color contrast for status labels

### 14.9 Demo Acceptance Criteria (Frontend)

- User can upload mixed PDF/DOC/DOCX CV files in one batch.
- Candidates without parsed `name` are flagged as `invalid_profile`.
- Ranking page displays deterministic ordered results with statuses.
- Clicking a candidate opens detail page with:
  - 8-axis radar chart (ECharts)
  - overall assessment
  - recommended interview questions
- End-to-end flow works with backend APIs in Docker environment.

---

## 15. Canonical Data Dictionary (Single Source of Truth)

This section defines canonical enums and field names shared across frontend and backend. All APIs, DB mappings, and UI states must align with this dictionary.

### 15.1 Candidate Processing Status

Used for file-level ingestion/parsing pipeline visibility.

- `queued`
- `processing`
- `success`
- `failed`

### 15.2 Candidate Recommendation Status

Used for ranking and recruiter decision states.

- `shortlisted`
- `recommended`
- `not_recommended`
- `invalid_profile`
- `manual_review`

Rules:

- `invalid_profile` is automatically assigned when required identity fields are missing (at minimum: `name`).
- `manual_review` can be operator-assigned and takes precedence in UI status display.

### 15.3 Required Candidate Identity Fields

Minimum identity fields for rank eligibility:

- `name` (required)

Optional but recommended:

- `email`
- `phone`

### 15.4 Canonical Frontend/Backend Field Names

#### Upload Item

```json
{
  "batch_id": "string",
  "file_id": "string",
  "file_name": "string",
  "file_type": "pdf|doc|docx",
  "processing_status": "queued|processing|success|failed",
  "error_code": "string|null",
  "error_message": "string|null",
  "candidate_id": "uuid|null",
  "created_at": "datetime"
}
```

#### Candidate Profile (Normalized)

```json
{
  "candidate_id": "uuid",
  "name": "string|null",
  "email": "string|null",
  "phone": "string|null",
  "education": [],
  "experience": [],
  "skills": [],
  "publications": []
}
```

#### Ranking Row

```json
{
  "rank": "number",
  "candidate_id": "uuid",
  "candidate_name": "string",
  "total_score": "number",
  "recommendation_status": "shortlisted|recommended|not_recommended|invalid_profile|manual_review",
  "tier": "string",
  "dimension_scores": {
    "skill_match": "number",
    "experience_match": "number",
    "education_match": "number",
    "research_quality": "number",
    "communication_signal": "number",
    "leadership_signal": "number",
    "domain_relevance": "number",
    "project_impact": "number"
  }
}
```

#### Candidate Insight Response

```json
{
  "candidate_id": "uuid",
  "recommendation_status": "shortlisted|recommended|not_recommended|invalid_profile|manual_review",
  "overall_assessment": {
    "summary": "string",
    "strengths": ["string"],
    "risks": ["string"],
    "rationale": "string"
  },
  "radar_dimensions": {
    "skill_match": "number",
    "experience_match": "number",
    "education_match": "number",
    "research_quality": "number",
    "communication_signal": "number",
    "leadership_signal": "number",
    "domain_relevance": "number",
    "project_impact": "number"
  },
  "recommended_interview_questions": [
    {
      "question": "string",
      "target_dimension": "string",
      "difficulty": "easy|medium|hard",
      "intent": "string"
    }
  ]
}
```

### 15.5 Endpoint Naming Alignment

- Batch upload status:
  - `GET /jobs/{job_id}/uploads/{batch_id}/status`
- Candidate recommendation status update:
  - `PUT /jobs/{job_id}/candidates/{candidate_id}/status`
- Candidate insight:
  - `GET /jobs/{job_id}/results/{candidate_id}/insight`

### 15.6 Versioning Rule

If any enum value or field name in this section changes:

1. Update this section first.
2. Bump PRD document version.
3. Update backend schemas and frontend types in the same change set.

---

## 16. Appendix: Conventional Commit Messages

| Type       | Description             | Example                               |
| :--------- | :---------------------- | :------------------------------------ |
| `feat`     | New feature             | `feat: add CV upload endpoint`        |
| `fix`      | Bug fix                 | `fix: handle empty skills in matcher` |
| `docs`     | Documentation           | `docs: update API spec`               |
| `test`     | Test updates            | `test: add unit tests for parser`     |
| `refactor` | Code refactor           | `refactor: extract taxonomy loader`   |
| `perf`     | Performance improvement | `perf: optimize scoring loop`         |
| `chore`    | Maintenance             | `chore: update requirements.txt`      |

---

## 17. License

This project is licensed under the MIT License — see the `LICENSE` file for details.

---

**Document Version:** 1.2.0 | **Last Updated:** 2026-08-03
