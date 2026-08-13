# Product Requirements Document (PRD)

**Feature Name:** **JD Management, Parsing, and Candidate Matching MVP**  
**Version:** v1.0 (MVP)  
**Status:** Draft  
**Product Manager:** HR Product Team  
**Target Users:** Talent Acquisition Specialists, Senior Recruiters, Recruiting Operations Leads

---

## 1. Executive Summary

The HR recruiting support system needs to reduce manual screening effort by connecting three operational steps into one workflow: creating and managing Job Posts, parsing JD text into structured criteria, and ranking candidates based on JD-CV fit. Today, CV parsing is already available as a separate agent that stores structured candidate profiles. The missing capability is a unified front-end management experience and the logic layer that transforms JD requirements into explainable and adjustable ranking outcomes.

This MVP delivers four core modules: (1) Job Post Management container, (2) JD Parser module with editable structured output, (3) Candidate Management linked to existing CV parser data, and (4) Matching and Ranking engine with score explainability and fit clustering. The MVP objective is to help HR teams answer two operational questions quickly: "Who should we contact first?" and "Who can we safely reject now?"

CRITICAL quality principle for this MVP: **Traceable and explainable matching decisions**. Every key output must be inspectable by HR users, including JD parsing provenance, score breakdown components, and candidate fit clusters. This is a non-negotiable trust requirement for production adoption.

### Product Vision

Enable HR teams to manage a complete JD-to-shortlist loop in one place, from opening a role to identifying high-fit candidates with transparent, adjustable, and fast decision support.

### Success Definition (MVP)

Within one role intake cycle, HR can publish a Job Post, parse and tune JD requirements, import candidates, and obtain an updated ranked list without manual spreadsheet scoring.

### User Personas

1. **Persona A: High-Volume Recruiter (Primary)**

   - Handles 10-20 concurrent openings.
   - Needs fast elimination decisions and confidence in automation.
   - Pain points: repetitive triage, inconsistent screening criteria, slow turnaround.
   - Success criteria: can filter Low Fit candidates in one click and prioritize top candidates in under 10 minutes per role.

2. **Persona B: Specialist Recruiter (Secondary)**

   - Handles niche technical roles with strict requirements.
   - Needs fine-grained control over must-have vs preferred skills and ordering/weight.
   - Pain points: difficult to calibrate JD strictness; hard to explain candidate ranking to hiring managers.
   - Success criteria: can inspect score provenance, adjust weights, and re-rank candidates with clear rationale.

3. **Persona C: Recruiting Operations Lead (Secondary)**
   - Monitors recruiting funnel quality across sourcing channels.
   - Needs cross-channel comparison data and process consistency.
   - Pain points: limited visibility into source quality and parser failure handling.
   - Success criteria: can compare candidate volume and average fit score by channel for each role.

---

## 2. MVP Scope (P0 + P1)

### P0 — Core Requirements (Launch Blockers)

| ID    | Feature                      | Description                                                                                                             |
| ----- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| F0.1  | Module 0 Routing & Container | `/` and `/home` resolve to the same Job Post management page and load role list successfully.                           |
| F0.2  | Job Post CRUD                | Create, edit, status update (Draft/In Progress/Closed), and archive behavior for Job Posts.                             |
| F0.3  | Job Post Copy                | Copy an existing Job Post with full JD text + parsed conditions using deep clone, excluding candidate associations.     |
| F0.4  | Job Post List View           | List cards/table show Job Title, JD summary (first 200 chars), start date, headcount, and status.                       |
| F0.5  | JD Parse Trigger             | HR can paste JD text in Job Post detail and trigger JD parser agent to extract structured requirements.                 |
| F0.6  | JD Structured Output         | Must Skill, Preferred Skill, Language, Education, and Visa requirements are saved in fixed JSON structure.              |
| F0.7  | JD Clarification Prompts     | If parser detects missing critical constraints (for example visa or salary), UI asks closed-option follow-up questions. |
| F0.8  | JD Explainability            | Each parsed skill has source sentence provenance visible in UI.                                                         |
| F0.9  | JD Manual Editing            | HR can add/edit/remove skills and drag-drop reorder skills; all edits instantly sync to JSON state.                     |
| F0.10 | Candidate Linking            | Job Post detail shows candidates associated with that role from existing CV parser database.                            |
| F0.11 | Batch CV Import              | Upload multiple PDF/Word files, invoke CV parser agent, persist candidates, and auto-link to active Job Post.           |
| F0.12 | Import Failure Handling      | Encrypted/scanned/unsupported files are marked as failed with actionable retry/delete options.                          |
| F0.13 | Matching Engine              | Compute candidate fit score from Must/Preferred constraints and weights; default ranking is descending by fit score.    |
| F0.14 | Score Breakdown UI           | Candidate-level score decomposition is visible (for example skill +30, experience +15).                                 |
| F0.15 | Async Recalculation          | Weight changes trigger background recalculation job and refresh ranking without blocking user interaction.              |
| F0.16 | Fit Clustering               | Automatically label candidates as High Fit / Medium Fit / Low Fit with one-click filters.                               |
| F0.17 | Channel Tracking             | CV import requires source channel tag (104/LinkedIn/Referral/Other) and stores it for analytics.                        |
| F0.18 | Channel Dashboard            | Job Post detail displays per-channel candidate count and average fit score.                                             |
| F0.19 | JD Diagnostic Tool           | Show Must skill satisfaction rates and suggest relaxing constraints when any Must item is below 20% satisfaction.       |
| F0.20 | Last-Write-Wins Save Rule    | Concurrent edits follow MVP rule: latest save overwrites previous changes, with visible "last updated" metadata.        |

