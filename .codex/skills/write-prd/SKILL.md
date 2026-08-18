---
name: write-prd
description: Write, revise, or review a Product Requirements Document (PRD) in the IHERD style using a fixed numbered structure with MVP scope tables (P0/P1), output contract / JSON schema, risks, KPIs, boundary requirements, and an optional engineering review layer. Use when the user asks to create or draft a PRD, product requirement, parser requirement, feature spec, or to review/revise an existing PRD.
---

# PRD Writer (IHERD)

Write PRDs in one consistent, engineering-ready style aligned with the project CV/JD parser documents.

## Required Header Block

Start every PRD with:

- YAML frontmatter (machine-readable source of truth): `prd_id`, `feature_name`, `version`, `status`, `owner`, `api_version`, `related_docs`, `affected_modules`.
- A visible header block (`# Product Requirements Document (PRD)`, Feature Name, Version, Status, Product Manager, Target Users) kept in sync with the frontmatter.
- A horizontal rule `---`, then a `Change Log` table.

## Canonical Section Structure

Use this exact ordered numbering for the core PRD:

1. `Executive Summary`
2. `MVP Scope` (split into `P0` and `P1`)
3. `Out of Scope`
4. `Technical Workflow`
5. `Output Contract / Fixed JSON Schema` (parser/data extraction features)
6. `Non-Functional Requirements`
7. `Risks and Mitigations`
8. `Boundary / Separation Requirements` (when multiple services may overlap)
9. `Success Metrics (KPIs)`
10. `Future Considerations (Post-MVP)`
11. `PRD Owner Sign-off`

Keep headings for non-applicable sections and write `N/A` with a one-line reason.

When the user asks for an engineering review-ready version, append:

12. `Engineering Review Edition (Same-Spec Review Layer)`: implementation phases, API surface, test gates, release readiness, observability runbook, and open review decisions.

Append a `Glossary` section after Section 12 for cross-module terms.

## Content Rules by Section

### 0) Frontmatter + Change Log

- Emit the YAML frontmatter fields above; keep the visible header block in sync.
- Add a Change Log table with `Version | Date | Author | Change Summary`.

### 1) Executive Summary

- Describe user problem, product value, and expected output.
- Include one explicit trust/quality statement (traceability, determinism, explainability).
- Include product vision and MVP success definition.
- Include at least 2 user personas for workflow-heavy or cross-module features.
- Add an `Open Questions (Resolve Before Build)` subsection listing questions that could change scope or contract.

### 2) MVP Scope (P0 + P1)

- Use tables with `ID | Feature | Description | Status`; status is Not Started/In Progress/Done/Blocked.
- `P0`: launch blockers only; `P1`: delayable quality/usability enhancements.
- Make every feature line testable.
- Write acceptance criteria as assertable statements; use Gherkin (Given/When/Then) for critical paths.
- For multi-module systems, add a module priority summary table.
- Add a `Related Code / Entry Points` table mapping requirements to existing files.
- Add a `Requirements Traceability Matrix (RTM)` mapping every requirement to AC, test case ID, KPI/validation, and module/file.

### 3) Out of Scope

- Use a bullet list; explicitly exclude adjacent ideas to prevent scope creep.

### 4) Technical Workflow

- Use numbered steps.
- Include both user flow and backend/system flow for workflow-heavy products.
- Include failure and fallback workflow steps.
- Use Mermaid diagrams: sequence diagram for backend flow, state diagram for status/failure transitions.
- Add a `Config / Environment / External Dependencies` subsection: env vars, feature flags, external services with SLA/fallback.

### 5) Output Contract / Schema

- Add an `API Contract Summary` table: Endpoint | Method | Auth | Success | Error Codes | Idempotent | Rate Limit.
- Provide a versioned fixed JSON schema in a fenced `json` block (`schema_version` field).
- State the backward-compatibility policy (additive-only within major; breaking changes need a migration plan).
- Include required metadata (status, path/mode, cache flags, errors) when relevant.
- Use explicit nullability for uncertain fields.
- When storage planning is core to MVP, include concrete database schema recommendations with an ER diagram and data lifecycle rules (soft delete, retention, audit columns).

### 6) Non-Functional Requirements

- Use a table; cover determinism/reproducibility, resilience, traceability, performance, compatibility/security as applicable.

### 7) Risks and Mitigations

- Use a table with `Risk | Impact | Mitigation`.
- Include at least one failure-mode mitigation for fallback/degradation behavior.

### 8) Boundary / Separation Requirements

- Mandatory when neighboring modules exist (example: CV parser vs JD parser).
- State ownership boundaries and what must not be changed.

### 9) Success Metrics (KPIs)

- Use a table `Metric | Target | Measured By`; targets numeric and time-bounded where possible, aligned to MVP.
- `Measured By` states how to verify (dashboard, DB query, CI assertion).
- Map each P0 capability to at least one metric or validation mechanism (see RTM).

### 10) Future Considerations

- Use a bullet list only; keep post-MVP ideas separated from launch scope.

### 11) Sign-off

- Add a `Definition of Done (DoD)` checklist before the sign-off lines.
- End with PRD Owner / Engineering Lead / Data-AI Lead sign-off lines.

## Style Rules

- Use numbered `##` headings (`## 1. ...`, `## 2. ...`).
- Keep terminology consistent across sections.
- Prefer concise, operational wording over narrative prose.
- Mark critical requirements with `CRITICAL` or `Non-negotiable`.
- Write the document body in English unless the user requests another language.

## Authoring Workflow

1. Read related implementation or baseline PRD files first.
2. Fill frontmatter + header + change log.
3. Fill P0/P1 first, then contract/schema, then risks, then KPIs.
4. Build the RTM; ensure each P0 item maps to AC, test, and KPI.
5. Verify section order against the canonical structure.
6. Add Mermaid diagrams and the config/dependencies subsection.
7. Append Section 12 on request without changing Sections 1-11 semantics.
8. End with DoD, sign-off, and Glossary.

## Template

Copy and adapt `assets/PRD_TEMPLATE.md` as the starting point.

## Quick Validation Checklist

- [ ] YAML frontmatter present; header block in sync.
- [ ] Change Log present.
- [ ] Section numbering and order match canonical structure.
- [ ] P0/P1 tables present with testable items and status column.
- [ ] Gherkin/assertable ACs for critical paths.
- [ ] Related Code / Entry Points table included.
- [ ] RTM maps every P0 to AC + test + KPI + module.
- [ ] Out-of-scope explicit.
- [ ] Mermaid diagrams present for system flow / state.
- [ ] Config / env / external dependencies section present.
- [ ] API contract table present (method/auth/status/idempotency/rate limit).
- [ ] JSON contract present with `schema_version` + backward-compat rule.
- [ ] DB schema recommendation + ER diagram + data lifecycle when persistence is core.
- [ ] Risks include mitigations.
- [ ] KPI table has numeric targets and `Measured By`.
- [ ] Future scope separated from MVP.
- [ ] DoD checklist and sign-off included.
- [ ] Glossary present for cross-module terms.
- [ ] Section 12 added when review/engineering edition requested.