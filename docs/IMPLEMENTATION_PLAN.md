# Agent CV Screening - Implementation Plan & Schedule

## 1) Objective

Deliver a production-ready, deterministic AI-assisted CV screening platform that supports:

- CV upload and structured extraction
- Department/job-specific scoring and ranking
- Report generation (candidate PDF and comparison Excel)
- Feedback analytics for continuous improvement

This plan is based on the current repository state and focuses on closing the gap from "working prototype" to "production-grade system."

## 2) Current Baseline (As-Is)

### Implemented Today

- Backend API using FastAPI with modular routes (`candidates`, `jobs`, `scoring`, `reports`, `feedback`)
- Deterministic LLM extraction pipeline (`temperature=0`, `seed=42`) with hash-based cache
- PostgreSQL-oriented data model via SQLAlchemy async models
- Deterministic rule-based scoring and ranking service (no LLM in scorer)
- Basic frontend (React + Vite + TypeScript + Tailwind) for batch PDF upload and parsed-result visualization
- Dockerized local environment with `db` + `backend`
- Initial unit tests for parser, scorer, reporter, feedback analytics

### Gaps to Production

- No Alembic migration workflow committed yet (schema managed via startup `create_all`)
- Frontend does not yet cover job config, scoring run, result views, reporting, and feedback flows
- No background task queue for long-running parse/score/report jobs
- Limited observability (structured logs/metrics/tracing not standardized)
- Security hardening and CI/CD pipeline are not fully defined
- Test coverage is partial (integration/e2e/performance tests missing)

## 3) Target Architecture (To-Be)

### Frontend

- Single-page app for end-to-end recruiter workflow:
  1. Create job and scoring config
  2. Upload candidate CVs (PDF/DOC/DOCX, high-volume batch)
  3. Trigger scoring
  4. View ranked list with statuses (`shortlisted`, `recommended`, `not_recommended`, `invalid_profile`)
  5. Open candidate detail with 8-dimension radar chart (ECharts)
  6. Review overall assessment and recommended interview questions
  7. Generate/download reports
  8. Submit recruiter feedback actions

### Backend

- Domain-oriented FastAPI services:
  - Parsing service (LLM + cache)
  - Skill matching and deterministic scoring
  - Reporting service (PDF/Excel)
  - Feedback analytics
- Batch-processing status service for high-volume upload visibility and retry
- API versioning and validation with Pydantic schemas
- Async database access via SQLAlchemy + asyncpg

### Database

- PostgreSQL 15+ as primary datastore
- JSONB for structured extraction/scoring snapshots
- Proper indexing and migration control through Alembic

### Deployment

- Containerized deployment using Docker and Docker Compose for dev/staging
- CI pipeline for lint/test/build/security scan
- Optional production target: Kubernetes or managed container platform

### Modularity Requirement for Future Reuse

- Design all core capabilities as separable modules with stable interfaces:
  - `ingestion/parsing` (document -> structured profile)
  - `matching/scoring` (profile + rubric -> scores/rank)
  - `reporting` (scores -> export artifacts)
  - `feedback/analytics` (user actions -> quality signals)
- Avoid CV-specific coupling inside the scoring engine; keep scorer input as generic normalized JSON.
- Keep scoring rules/config externalized in versioned config payloads so future domains can reuse the engine without code rewrite.
- Keep API boundaries clear so each module can later be extracted into an independent service/package.
- Enforce one canonical contract source for enums/field names:
  - Follow `docs/PRD-Overall-v1.0.md` section `Canonical Data Dictionary (Single Source of Truth)`.

## 4) Technology Stack

### Frontend Stack

- React 18
- TypeScript 5
- Vite 5
- Tailwind CSS 3
- Apache ECharts (radar chart for candidate capability visualization)

### Backend Stack

- Python 3.12 runtime (container)
- FastAPI
- Uvicorn
- Pydantic v2 / pydantic-settings
- SQLAlchemy 2 (async)
- OpenAI SDK + Tenacity retry
- Document extraction: `pdfplumber`, `pypdf`, DOC/DOCX parser adapter
- Reporting: `reportlab`, `openpyxl`