### P1 — Important Enhancements

| ID   | Feature                   | Description                                                                         |
| ---- | ------------------------- | ----------------------------------------------------------------------------------- |
| F1.1 | JD Quality Hints          | Suggest clearer JD phrasing when parser confidence is low for key requirements.     |
| F1.2 | Fit Threshold Tuning      | Admin-adjustable percentile thresholds for High/Medium/Low clusters by role family. |
| F1.3 | Candidate Comparison View | Side-by-side comparison of top candidates across selected dimensions.               |
| F1.4 | Recalculation Job Monitor | Lightweight status panel for background scoring jobs (queued/running/done/failed).  |
| F1.5 | Export Shortlist          | Export filtered candidate list with score components to CSV/XLSX.                   |
| F1.6 | Additional Channels       | Configurable source channel taxonomy beyond default preset values.                  |

### Module Priority Summary (0-3)

| Module   | Name                                     | Priority | Rationale                                             |
| -------- | ---------------------------------------- | -------- | ----------------------------------------------------- |
| Module 0 | Job Post Management (Container Layer)    | P0       | Entry point for all downstream flows.                 |
| Module 1 | JD Parsing Module                        | P0       | Required to generate structured criteria for scoring. |
| Module 2 | Candidate Management (Association Layer) | P0       | Required candidate ingestion and role linkage.        |
| Module 3 | Matching & Ranking Engine                | P0       | Core product value delivery.                          |

### Acceptance Criteria by Module

#### Module 0: Job Post Management

- **AC0.1** Accessing `/` and `/home` renders identical page component and data state.
- **AC0.2** Job Post list includes title, 200-char JD summary, start time, headcount, status.
- **AC0.3** "Create from existing" deep-copies JD text and parsed JSON but copies zero candidate links.
- **AC0.4** Status transition to Closed/Archived hides role from default active view and preserves history.
- **AC0.5** Editing base info persists successfully and is visible after reload.

#### Module 1: JD Parsing

- **AC1.1** JD paste + parse action returns structured fields: Must, Preferred, Language, Education, Visa.
- **AC1.2** Missing critical items produce closed-option follow-up prompts (no free-text chatbot dependency).
- **AC1.3** Must skills render as red tags; Preferred skills render as blue tags.
- **AC1.4** Clicking provenance on any skill reveals mapped JD sentence snippet.
- **AC1.5** Manual add/edit/delete/reorder updates are reflected in persisted JSON immediately.

#### Module 2: Candidate Management

- **AC2.1** Job Post detail lists linked candidates with name, current company, total years, education.
- **AC2.2** Multi-file upload supports PDF/Word and initiates CV parser job per file.
- **AC2.3** Successful parse records are linked to active Job Post automatically.
- **AC2.4** Failed parse records include explicit error reason and retry/delete action.
- **AC2.5** Import flow requires source channel selection and stores channel for each candidate-role link.

#### Module 3: Matching & Ranking

- **AC3.1** Initial candidate list default sort is descending by total fit score.
- **AC3.2** Score breakdown displays at least skill, experience, education/language components where applicable.
- **AC3.3** Weight changes enqueue async recalculation; UI remains responsive and list updates on completion.
- **AC3.4** Candidates are grouped as High/Medium/Low Fit and can be filtered in one click.
- **AC3.5** JD diagnostic displays Must skill satisfaction percentages and flags any item below 20%.

---

## 3. Out of Scope

- Full collaborative editing lock model (operational transform / CRDT / real-time merge conflict resolution).
- Offer management, interview scheduling, ATS calendar integration, and onboarding workflow.
- ML model retraining pipeline for JD parser or CV parser in MVP timeline.
- Multi-language JD parsing beyond primary launch language set.
- External benchmarking against labor market salary intelligence tools.
- Automatic rejection email dispatch and communication orchestration.
- Cross-job global talent pool recommendations (candidate reuse ranking across roles).
- Explainability at token-level model attention visualization.
- Offline document OCR enhancement services beyond baseline parser behavior.

---

## 4. Technical Workflow

### 4.1 End-to-End User Flow (Text-Based)

