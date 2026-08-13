# Product Requirements Document (PRD)

**Feature Name:** **CV Insight Parser (Current Production Parser)**  
**Version:** v1.0 (MVP / Current Baseline)  
**Status:** Draft  
**Product Manager:** [Your Name]  
**Target Users:** Recruiters, HR Specialists, Hiring Managers, Talent Ops

---

## 1. Executive Summary

This document defines the requirements for the **CV parser** currently implemented in `backend/app/services/cv_parser/service.py` (primary module namespace: `app.services.cv_parser`).

The CV parser accepts a candidate PDF resume, performs multimodal and text-based extraction with fallbacks, and returns a normalized structured JSON containing candidate identity, skills, education, experience, and publications.

This PRD also establishes a product boundary:

- `CV parser` = implemented and in active use.
- `JD parser` = newly introduced concept, but extraction logic is **not implemented yet**.

The immediate goal is to keep CV parsing stable and measurable while leaving clear extension points for a future dedicated JD parser service.

---

## 2. Scope and Parser Boundary

### In Scope (Current CV Parser)

- Parse **CV/Resume PDF** files only.
- Extract and normalize:
  - `name`, `email`, `phone`
  - `skills`
  - `education`
  - `experience`
  - `publications`
- Support robust fallback chain:
  - Vision-first parsing
  - Text-only LLM fallback
  - Rule-based content fallback
- Cache parse result by file hash.

### Out of Scope (for this parser)

- Parsing standalone Job Descriptions as first-class input objects.
- JD skill taxonomy, must/preferred classification, JD evidence tagging.
- JD-specific missing-field workflows.

### Boundary Rule (Critical)

Any new JD parsing capability must be implemented in a **separate JD parser module/service**, not by overloading CV parser behavior inside `CVParserService`.

---

## 3. MVP Functional Requirements

### P0 — Must Have (Aligned to current implementation)

| ID   | Feature                     | Description                                                                                             |
| ---- | --------------------------- | ------------------------------------------------------------------------------------------------------- |
| F0.1 | PDF Input                   | Accept CV in PDF format. Reject unsupported file types.                                                 |
| F0.2 | Cache-First Flow            | Compute file MD5 and return cached structured output when available.                                    |
| F0.3 | Vision Parsing Primary Path | Render first N PDF pages to images and parse via multimodal LLM.                                        |
| F0.4 | Text Fallback               | If vision parse fails and fallback is enabled, parse compressed text with text LLM path.                |
| F0.5 | Rule-Based Fallback         | If both LLM paths fail, recover minimum structured content from deterministic regex/section heuristics. |
| F0.6 | Stable Schema Normalization | Normalize variant model keys into a fixed output schema.                                                |
| F0.7 | Contact Hint Merge          | Merge regex-derived email/phone/name hints into structured output when missing.                         |
| F0.8 | Content Enrichment Fallback | Fill empty arrays (`skills`, `education`, `experience`, `publications`) from raw text heuristics.       |
| F0.9 | Deterministic Metadata      | Return parse metadata (`status`, `parse_path`, `extraction_model`, `cache_hit`, `file_hash`).           |

### P1 — Important Quality Controls

| ID   | Feature                       | Description                                                              |
| ---- | ----------------------------- | ------------------------------------------------------------------------ |
| F1.1 | Focus Pass for Sparse Results | Trigger second vision pass when education/experience are empty.          |
| F1.2 | Fragment Merge Logic          | Merge fragmented job lines and education fragments into unified records. |
| F1.3 | Prompt Compression Guardrail  | Compress long CV text while preserving high-priority lines.              |
| F1.4 | Non-empty Preference Merge    | Prefer non-empty fields from focus pass payload for targeted sections.   |

---

## 4. Current Technical Workflow

1. Compute file hash and check parser cache.
2. Extract raw PDF text (`pdfplumber`, fallback `pypdf`).
3. Generate contact hints from raw text (`email`, `phone`, `name`).
4. Execute vision parse path:
   - Render pages as data URLs.
   - Run multimodal prompt.
   - Optionally run focus pass for timeline completeness.
