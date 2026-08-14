# Product Requirements Document (PRD)

**Feature Name:** JD Parsing and Skill Weighting Contract  
**Version:** v1.1 (Implementation-Aligned MVP)  
**Status:** Draft  
**Product Manager:** HR Product Team  
**Target Users:** Recruiters, Hiring Managers, Recruiting Ops

---

## 1. Executive Summary

This document defines the **actual, code-aligned** contract for JD parsing and skill weighting in this repository, and corrects prior assumptions that did not match implementation.

The MVP behavior today is:

- Parse raw JD text into structured requirement buckets.
- Persist parsed requirements into `job_posts.jd_parsed_json`.
- Generate default skill weights into `job_posts.weight_config_json`.
- Use parsed output to support diagnostics and downstream scoring views.

CRITICAL principle: parsing and weighting outputs must stay deterministic, inspectable, and backward compatible with current frontend consumers.

---

## 2. MVP Scope (P0 + P1)

### P0 — Implemented / Required Now

| ID | Feature | Description |
|---|---|---|
| F0.1 | JD Parse on Job Create | `POST /jobs` parses `description` immediately and saves `jd_parsed_json` + `weight_config_json`. |
| F0.2 | Parse Existing Job JD | `POST /jobs/{job_id}/parse-jd` re-parses provided JD text and replaces parsed/weight payloads. |
| F0.3 | Structured Requirement Buckets | Output includes `must_skills`, `preferred_skills`, `language_requirements`, `education_requirement`, `visa_requirement`, `experience_requirement`. |
| F0.4 | Skill Provenance Stub | Each parsed skill includes `provenance.source_sentence` and confidence metadata. |
| F0.5 | Default Weight Extraction | Backend derives `weight_config_json.skills[]` from parsed skill entries using parser-assigned skill weights. |
| F0.6 | JD Diagnostics Endpoint | `GET /jobs/{job_id}/diagnosis` returns must-skill satisfaction view based on current score breakdown logic. |

### P1 — Near-Term Corrections / Hardening

| ID | Feature | Description |
|---|---|---|
| F1.1 | API Contract Unification | Standardize snake_case/camelCase mapping for weight skills (`skill_id` vs `skillId`). |
| F1.2 | Weight Update Endpoint | Implement backend `PUT /jobs/{job_id}/weight` expected by frontend service. |
| F1.3 | Recalculate Endpoint | Implement backend `POST /jobs/{job_id}/recalculate` expected by frontend service. |
| F1.4 | JD Parse History Write | Persist parse snapshots into `jd_parser_history` for auditability. |
| F1.5 | Evidence Precision | Replace current prefix-based provenance with sentence-level source spans. |

---

## 3. Out of Scope

- Replacing JD parser with fully LLM-only extraction in MVP.
- Token-level explainability visualizations.
- Real-time collaborative editing and conflict merge.
- Multi-language JD parsing quality guarantees.
- Redesign of full candidate scoring engine.

---

## 4. Technical Workflow

1. Client submits job create/update parse action.
2. `JDParserService.parse_jd()` normalizes text and runs rule-based extraction.
3. Service computes:
   - required/preferred skill buckets
   - years extraction
   - language/education/visa placeholders
   - LLM-ready preprocessed payload (internal metadata)
4. Route writes parsed JSON to `job_posts.jd_parsed_json`.
5. Route derives `weight_config_json` from parsed skills via `_default_weight_config`.
6. Job detail and diagnosis endpoints consume persisted JSON.

Notes:

- Parser currently remains rule-first (with preprocessed LLM refinement payload prepared but not automatically applied in route).
- Parse response API returns persisted parsed JSON and weight config; internal prompt metadata is not exposed via job routes.

---

## 5. Output Contract / Fixed JSON Schema

### 5.1 `jd_parsed_json` (Persisted)