1. HR enters `/` or `/home` and sees Job Post list.
2. HR creates a new Job Post (blank or copied from existing role).
3. HR opens Job Post detail and pastes JD content.
4. JD parser agent extracts structured constraints and returns normalized JSON + provenance.
5. If required fields are missing, system displays closed-option clarification prompts.
6. HR reviews tags, edits constraints, and drag-reorders skills (weight order).
7. HR uploads candidate files in batch and selects source channels.
8. CV parser agent processes each file; successes are linked to role, failures are flagged.
9. Matching engine computes fit scores using JD constraints + weights + candidate structured CV.
10. UI shows ranked list, score breakdown, fit clusters, and channel dashboard.
11. HR adjusts weights; system triggers async re-score and updates ranking on completion.
12. HR filters Low Fit for elimination and focuses on High/Medium Fit shortlisting.

### 4.2 Backend Processing Workflow

1. Job Post API stores base metadata and version timestamp.
2. JD parsing service stores raw JD, parsed JSON, provenance mapping, and parse confidence.
3. Candidate import service creates ingestion jobs and parser task records.
4. Candidate-role association table persists linkage with source channel and import status.
5. Matching service computes component scores and persists versioned score records.
6. Recalculation service enqueues async jobs when JD weights/constraints change.
7. Diagnostic service computes Must skill satisfaction ratio from linked candidate set.

### 4.3 Failure and Fallback Workflow

1. Parser timeout or failure returns structured error state (`error_code`, `retryable`).
2. Upload failure row remains visible with retry/delete options and audit metadata.
3. Scoring recalculation failure falls back to last successful score set and raises warning.
4. Missing normalization mapping triggers default alias matching with low-confidence flag.

---

## 5. Output Contract / Fixed JSON Schema

### 5.1 JD Structured Output Contract

```json
{
  "job_post_id": "uuid",
  "jd_raw_text": "string",
  "parse_status": "success|partial|error",
  "requirements": {
    "must_skills": [
      {
        "skill_id": "string",
        "display_name": "string",
        "canonical_skill": "string",
        "priority_order": 1,
        "weight": 1.0,
        "provenance": {
          "source_sentence": "string",
          "source_char_start": 0,
          "source_char_end": 42,
          "confidence": 0.0
        }
      }
    ],
    "preferred_skills": [
      {
        "skill_id": "string",
        "display_name": "string",
        "canonical_skill": "string",
        "priority_order": 1,
        "weight": 0.6,
        "provenance": {
          "source_sentence": "string",
          "source_char_start": 0,
          "source_char_end": 42,
          "confidence": 0.0
        }
      }
    ],
    "language_requirements": [
      {
        "language": "English",
        "level": "basic|business|fluent|native",
        "is_mandatory": true,
        "provenance": "string"
      }
    ],
    "education_requirement": {
      "minimum_degree": "none|bachelor|master|phd",
      "field_of_study": "string|null",
      "is_mandatory": false,
      "provenance": "string|null"
    },
    "visa_requirement": {
      "requirement_type": "none|required|preferred|unknown",
      "target_region": "string|null",
      "provenance": "string|null"
    }
  },
  "clarification_prompts": [
    {
      "prompt_id": "uuid",
      "question_type": "visa|salary|location|work_mode",
      "question_text": "string",
      "options": [
        {
          "value": "string",
          "label": "string"
        }
      ],
      "selected_value": "string|null"
    }
  ],
  "metadata": {
    "parser_agent_version": "string",
    "taxonomy_version": "string",
    "updated_by_user_id": "uuid",
    "last_updated_at": "ISO-8601",
    "save_strategy": "last_write_wins",
    "error_message": "string|null"
  }
}
```

### 5.2 Candidate-Job Match Result Contract

```json
{
  "job_post_id": "uuid",
  "candidate_id": "uuid",
  "score_version": 3,
  "total_score": 78.5,
  "fit_band": "high|medium|low",
  "score_breakdown": {
    "must_skill_score": 35.0,
    "preferred_skill_score": 18.0,
    "experience_score": 15.0,
    "education_score": 5.0,
    "language_score": 5.5
  },
  "diagnostic_flags": ["missing_must_skill:Kubernetes"],
  "computed_at": "ISO-8601",
  "compute_status": "success|fallback|error",
  "metadata": {
    "recalc_job_id": "uuid|null",
    "taxonomy_version": "string",
    "error_message": "string|null"
  }
}
```

### 5.3 Database Schema Recommendations (MVP)

#### Table A: `job_posts`

