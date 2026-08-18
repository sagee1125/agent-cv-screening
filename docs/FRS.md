# Functional Requirements Specification (FRS)

**Project:** Agent-CV-Screening  
**Version:** 1.0.0  
**Status:** Draft  
**Date:** 2026-08-03  
**Reference Documents:** `docs/PRD-Overall-v1.0.md`, `docs/IMPLEMENTATION_PLAN.md`

---

## 1. Purpose

This document defines detailed functional requirements for the Agent-CV-Screening system. It translates product goals into implementable and testable system behavior for frontend, backend, and data workflows.

---

## 2. Scope

### 2.1 In Scope (Rapid Demo)
- Job configuration creation and update
- High-volume CV upload (`pdf`, `doc`, `docx`)
- Deterministic CV parsing with required identity validation (`name`)
- Deterministic scoring and ranking
- Candidate status management and ranking board
- Candidate insight view:
  - 8-dimension radar chart
  - overall assessment summary
  - recommended interview questions
- Report export (at minimum comparison `.xlsx`)
- Basic feedback action logging

### 2.2 Out of Scope (Current Iteration)
- Full enterprise auth/SSO
- Advanced async orchestration across multiple workers
- Multi-region deployment
- Advanced BI dashboards

---

## 3. Actors and User Roles

- **Recruiter/Reviewer (Primary User):**
  - Creates jobs/config
  - Uploads CVs
  - Runs scoring
  - Reviews ranking and candidate details
  - Logs review actions
- **System Operator (Secondary User):**
  - Monitors upload/processing status
  - Retries failed batches/files
  - Validates demo environment readiness

---

## 4. Functional Modules

1. Job & Rubric Management
2. CV Ingestion & Parsing
3. Scoring & Ranking
4. Candidate Insight
5. Reporting
6. Feedback Logging
7. Operational Status & Retry

---

## 5. Canonical Data Contract Dependency

All functional behavior in this document must follow canonical enums and field names defined in:
- `docs/PRD-Overall-v1.0.md` -> Section 5 (Canonical Data Dictionary)

Critical enums:
- `processing_status`: `queued | processing | success | failed`
- `recommendation_status`: `shortlisted | recommended | not_recommended | invalid_profile | manual_review`

---

## 6. Detailed Functional Requirements

## 6.1 Job & Rubric Management

### FR-001 Create Job
- **Description:** User can create a job with department, position, JD text, and scoring config.
- **Input:** `department_name`, `position_name`, `jd_text`, `config`, `created_by`
- **Output:** `job_id`, `config_version`, persisted job config
- **Acceptance Criteria:**
  - Job is persisted successfully.
  - Returned payload contains version metadata and `job_id`.

### FR-002 Update Job Config
- **Description:** User can update a job scoring config.
- **Input:** `job_id`, new `config`
- **Output:** incremented `config_version`, `updated_at`
- **Acceptance Criteria:**
  - Version increments deterministically.
  - New scoring runs use latest active config.

---

## 6.2 CV Ingestion & Parsing

### FR-003 Batch CV Upload
- **Description:** User can upload CVs in batch.
- **Supported Types:** `.pdf`, `.doc`, `.docx`
- **Scale Target:** 200 files per batch (demo/staging target)
- **Acceptance Criteria:**
  - System accepts mixed file types in one batch.
  - Each file receives `processing_status`.

### FR-004 File-Level Processing Status
- **Description:** System tracks processing state per file.
- **States:** `queued`, `processing`, `success`, `failed`
- **Acceptance Criteria:**
  - Frontend can query batch/file status.
  - Failed files include `error_code` and/or `error_message`.

### FR-005 Required Identity Validation
- **Description:** Parsed candidate profile must include `name` for ranking eligibility.
- **Rule:** missing/empty `name` => `recommendation_status=invalid_profile`
- **Acceptance Criteria:**
  - Invalid profiles are clearly flagged.
  - Invalid profiles are excluded from default ranking list.

### FR-006 Deterministic Parsing
- **Description:** LLM parsing must be deterministic and reproducible.
- **Rule:** fixed deterministic settings + hash-based cache
- **Acceptance Criteria:**
  - Re-processing same file with same config yields consistent structured output.

---

## 6.3 Scoring & Ranking

### FR-007 Trigger Scoring
- **Description:** User can trigger scoring for all eligible candidates under a job.
- **Acceptance Criteria:**
  - System returns scoring start response with queued count.
  - Candidates with `invalid_profile` are not ranked by default.

### FR-008 Deterministic Ranking
- **Description:** System computes and returns deterministic ranking.
- **Sort Rule:** primary `total_score DESC`, secondary deterministic tie-breaker
- **Acceptance Criteria:**
  - Same input dataset + same config => same ranking order.

### FR-009 Recommendation Status Assignment
- **Description:** System assigns status labels for ranking and review.
- **Statuses:** `shortlisted`, `recommended`, `not_recommended`, `invalid_profile`, `manual_review`
- **Acceptance Criteria:**
  - Status is available on ranking rows.
  - `manual_review` can override display status when set by operator.

---

## 6.4 Candidate Insight

### FR-010 Candidate Insight View
- **Description:** User can open a candidate detail insight page from ranking list.
- **Acceptance Criteria:**
  - Insight payload is returned through a dedicated endpoint.
  - UI can render insights without additional data joins.

