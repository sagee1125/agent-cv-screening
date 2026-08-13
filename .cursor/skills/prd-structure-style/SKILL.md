---
name: prd-structure-style
description: Standardize PRD writing in this repository using a fixed, numbered structure with MVP scope tables, schema contract, risks, KPIs, and future considerations. Use when the user asks to write, revise, or review a PRD, product requirement, parser requirement, or feature spec.
---

# PRD Structure Style (IHERD)

## Goal

Produce PRDs in one consistent style aligned with existing CV/JD parser documents.

## Required Header Block

Start every PRD with:

- `# Product Requirements Document (PRD)`
- `Feature Name`
- `Version` (for example `v1.0 (MVP)`)
- `Status` (Draft/Review/Approved)
- `Product Manager`
- `Target Users`

Then add a horizontal rule `---`.

## Canonical Section Structure

Use this exact ordered structure and numbering for the core PRD:

1. `Executive Summary`
2. `MVP Scope` (split into `P0` and `P1`)
3. `Out of Scope`
4. `Technical Workflow`
5. `Output Contract / Fixed JSON Schema` (if feature is parser/data extraction)
6. `Non-Functional Requirements`
7. `Risks and Mitigations`
8. `Boundary / Separation Requirements` (required when multiple services may overlap)
9. `Success Metrics (KPIs)`
10. `Future Considerations (Post-MVP)`
11. `PRD Owner Sign-off`

If a section is not applicable, keep the heading and write `N/A` with one-line reason.

When a user asks for an engineering review-ready version, append:

12. `Engineering Review Edition (Same-Spec Review Layer)` with implementation phases, API surface, test gates, release readiness, observability runbook, and open review decisions.

## Content Rules by Section

### 1) Executive Summary

- Describe user problem, product value, and expected output.
- Include one explicit trust/quality statement (for example traceability, determinism, explainability).
- Include product vision and success definition for MVP.
- Include at least 2 user personas when the feature is workflow-heavy or cross-module.

### 2) MVP Scope (P0 + P1)

- Use tables with `ID | Feature | Description`.
- `P0`: launch blockers only.
- `P1`: quality or usability enhancements that can be delayed.
- Every feature line should be testable.
- For multi-module systems, include a module priority summary table.
- Add explicit acceptance criteria grouped by module when possible.

### 3) Out of Scope

- Use bullet list.
- Exclude adjacent ideas explicitly to prevent scope creep.

### 4/7) Technical Workflow + Risks

- Workflow can be numbered steps.
- Risks must be a table with `Risk | Impact | Mitigation`.
- Include at least one failure-mode mitigation for fallback/degradation behavior.
- For workflow-heavy products, include both user flow and backend/system flow.

### 5) Output Contract / Schema

- Provide a fixed JSON schema in a fenced `json` block.
- Include required metadata fields (status, path/mode, cache flags, errors) when relevant.
- Use explicit nullability for uncertain fields.
- If the PRD includes storage planning, include concrete MVP database schema recommendations (key tables, constraints, indexing).

### 6) Non-Functional Requirements

- Table format recommended.
- Cover determinism/reproducibility, resilience, traceability, performance, compatibility/security as applicable.

### 8) Boundary / Separation Requirements

- Mandatory if neighboring modules exist (example: CV parser vs JD parser).
- State ownership boundaries and what must not be changed.

### 9) Success Metrics (KPIs)

- Table format `Metric | Target`.
- Targets must be measurable, time-bounded where possible, and aligned to MVP.
- Ensure each P0 capability maps to at least one metric or validation mechanism.

### 10) Future Considerations

- Bullet list only.
- Keep post-MVP ideas separated from launch scope.

## Style Rules

- Use numbered `##` headings (`## 1. ...`, `## 2. ...`).
- Keep terms consistent (do not rename same concept across sections).
- Prefer concise, operational wording over narrative prose.
- Mark critical requirements with explicit keywords: `CRITICAL` or `Non-negotiable`.
- Use English for doc body unless user requests another language.

## Authoring Workflow

1. Read related implementation or baseline PRD files.
2. Fill `P0/P1` first, then contract/schema, then risks, then KPIs.
3. Check section order against canonical structure.
4. Ensure each P0 item maps to at least one KPI or validation check.
5. If requested, append Section 12 engineering review layer without changing Sections 1-11 semantics.
6. Finalize with sign-off line.

## Template

Use and adapt this template first:

- `PRD_TEMPLATE.md`

## Quick Validation Checklist

- [ ] Header block complete.
- [ ] Section numbering and order match canonical structure.
- [ ] P0/P1 table present with testable items.
- [ ] Module priority summary and module-level acceptance criteria included (if multi-module).
- [ ] Out-of-scope is explicit.
- [ ] JSON contract present when data output exists.
- [ ] Database schema recommendation included when data persistence is core to MVP.
- [ ] Risks include mitigation.
- [ ] KPI table has numeric targets.
- [ ] Future scope separated from MVP.
- [ ] Sign-off line included.
- [ ] Section 12 review layer added when user asks for review/engineering edition.