### Data & Infra Stack

- PostgreSQL 15
- Docker / Docker Compose
- Alembic (to be fully adopted)
- Pytest (+ async, coverage) for testing

## 5) Workstreams

## 5.1 Frontend Workstream

### Scope

- Build full recruiter UI workflow (beyond parser demo page)
- Add job configuration forms (weights, hard filters, tiers)
- Add high-volume CV upload workbench with per-file status tracking and retry
- Add ranking board with status labels and deterministic ordering
- Add candidate insight page with 8-axis radar chart (ECharts), overall assessment, and interview question recommendations
- Add feedback capture UI and analytics dashboards

### Deliverables

- `Job Management` pages
- `Bulk Upload Workbench` (PDF/DOC/DOCX + progress + failed file list)
- `Scoring Results` pages with pagination/filter/status chips
- `Candidate Detail` insight page (radar + assessment + interview questions)
- `Reports` trigger/download controls
- `Feedback` action controls + analytics view
- Shared API client layer and typed contracts

### Exit Criteria

- Recruiter can upload large CV batches, see ranking/status, and inspect candidate insights
- Frontend type-check and build pass in CI

## 5.2 Backend Workstream

### Scope

- Harden API contracts and validation
- Improve error handling and idempotency for upload/scoring/report generation
- Support DOC/DOCX parsing path with consistent normalized output schema
- Add candidate insight aggregation endpoint (radar dimensions + assessment + interview questions)
- Add observability and operational endpoints

### Deliverables

- Stable REST contracts for all recruiter workflows
- Upload batch status endpoint and retry semantics
- Candidate status override endpoint (`manual_review` compatible)
- Improved logging format and request correlation IDs
- Health/readiness endpoints with dependency checks

### Exit Criteria

- All core APIs stable and documented
- Batch upload/parse lifecycle is observable and recoverable by operators

## 5.3 Database Workstream

### Scope

- Formalize schema management with Alembic
- Add/verify indexes for expected query paths
- Prepare rollback-safe migration process

### Deliverables

- Initial migration and migration history policy
- Index review for:
  - `scoring_results(config_id, rank)`
  - `resumes(candidate_id, uploaded_at)`
  - JSONB GIN on extracted/scoring payloads where justified
- Seed data scripts for taxonomy and test fixtures

### Exit Criteria

- Database can be recreated/migrated deterministically in all environments
- Query performance meets target response profiles

## 5.4 DevOps & Deployment Workstream

### Scope

- Build reliable CI/CD pipeline and environment promotion path
- Secure runtime configuration and secrets handling
- Establish monitoring/alerting baseline

### Deliverables

- CI stages: lint -> type-check -> unit/integration tests -> image build -> security checks
- Tagged container release strategy
- Staging deployment profile and smoke tests
- Production runbook (rollback, backup, incident basics)

### Exit Criteria

- One-command deploy to staging
- Repeatable production deployment with rollback path

## 6) Implementation Schedule (4 Weeks, Rapid Demo)

Assumption: one full-time engineer building a fast, usable demo within one month.

### Demo Scope (Must Deliver)

- End-to-end path: upload -> parse -> score -> rank/status view -> candidate insight -> export
- Minimal job configuration UI and API
- Deterministic scoring and reproducible parsing behavior
- Basic Docker-based deployment and run instructions
- Support PDF/DOC/DOCX upload and enforce `name` presence for rank eligibility
- Keep frontend/backend field names and enum values identical to PRD canonical dictionary.

### Week 1 - Demo Foundation

- Freeze API payloads for upload, batch status, job config, scoring, results, candidate insight, and export
- Add Alembic baseline migration and stabilize schema lifecycle
- Stabilize backend happy path (parse/scoring/report) with DOC/DOCX adapter
- Create shared typed contract map from PRD canonical dictionary (backend schemas + frontend TS types)
- Define module interfaces to support future extraction:
  - Parser interface
  - Scoring engine interface
  - Reporting adapter interface
  - Insight/question adapter interface