### FR-011 Radar Chart Visualization
- **Description:** System provides 8-dimension capability data for ECharts radar chart.
- **Dimensions:**
  - `skill_match`
  - `experience_match`
  - `education_match`
  - `research_quality`
  - `communication_signal`
  - `leadership_signal`
  - `domain_relevance`
  - `project_impact`
- **Acceptance Criteria:**
  - All dimensions are present (default to `0` if unavailable).
  - Values are numeric and normalized for chart display.

### FR-012 Overall Assessment
- **Description:** System returns concise overall assessment.
- **Must Include:** strengths, risks, rationale, summary
- **Acceptance Criteria:**
  - Assessment references deterministic scoring snapshot.
  - Output is consistently structured for frontend display.

### FR-013 Recommended Interview Questions
- **Description:** System returns interview question recommendations per candidate.
- **Each Item Must Include:** `question`, `target_dimension`, `difficulty`, `intent`
- **Acceptance Criteria:**
  - Questions map to weak or critical dimensions.
  - Difficulty is in enum: `easy|medium|hard`.

---

## 6.5 Reporting

### FR-014 Comparison Export
- **Description:** User can generate and download comparison report.
- **Minimum Format:** `.xlsx`
- **Acceptance Criteria:**
  - File is generated for ranked candidates.
  - Download URL is returned and accessible.

### FR-015 Candidate Report (Optional in Demo)
- **Description:** Candidate one-page PDF can be generated for selected candidate.
- **Acceptance Criteria:**
  - If enabled in scope, report includes key dimensions and recommendation summary.

---

## 6.6 Feedback Logging

### FR-016 Log Reviewer Action
- **Description:** User action (view/invite/reject/etc.) can be recorded.
- **Input:** `scoring_result_id`, `action`, `context`, `user_id`
- **Acceptance Criteria:**
  - Log record persists with timestamp.
  - Action logs can be queried for later analytics.

---

## 6.7 Operational Status & Retry

### FR-017 Batch Status Query
- **Description:** Operator can query batch processing progress.
- **Acceptance Criteria:**
  - Response includes aggregate and per-file status.

### FR-018 Retry Failed Files
- **Description:** Operator can retry failed files within a batch.
- **Acceptance Criteria:**
  - Retried files re-enter status lifecycle (`queued -> processing -> success/failed`).
  - Retry results are auditable.

---

## 7. Frontend Functional Requirements

### FR-019 Upload Workbench UI
- Show file queue, per-file status, error reason, retry action.
- Show batch progress summary.

### FR-020 Ranking Board UI
- Show rank, candidate, score, status, and quick action to detail.
- Support pagination or virtualization for large lists.

### FR-021 Candidate Insight UI
- Render radar chart via ECharts.
- Render overall assessment block.
- Render recommended interview question list.

### FR-022 Status Styling & Filtering
- Show color-coded status chips.
- Allow filtering by status and search by candidate name.

---

## 8. Backend Functional Requirements

### FR-023 API Versioned Responses
- All API responses include `version`.

### FR-024 Schema Validation
- Request/response payloads validated through typed schemas.

### FR-025 Insight Aggregation Endpoint
- Provide unified payload for candidate detail page:
  - radar dimensions
  - recommendation status
  - overall assessment
  - interview questions

### FR-026 Contract Consistency
- Backend field names and enums must match PRD canonical dictionary exactly.

---

## 9. Non-Functional Constraints Affecting Functional Behavior

- Deterministic scoring path must not call LLM.
- Same input + same config must produce stable ordering.
- Upload/retry flows must be recoverable after transient errors.
- Frontend should remain usable for 500+ ranked rows.

---

## 10. Traceability Matrix (High-Level)

| Requirement Group | API/Service Area | Frontend Area |
| :--- | :--- | :--- |
| FR-001 ~ FR-002 | jobs routes, config persistence | Job setup page |
| FR-003 ~ FR-006 | candidates upload/parser/cache | Upload workbench |
| FR-007 ~ FR-009 | scoring service/results routes | Ranking board |
| FR-010 ~ FR-013 | insight aggregation/scoring snapshot | Candidate insight page |
| FR-014 ~ FR-015 | reports routes/reporter service | Export controls |
| FR-016 | feedback route/log table | Detail/ranking actions |
| FR-017 ~ FR-018 | batch status + retry endpoints | Upload status panel |
| FR-019 ~ FR-022 | n/a | frontend feature modules |
| FR-023 ~ FR-026 | schemas/routes/contracts | typed API client |

---

## 11. Acceptance for Demo Completion

Demo is considered functionally complete when:
- End-to-end flow works: upload -> parse -> rank -> candidate insight -> export
- Mixed format upload works: PDF/DOC/DOCX
- Missing `name` candidates are marked `invalid_profile`
- Ranking/status display is deterministic and consistent
- Candidate detail includes radar, assessment, and interview questions
- API/Frontend contracts match canonical dictionary

---

## 12. Change Control

Any change to enums, field names, or required data structures must:
1. Update `docs/PRD-Overall-v1.0.md` canonical dictionary first.
2. Update this FRS accordingly.
3. Update backend schemas and frontend types in the same change set.

---

**Document Owner:** Project Team  
**Last Updated:** 2026-08-03