| Column                  | Type         | Constraints          | Notes                               |
| ----------------------- | ------------ | -------------------- | ----------------------------------- |
| id                      | UUID         | PK                   | Job Post identifier                 |
| title                   | VARCHAR(255) | NOT NULL             | Job title                           |
| jd_raw_text             | TEXT         | NULL                 | Source JD text                      |
| jd_summary_200          | VARCHAR(220) | NULL                 | Cached list summary                 |
| head_count              | INT          | NOT NULL DEFAULT 1   | Open positions                      |
| recruiting_start_at     | TIMESTAMP    | NOT NULL             | Hiring start                        |
| status                  | ENUM         | NOT NULL             | draft/in_progress/closed/archived   |
| cloned_from_job_post_id | UUID         | NULL FK job_posts.id | Copy traceability                   |
| jd_structured_json      | JSONB        | NULL                 | Parsed + edited requirement payload |
| jd_schema_version       | VARCHAR(32)  | NOT NULL             | Contract version                    |
| created_by              | UUID         | NOT NULL             | Audit                               |
| created_at              | TIMESTAMP    | NOT NULL             | Audit                               |
| updated_at              | TIMESTAMP    | NOT NULL             | Audit                               |

#### Table B: `candidate_job_links`

| Column                            | Type         | Constraints               | Notes                       |
| --------------------------------- | ------------ | ------------------------- | --------------------------- |
| id                                | UUID         | PK                        | Link record identifier      |
| job_post_id                       | UUID         | NOT NULL FK job_posts.id  | Role association            |
| candidate_id                      | UUID         | NOT NULL FK candidates.id | Candidate association       |
| source_channel                    | ENUM         | NOT NULL                  | 104/linkedin/referral/other |
| import_status                     | ENUM         | NOT NULL                  | pending/success/failed      |
| import_error_code                 | VARCHAR(64)  | NULL                      | Machine-readable error      |
| import_error_message              | TEXT         | NULL                      | User-facing error           |
| cv_file_name                      | VARCHAR(255) | NULL                      | Uploaded document           |
| cv_file_type                      | ENUM         | NULL                      | pdf/doc/docx                |
| retry_count                       | INT          | NOT NULL DEFAULT 0        | Retry tracking              |
| linked_at                         | TIMESTAMP    | NOT NULL                  | Association timestamp       |
| UNIQUE(job_post_id, candidate_id) | -            | Unique                    | Prevent duplicate links     |

#### Table C: `candidate_match_scores`

| Column                               | Type         | Constraints               | Notes                       |
| ------------------------------------ | ------------ | ------------------------- | --------------------------- |
| id                                   | UUID         | PK                        | Score record identifier     |
| job_post_id                          | UUID         | NOT NULL FK job_posts.id  | Role context                |
| candidate_id                         | UUID         | NOT NULL FK candidates.id | Candidate context           |
| score_version                        | INT          | NOT NULL                  | Increment per recalculation |
| total_score                          | DECIMAL(5,2) | NOT NULL                  | 0-100 score                 |
| fit_band                             | ENUM         | NOT NULL                  | high/medium/low             |
| breakdown_json                       | JSONB        | NOT NULL                  | Component scores            |
| diagnostic_json                      | JSONB        | NULL                      | Missing skills / notes      |
| compute_status                       | ENUM         | NOT NULL                  | success/fallback/error      |
| computed_at                          | TIMESTAMP    | NOT NULL                  | Computation time            |
| recalc_job_id                        | UUID         | NULL                      | Async job trace             |
| INDEX(job_post_id, total_score DESC) | -            | Index                     | Fast rank query             |

---

## 6. Non-Functional Requirements

| Category       | Requirement                                                                                                       |
| -------------- | ----------------------------------------------------------------------------------------------------------------- |
| Performance    | P95 Job Post list API < 800 ms for up to 500 roles; ranked candidate query P95 < 1.2 s for 500 candidates.        |
| Scalability    | Recalculation jobs support at least 1,000 candidate-score computations per role via async workers.                |
| Responsiveness | UI interaction remains non-blocking during background recalculation; status updates shown within 3 seconds.       |
| Reliability    | CV import and scoring jobs are retryable for transient failures; at-least-once processing with idempotent writes. |
| Determinism    | Same JD JSON + same candidate snapshot + same taxonomy version must yield reproducible score output.              |
| Traceability   | Every parsed requirement and score result must store provenance, version metadata, and timestamps.                |
| Explainability | HR can inspect source sentence for parsed skills and score breakdown for each candidate.                          |
| Security       | Role-based access for HR users; uploaded files and PII encrypted at rest and in transit (TLS 1.2+).               |
| Privacy        | Retain candidate files per retention policy; support deletion workflow for compliance requests.                   |
| Compatibility  | Support latest two major versions of Chrome and Edge in MVP.                                                      |
| Availability   | Core APIs and ranking view target 99.5% monthly availability in MVP environment.                                  |
| Observability  | Structured logs and metrics for parser success rate, import failures, recalculation latency, and API errors.      |

---

## 7. Risks and Mitigations