```json
{
  "must_skills": [
    {
      "skill_id": "python_1",
      "display_name": "Python",
      "canonical_skill": "python",
      "priority_order": 1,
      "weight": 1.0,
      "provenance": {
        "source_sentence": "requirements: python ...",
        "source_char_start": 0,
        "source_char_end": 240,
        "confidence": 0.75
      }
    }
  ],
  "preferred_skills": [
    {
      "skill_id": "docker_1",
      "display_name": "Docker",
      "canonical_skill": "docker",
      "priority_order": 1,
      "weight": 0.6,
      "provenance": {
        "source_sentence": "nice to have: docker ...",
        "source_char_start": 0,
        "source_char_end": 240,
        "confidence": 0.75
      }
    }
  ],
  "language_requirements": [
    {
      "language": "English",
      "level": "business",
      "is_mandatory": true,
      "provenance": "..."
    }
  ],
  "education_requirement": {
    "minimum_degree": "bachelor",
    "field_of_study": null,
    "is_mandatory": true,
    "provenance": "..."
  },
  "visa_requirement": {
    "requirement_type": "unknown",
    "target_region": null,
    "provenance": "..."
  },
  "experience_requirement": {
    "minimum_years": 3
  }
}
```

### 5.2 `weight_config_json` (Persisted)

```json
{
  "skills": [
    { "skill_id": "python_1", "weight": 1.0 },
    { "skill_id": "docker_1", "weight": 0.6 }
  ]
}
```

### 5.3 API Responses (Current)

- `POST /jobs/{job_id}/parse-jd` returns:

```json
{
  "version": "string",
  "id": "uuid",
  "jd_parsed_json": {},
  "weight_config_json": {},
  "updated_at": "ISO-8601"
}
```

CRITICAL correction: frontend type definitions should accept backend snake_case skill keys in weight config unless a dedicated mapper is added.

---

## 6. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Determinism | Same JD input should produce stable bucketing/weights under same parser version. |
| Explainability | Every skill item must carry provenance payload (even if coarse in MVP). |
| Compatibility | API output must remain compatible with existing job pages and list/detail flows. |
| Resilience | Invalid/empty input must return explicit parse failure state (422 path in routes). |
| Performance | JD parse request should remain interactive for standard JD sizes (< 5k chars). |

---

## 7. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Parser bucket misclassification on mixed lines | Medium | Keep section-aware parsing and add sentence-level split tests. |
| Frontend/backend casing mismatch in weight config | High | Add mapper or unify contract to one canonical key style. |
| Diagnosis logic not truly per-skill | Medium | Mark current method as heuristic; implement true skill-level satisfaction scoring in P1. |
| Weight update/recalculate endpoints missing | High | Add routes expected by frontend service or gate frontend calls behind feature flags. |
| Provenance quality too generic | Medium | Upgrade to sentence-span extraction in parser service. |

---

## 8. Boundary / Separation Requirements

- CRITICAL: JD parser logic stays in `backend/app/services/jd_parser`.
- CRITICAL: CV parser logic stays in `backend/app/services/cv_parser`.
- Job route layer (`backend/app/api/routes/jobs.py`) orchestrates persistence; it does not own parsing rules.
- Frontend can render and edit via API contracts but must not assume undocumented keys.

---

## 9. Success Metrics (KPIs)

| Metric | Target |
|---|---|
| Parse success rate (`/parse-jd`) | >= 98% for valid non-empty JD payloads |
| Schema validity rate | 100% responses conform to Section 5 contract |
| Frontend parse-render failures | 0 critical runtime errors from payload shape mismatch |
| Median parse response time | <= 1.5s in local/staging baseline |
| Provenance presence | >= 95% of parsed skills include non-empty provenance text |

---

## 10. Future Considerations (Post-MVP)

- Enable optional LLM refinement pass using existing preprocessed payload.
- Add parser confidence scoring per field and per skill.
- Versioned parser outputs with migration tooling.
- First-class manual JD skill edit/save API contract.
- True score recomputation pipeline tied to weight updates.

---

## 11. PRD Owner Sign-off

**PRD Owner Sign-off:** ____________________  
**Engineering Lead Sign-off:** ____________________  
**Date:** ____________________