### Week 2 - Usable Demo UI

- Build minimal frontend pages for:
  - Job setup
  - Candidate upload/list with per-file processing state
  - Score trigger
  - Ranked results + status labels
  - Candidate detail insight page (radar + assessment + interview questions)
- Implement one export flow (`.xlsx`) end to end
- Keep UI focused on demo clarity over final polish

### Week 3 - Reliability for Demo Day

- Add integration tests for upload, batch status, scoring, and results APIs
- Add one end-to-end happy-path test
- Improve error handling and operator messages
- Add minimal CI checks (`typecheck`, unit/integration tests, image build)
- Add contract-consistency checks for critical enums/statuses (`processing_status`, `recommendation_status`)

### Week 4 - Demo Readiness and Delivery

- Run user walkthroughs with representative JD/CV samples
- Fix high-impact defects only
- Prepare demo script and fallback data set
- Finalize deployment checklist and release demo environment

## 7) Milestones (Rapid Demo Track)

- M1 (End of Week 1): Stable backend flow + migration baseline + module interfaces
- M2 (End of Week 2): Complete demo UI for core workflow
- M3 (End of Week 3): Reliable demo baseline with tests and CI checks
- M4 (End of Week 4): Demo-ready release environment and walkthrough pack

## 8) Quality, Testing, and Acceptance

### Required Test Layers

- Unit tests for parser/matcher/scorer/reporter logic
- Integration tests for API + database behavior
- End-to-end tests for critical user journeys
- Basic performance tests for parse and scoring paths

### Acceptance Criteria

- Deterministic scoring guaranteed (no LLM in scoring path)
- CV extraction reproducibility validated through hash cache behavior
- Upload supports PDF/DOC/DOCX and marks missing-name profiles as `invalid_profile`
- Ranking page shows deterministic ordering and required status labels
- Candidate detail shows 8-axis radar chart, overall assessment, and interview question recommendations
- Frontend TS types and backend schemas match PRD canonical dictionary without naming drift
- Full workflow passes in staging with representative test data
- Build, test, and deployment pipeline succeeds without manual patching

## 9) Risks and Mitigations

- LLM output drift despite deterministic parameters

  - Mitigation: response schema validation + cache + regression golden set

- Long-running synchronous requests reduce API reliability

  - Mitigation: batch status endpoint + retry workflow; queue refactor can be post-demo

- JSONB-heavy queries degrade at scale

  - Mitigation: targeted indexes + periodic query profiling

- Environment/config mismatch across local/staging/prod

  - Mitigation: strict env templates, startup validation, release checklist

- DOC/DOCX parsing quality is inconsistent across templates
  - Mitigation: parser adapter abstraction + fallback extraction + explicit `invalid_profile` handling

## 10) Team Operating Model (Single Full-Time Engineer)

- One full-stack engineer owns backend, frontend, database migration, testing, and deployment.
- Stakeholders (PM/mentor/users) provide fast review cycles and weekly feedback, not implementation.

### Suggested Time Allocation

- 45% backend and scoring/report pipeline
- 30% frontend workflow completion
- 15% testing + CI
- 10% demo environment + documentation

## 10.1 Reusability Track for Future General Evaluation System

- Keep `scoring` domain model generic:
  - Inputs: normalized candidate profile + rubric/config
  - Outputs: dimension scores + total score + ranking metadata
- Extract CV-specific parsing rules behind a parser adapter, not inside scorer logic.
- Keep reporting templates pluggable so future domains can replace output formats without touching scoring.
- Version configuration schema from day one to support future rubric evolution across domains.
- Define clear contracts so modules can later be moved into standalone services or libraries.

## 11) Definition of Done

A phase is done when:

- Feature scope is implemented
- Tests are added and passing in CI
- Documentation is updated
- Operational considerations (logging, errors, rollback notes) are included

---

Last updated: 2026-08-03