| Risk                                                                                          | Impact | Mitigation                                                                                                                                                                                                                 |
| --------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1 Skill naming mismatch between CV parser and JD parser (for example "Python" vs "python3"). | High   | Build and version a canonical Skill Taxonomy service with alias mapping; normalize both parser outputs pre-scoring; log unknown skills for weekly taxonomy updates; fallback to fuzzy alias matching with confidence flag. |
| R2 Large candidate volume causes slow recalculation after weight changes.                     | High   | Use async queue + worker pool; incremental recomputation per affected role only; cache candidate normalized vectors; optimistic UI refresh with "last computed" timestamp; enforce job timeout + retry policy.             |
| R3 Job Post copy incorrectly duplicates candidate associations.                               | Medium | Implement deep clone at Job Post + JD JSON level only; explicit exclusion list for association tables; add integration test verifying zero copied candidate links.                                                         |
| R4 Concurrent edits from multiple HR users overwrite each other unexpectedly.                 | Medium | MVP policy is last-write-wins with visible "last updated by/time"; maintain full edit history snapshot for rollback support by admin; include conflict warning toast on stale data detection.                              |
| R5 CV parse failures reduce trust and throughput.                                             | High   | Standardize import error taxonomy (encrypted PDF, scanned image, unsupported format, parser timeout); show per-file recovery actions (retry/delete/re-upload guideline); batch retry endpoint with capped retry count.     |
| Parser vendor/model drift impacts output consistency.                                         | Medium | Pin parser agent version per production release; include schema contract validation gate; alert when parse confidence distribution shifts beyond threshold.                                                                |
| Data quality issues in historical candidate profiles skew scores.                             | Medium | Track candidate profile completeness score; apply missing-data penalty logic transparently; surface low-confidence badge in UI.                                                                                            |
| Async job backlog under peak upload periods.                                                  | Medium | Autoscale worker replicas by queue depth; priority queue for active Job Posts; circuit breaker for non-critical recalculations.                                                                                            |

### Failure-Mode Requirements (Non-negotiable)

- If scoring fails, system must continue showing last successful ranking with explicit stale-data indicator.
- If JD parse is partial, HR must still be able to manually complete required fields and proceed.
- If import fails for subset of files, successful files must continue downstream processing independently.

---

## 8. Boundary / Separation Requirements

- **CV Parser Ownership Boundary (CRITICAL):** Existing CV parser extraction logic and output schema ownership remains in CV Parser service; this PRD does not redefine CV extraction fields.
- **JD Parser Ownership Boundary (CRITICAL):** JD parser service owns JD requirement extraction, provenance mapping, and clarification prompt generation.
- **Matching Engine Boundary:** Matching service consumes normalized outputs from CV parser and JD parser, but must not mutate source parser records.
- **Taxonomy Boundary:** Canonical skill taxonomy is shared infrastructure; parser teams publish aliases but matching engine consumes versioned resolved identifiers only.
- **UI/API Boundary:** Front-end can edit JD structured requirements through defined API contracts; direct database edits are prohibited.
- **Copy Behavior Boundary:** Job Post duplication copies role metadata and JD structured payload only; candidate associations and score history are never copied.
- **Concurrency Boundary:** MVP applies last-write-wins behavior only; no collaborative lock mechanics included before post-MVP.

---

## 9. Success Metrics (KPIs)

| Metric                                          | Target                                                                                                          |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Time to first ranked shortlist per new Job Post | <= 15 minutes from JD paste to scored candidate list (P50).                                                     |
| Manual screening reduction                      | >= 40% reduction in initial CV triage time compared with baseline process in first 60 days.                     |
| JD parse completeness                           | >= 90% of parses produce all required fields after clarification step (Must/Preferred/Language/Education/Visa). |
| Score recalculation latency                     | P95 <= 60 seconds for roles with up to 500 linked candidates.                                                   |
| Import failure recovery rate                    | >= 80% of failed files are resolved (retry or re-upload success) within 24 hours.                               |
| Fit clustering utility                          | >= 70% of HR sessions use at least one High/Medium/Low filter action.                                           |
| Channel analytics adoption                      | >= 60% of active Job Posts have source channel tags on >= 90% candidate links.                                  |
| JD diagnostic impact                            | For roles with Must-skill <20% alert, >= 50% show JD adjustment within 7 days.                                  |
| Explainability usage                            | >= 50% of shortlist sessions open score breakdown or provenance at least once.                                  |
| Data freshness                                  | 99% of displayed ranking results are from latest successful score version for that role.                        |

---

## 10. Future Considerations (Post-MVP)

- Adaptive weighting recommendations based on historical hire outcomes.
- Team-level templates for role families (for example backend engineer, product designer).
- Advanced collaboration model with mergeable drafts and conflict resolution.
- Auto-suggestion of alternative must skills when diagnostic satisfaction is persistently low.
- Multi-language JD parsing and cross-lingual skill normalization.
- Hiring manager portal for shared review and feedback loops.
- Integrations with ATS platforms for interview pipeline synchronization.
- Model-assisted candidate outreach prioritization and messaging workflow.