5. Normalize LLM payload into stable schema.
6. Merge contact hints.
7. Apply deterministic content fallback for empty arrays.
8. If vision fails:
   - Use text LLM fallback when enabled.
   - Else downgrade to rule-based fallback.
9. Persist parse result into hash cache and return payload.

---

## 5. Output Contract (CV Parser)

```json
{
  "file_hash": "md5_string",
  "cache_hit": false,
  "structured_data": {
    "name": "Candidate Name",
    "email": "candidate@example.com",
    "phone": "+1-555-123-4567",
    "skills": ["Python", "FastAPI", "Docker"],
    "education": [
      {
        "school": "Example University",
        "degree": "Master",
        "major": "Computer Science",
        "period": "2018 - 2020"
      }
    ],
    "experience": [
      {
        "company": "Example Corp",
        "job_title": "Backend Engineer",
        "period": "2020-01 - Present",
        "description": "Built APIs, improved performance, and maintained services."
      }
    ],
    "publications": [
      {
        "title": "Paper Title",
        "journal": "Conference Name",
        "year": "2021"
      }
    ]
  },
  "raw_llm_response": {},
  "extraction_model": "model_name",
  "extraction_seed": 42,
  "status": "success",
  "parse_path": "vision",
  "error_message": null
}
```

Notes:

- `status` may be `success` or `fallback`.
- `parse_path` may be `vision`, `vision_focus`, `text_fallback`, or `rule_fallback`.

---

## 6. Non-Functional Requirements

| Category      | Requirement                                                                 |
| ------------- | --------------------------------------------------------------------------- |
| Determinism   | Use fixed seed and temperature settings for reproducibility where possible. |
| Resilience    | Parser must degrade gracefully across vision, text, and rule-based paths.   |
| Traceability  | Return parse path and error context in metadata for debugging.              |
| Performance   | Cache should reduce repeated parse latency for identical files.             |
| Compatibility | Support common CV formats in PDF layouts (single/multi-column).             |

---

## 7. Risks and Mitigations

| #   | Risk                                | Impact | Mitigation                                                          |
| --- | ----------------------------------- | ------ | ------------------------------------------------------------------- |
| R1  | OCR/layout ambiguity in complex CVs | High   | Vision-first strategy + optional focus pass + text fallback chain.  |
| R2  | Inconsistent LLM key naming         | Medium | Alias-based normalization (`experience`, `work_experience`, etc.).  |
| R3  | Fragmented timeline records         | Medium | Post-processing merge heuristics for education and experience rows. |
| R4  | Missing contact fields              | Medium | Regex contact hints merged into normalized payload.                 |
| R5  | Hallucinated fields                 | Medium | Prompt rules: explicit facts only, unknown -> null.                 |

---

## 8. JD Parser Separation Requirements

To avoid product confusion and maintenance risk, the system must keep explicit naming and ownership boundaries:

- CV parser concerns remain in `CVParserService`.
- JD parser logic must be created as a separate service/module (for example: `JDParserService`).
- Any future JD-specific prompt/schema/versioning must not modify the CV output contract.
- Shared utilities (LLM client, cache, text helpers) can be reused, but parsing pipelines must stay independent.

Current status:

- CV parser logic: implemented.
- JD parser logic: not implemented yet (placeholder scope only).

---

## 9. Success Metrics (CV Parser v1)

| Metric                                          | Target                           |
| ----------------------------------------------- | -------------------------------- |
| Parse success rate (`status=success`)           | >= 92% on internal CV sample set |
| Fallback-only rate (`parse_path=rule_fallback`) | <= 8%                            |
| Contact completeness (`email` or `phone`)       | >= 95%                           |
| Cache hit latency improvement                   | >= 70% faster than first parse   |

---

## 10. Future Considerations (Post-MVP)

- Introduce dedicated `JDParserService` with independent schema and quality metrics.
- Add confidence scoring per extracted CV section.
- Add multilingual CV parsing support.
- Add structured certification/project extraction with evidence spans.
- Add parser benchmarking suite and regression dataset.

---

**PRD Owner Sign-off:** ********\_******** **Date:** ****\_****