---

## 11. PRD Owner Sign-off

**PRD Owner Sign-off:** ******\*\*******\_\_\_\_******\*\******* **Date:** **\*\***\_\_\_\_**\*\***  
**Engineering Lead Sign-off:** ****\*\*\*\*****\_\_****\*\*\*\***** **Date:** **\*\***\_\_\_\_**\*\***  
**Data/AI Lead Sign-off:** ******\*\*******\_******\*\******* **Date:** **\*\***\_\_\_\_**\*\***

---

## 12. Engineering Review Edition (Same-Spec Review Layer)

This section is an implementation review layer for engineering/design/data review meetings. It does not change MVP scope; it operationalizes it into build phases, API contracts, test gates, and launch readiness criteria.

### 12.1 Delivery Phases and Milestones

| Phase                              | Scope                                                                                           | Exit Criteria                                                                                                                      |
| ---------------------------------- | ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Phase 1: Foundation                | Module 0 shell + Job Post CRUD + route unification (`/` and `/home`) + copy behavior            | Demo proves create/edit/close/archive/copy; copy excludes candidate links via integration test.                                    |
| Phase 2: JD Intelligence           | Module 1 parser integration, tag rendering, provenance, manual editing, drag reorder, JSON sync | JD parse + edit cycle complete; provenance available per skill; clarification prompts resolve missing required fields.             |
| Phase 3: Candidate Ingestion       | Module 2 batch import, parser orchestration, failure handling, source channel persistence       | Mixed success/failure upload batch handled correctly; failed rows can retry/delete; channel tagging coverage >= 95% in QA dataset. |
| Phase 4: Matching Core             | Module 3 scoring, ranking, breakdown visualization, fit clustering, async recalculation         | Ranking stable and reproducible; async jobs update UI without blocking; stale-state handling verified.                             |
| Phase 5: Diagnostics and Hardening | JD diagnostic widget, channel dashboard, observability, security checks, UAT fixes              | KPI instrumentation active, error taxonomy complete, UAT sign-off for top 5 recruitment scenarios.                                 |

### 12.2 API Surface (MVP Proposed)

| Endpoint                                   | Method | Purpose                                            | Notes                                            |
| ------------------------------------------ | ------ | -------------------------------------------------- | ------------------------------------------------ |
| `/api/job-posts`                           | GET    | List job posts with summary fields                 | Supports status filter and pagination.           |
| `/api/job-posts`                           | POST   | Create new job post                                | Supports `clone_from_job_post_id` for deep copy. |
| `/api/job-posts/{id}`                      | PATCH  | Update base job post fields                        | Last-write-wins with `updated_at` check.         |
| `/api/job-posts/{id}/archive`              | POST   | Close/archive role                                 | Soft state transition only.                      |
| `/api/job-posts/{id}/jd/parse`             | POST   | Trigger JD parsing from raw text                   | Returns schema in Section 5.1.                   |
| `/api/job-posts/{id}/jd`                   | PATCH  | Save manual edits/reorder to JD JSON               | Atomic replace of structured payload.            |
| `/api/job-posts/{id}/candidates/import`    | POST   | Batch upload CV files with source channel          | Async ingestion job creation.                    |
| `/api/job-posts/{id}/candidates`           | GET    | Get linked candidates with profile basics          | Supports fit-band and channel filters.           |
| `/api/job-posts/{id}/matching/recalculate` | POST   | Trigger asynchronous re-scoring                    | Returns `recalc_job_id`.                         |
| `/api/job-posts/{id}/matching`             | GET    | Fetch ranked candidates + breakdown + fit band     | Optional `score_version=latest`.                 |
| `/api/job-posts/{id}/diagnostics`          | GET    | Must-skill satisfaction and relaxation suggestions | Threshold alert default is <20%.                 |
| `/api/job-posts/{id}/analytics/channels`   | GET    | Source channel dashboard data                      | Count + average score by channel.                |

### 12.3 Data and Consistency Rules (Review-Critical)

1. **Deep Clone Rule (Non-negotiable):** copy flow clones role metadata + JD JSON only; candidate links and score history are excluded.
2. **Versioned Scoring Rule:** each recalculation increments `score_version`; UI always reads latest successful version.
3. **Taxonomy Normalization Rule:** both JD and CV skill tokens must resolve to canonical taxonomy IDs before scoring.
4. **Save Semantics Rule:** last-write-wins in MVP; server records `updated_by` and `updated_at` on every mutation.
5. **Failure Isolation Rule:** per-file CV parse failure does not block successful files in the same batch.

### 12.4 Test Plan and Quality Gates

| Test Layer        | Coverage Focus                            | Mandatory Cases                                                                                            |
| ----------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Unit Tests        | Score calculation and normalization logic | Must vs Preferred weighting, tie-breaking, missing-data penalty, fit-band thresholds.                      |
| Contract Tests    | JD parser and matching schema compliance  | Validate Section 5.1 and 5.2 payload compatibility; reject invalid enum values.                            |
| Integration Tests | Module-to-module workflow                 | Copy without candidate links, parse-edit-save loop, upload-to-linking pipeline, recalculation propagation. |
| E2E Tests         | User-critical scenarios                   | New role to ranked shortlist; failure retry flow; low-fit elimination filter; channel dashboard rendering. |
| Performance Tests | Async and list scaling                    | 500-candidate role recalculation P95 <= 60s; list fetch under target latency.                              |
| Security Tests    | Authz and data handling                   | Role-based API checks, signed upload constraints, PII leakage scan in logs.                                |

### 12.5 Release Readiness Checklist

- [ ] Route and Module 0 functionality validated in staging.
- [ ] JD parse quality acceptance completed with representative role set (technical + non-technical).
- [ ] Import failure taxonomy mapped to user-facing messages and retry actions.
- [ ] Async recalculation queue saturation test completed with rollback/fallback behavior verified.
- [ ] KPI telemetry dashboard published for all Section 9 metrics.
- [ ] Security review passed (upload validation, RBAC checks, encryption confirmation).
- [ ] UAT sign-off from at least 2 recruiter personas.

### 12.6 Observability and Ops Runbook (MVP Minimum)

| Signal                             | Threshold                        | On-Call Action                                                                          |
| ---------------------------------- | -------------------------------- | --------------------------------------------------------------------------------------- |
| JD parse error rate                | >5% in 15 minutes                | Check parser upstream status, roll to fallback mode, notify product owner.              |
| CV import failure spike            | >15% batch failure in 30 minutes | Inspect file-type distribution and parser timeout logs; enable guided re-upload banner. |
| Recalc queue delay                 | Job wait time >120 seconds       | Scale worker pool; prioritize active roles; trigger backlog cleanup.                    |
| Score contract validation failures | Any sustained occurrence         | Block release toggle for new parser version; revert schema consumer.                    |

### 12.7 Open Review Decisions (To Resolve Before Build Lock)

1. Confirm exact fit-band threshold logic: fixed absolute score vs percentile by role.
2. Confirm salary field handling in clarification prompts (required vs optional in MVP).
3. Confirm channel enum seed set and naming alignment with reporting stakeholders.
4. Confirm retry limits and cooldown policy for repeated parse failures.
5. Confirm whether archived roles remain visible in analytics by default.

### 12.8 Engineering Sign-off Criteria

MVP build is review-approved only when:

1. All P0 acceptance criteria in Section 2 are demonstrated in staging.
2. Risks R1-R5 each have implemented mitigations with automated or monitored controls.
3. KPI instrumentation is live and queryable before production release.
4. No Critical or High severity unresolved defects remain in launch scope.

### 12.9 API Error Code Catalog (Frontend-Backend Contract)

The following error catalog is the MVP contract for user-facing and operationally actionable failures.

| Error Code                        | HTTP Status   | Module       | Retryable | User Message (UI)                                                                         | Client Action                                                                   |
| --------------------------------- | ------------- | ------------ | --------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `JOB_POST_NOT_FOUND`              | 404           | Module 0     | No        | Job Post not found or no longer available.                                                | Redirect to Job Post list and refresh data.                                     |
| `JOB_POST_CONFLICT_STALE_WRITE`   | 409           | Module 0     | Yes       | This Job Post was updated by another user. Your latest save follows MVP overwrite policy. | Reload latest snapshot, show last-updated metadata, allow user re-apply edits.  |
| `JOB_POST_CLONE_SOURCE_INVALID`   | 400           | Module 0     | No        | Selected source Job Post cannot be cloned.                                                | Prompt user to select another source role.                                      |
| `JOB_POST_CLONE_DEEP_COPY_FAILED` | 500           | Module 0     | Yes       | Failed to copy Job Post template. Please retry.                                           | Retry once; if still failing, surface support reference ID.                     |
| `JD_PARSE_EMPTY_INPUT`            | 400           | Module 1     | No        | JD content is empty. Please paste job description text.                                   | Block parse action until text is provided.                                      |
| `JD_PARSE_TIMEOUT`                | 504           | Module 1     | Yes       | JD parsing timed out. Please retry in a moment.                                           | Show retry button and preserve current JD text.                                 |
| `JD_PARSE_UPSTREAM_UNAVAILABLE`   | 503           | Module 1     | Yes       | JD parsing service is temporarily unavailable.                                            | Retry with exponential backoff; allow manual editing fallback.                  |
| `JD_PARSE_SCHEMA_INVALID`         | 502           | Module 1     | No        | JD parser returned an invalid structure.                                                  | Log contract error, fallback to manual requirement entry mode.                  |
| `JD_CLARIFICATION_REQUIRED`       | 422           | Module 1     | No        | More information is needed to finalize requirements.                                      | Render closed-option clarification prompts and block completion until answered. |
| `JD_PROVENANCE_MISSING`           | 200 (warning) | Module 1     | No        | Some skills do not have source traces.                                                    | Display warning badge; allow HR edit and continue.                              |
| `CV_IMPORT_UNSUPPORTED_FILE_TYPE` | 415           | Module 2     | No        | Unsupported file format. Upload PDF, DOC, or DOCX.                                        | Mark row failed and show remove action.                                         |
| `CV_IMPORT_FILE_TOO_LARGE`        | 413           | Module 2     | No        | File exceeds size limit.                                                                  | Mark failed; suggest compress/re-upload.                                        |
| `CV_PARSE_ENCRYPTED_PDF`          | 422           | Module 2     | No        | Encrypted PDF cannot be parsed. Upload an unlocked file.                                  | Mark failed with re-upload guidance.                                            |
| `CV_PARSE_SCANNED_IMAGE_LOW_TEXT` | 422           | Module 2     | Yes       | Scanned image quality is too low for parsing.                                             | Offer retry and guidance for higher-quality file.                               |
| `CV_PARSE_TIMEOUT`                | 504           | Module 2     | Yes       | CV parsing timed out for this file.                                                       | Keep row in failed state with retry action.                                     |
| `CV_PARSE_UPSTREAM_UNAVAILABLE`   | 503           | Module 2     | Yes       | CV parsing service is temporarily unavailable.                                            | Batch-level retry option with cooldown.                                         |
| `CANDIDATE_LINK_DUPLICATE`        | 409           | Module 2     | No        | Candidate is already linked to this Job Post.                                             | Skip duplicate and continue processing remaining files.                         |
| `SOURCE_CHANNEL_REQUIRED`         | 400           | Module 2     | No        | Source channel is required before import.                                                 | Disable submit until channel is selected.                                       |
| `MATCH_TAXONOMY_UNMAPPED_SKILL`   | 422           | Module 3     | No        | Some skills could not be normalized and were scored with reduced confidence.              | Show warning; include affected skills in diagnostics panel.                     |
| `MATCH_SCORE_COMPUTE_FAILED`      | 500           | Module 3     | Yes       | Failed to compute candidate scores. Showing last successful ranking.                      | Keep stale ranking, display stale-data indicator, allow retry recalculation.    |
| `RECALC_JOB_ENQUEUE_FAILED`       | 500           | Module 3     | Yes       | Unable to start recalculation job.                                                        | Retry enqueue; if repeated failure, suggest save-and-retry later.               |
| `RECALC_JOB_TIMEOUT`              | 504           | Module 3     | Yes       | Recalculation exceeded processing time limit.                                             | Preserve old score version; allow manual retry.                                 |
| `RECALC_JOB_CANCELLED`            | 409           | Module 3     | Yes       | Recalculation was cancelled due to newer updates.                                         | Auto-fetch latest job status and newest score version.                          |
| `DIAGNOSTIC_INSUFFICIENT_SAMPLE`  | 200 (warning) | Module 3     | No        | Not enough candidate data for reliable JD diagnostic.                                     | Show informational state and hide strict recommendations.                       |
| `CHANNEL_ANALYTICS_NOT_READY`     | 202           | Module 3     | Yes       | Channel analytics is still preparing.                                                     | Poll endpoint until ready; render loading placeholder.                          |
| `AUTH_FORBIDDEN`                  | 403           | Cross-module | No        | You do not have permission to perform this action.                                        | Hide privileged actions and route user to allowed views.                        |
| `RATE_LIMIT_EXCEEDED`             | 429           | Cross-module | Yes       | Too many requests. Please try again shortly.                                              | Retry with backoff and request de-duplication.                                  |
| `INTERNAL_UNEXPECTED_ERROR`       | 500           | Cross-module | Yes       | Unexpected system error occurred.                                                         | Show support ID and safe retry option.                                          |

#### Error Payload Contract (MVP)

```json
{
  "error_code": "string_enum",
  "message": "human_readable_message",
  "module": "module_0|module_1|module_2|module_3|cross",
  "retryable": true,
  "request_id": "uuid",
  "details": {
    "job_post_id": "uuid|null",
    "candidate_id": "uuid|null",
    "file_name": "string|null",
    "upstream_service": "jd_parser|cv_parser|matching_engine|null"
  },
  "timestamp": "ISO-8601"
}
```

#### Retry Policy (MVP)

1. **Immediate retry (once):** network transient, 502/503/504 class errors.
2. **Exponential backoff:** start 2s, then 5s, then 10s; max 3 attempts for background-safe endpoints.
3. **No auto-retry:** validation and business-rule errors (4xx non-transient).
4. **User-visible fallback:** when retries exhausted, keep last successful state and show actionable next step.
