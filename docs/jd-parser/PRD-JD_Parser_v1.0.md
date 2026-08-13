# Product Requirements Document (PRD)

**Feature Name:** **JD Insight Engine (with Explainable AI Tags)**  
**Version:** v1.0 (MVP)  
**Status:** Draft  
**Product Manager:** [Your Name]  
**Target Users:** HR Specialists, Talent Acquisition Partners, Hiring Managers

---

## 1. Executive Summary

This feature enables HR users to paste a raw Job Description (JD) into a chat-style interface. The system extracts structured hiring criteria (Must-have / Preferred skills, language, education, visa requirements) using an LLM. Unlike a black-box parser, this tool prioritizes **Explainability**—every extracted tag displays the exact source sentence from the JD as evidence. If critical information is missing, the system triggers a guided Q&A modal (not a free-text chat) to collect it. Users can then visually confirm, re-rank skills via drag-and-drop, and export a structured JSON for downstream ATS integration.

---

## 2. MVP Scope (P0 + P1 Only)

### P0 — Core Extraction (Must-have for launch)

| ID   | Feature                           | Description                                                                                                                                                                                         |
| ---- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F0.1 | JD Paste Input                    | A large textarea supporting plain text paste (no formatting, no file upload).                                                                                                                       |
| F0.2 | NER Extraction                    | Extract: Hard Skills (tech/tools), Years of Experience (numeric), Education Level (BSc/MSc/PhD), Language + Proficiency (e.g., English: TOEIC 800+), Visa Sponsorship (Yes/No/Unclear).             |
| F0.3 | Must/Preferred Classification     | Classify skills into `must` or `preferred`. **Rule:** If the JD does not explicitly use "must"/"required"/"essential", default to `preferred` to avoid false negatives in candidate screening.      |
| F0.4 | Structured JSON Output            | Backend returns a fixed-schema JSON (see Section 6). The UI renders a human-readable card view (Tag Cloud + List).                                                                                  |
| F0.5 | Evidence Snippet (Explainability) | **CRITICAL P0:** Each extracted skill/requirement must display a clickable tooltip or inline citation showing the **exact verbatim sentence** from the original JD where this extraction came from. |

### P1 — Important but can be manual-assisted

| ID   | Feature                  | Description                                                                                                                                                                                                                   |
| ---- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1.1 | Guided Missing-Field Q&A | If `salary_range` OR `visa_sponsor` OR `start_date` is null/missing, the system triggers a non-intrusive modal with **button-style options** (e.g., "$60k–$80k", "$80k–$100k", "Not disclosed")—no free-text typing required. |
| F1.2 | Drag-and-Drop Re-ranking | Users can re-order skills vertically via drag-and-drop. The top position represents the highest importance.                                                                                                                   |
| F1.3 | Visual Weight Indicator  | A simple progress bar or badge next to each skill showing its relative weight (calculated via rank-order decay algorithm) after each drag.                                                                                    |

---

## 3. Out of Scope for MVP (V2+)

- Voice input / Speech-to-text
- Auto-matching against internal candidate database
- Generating interview questions
- Generating LinkedIn search boolean strings
- Multi-language JD support (English-only for v1)

---

## 4. Technical Risks & Mitigations

| #   | Risk Description                                                                                                | Impact | Mitigation Strategy                                                                                                                                                                   |
| --- | --------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | **Contradictory JD statements** (e.g., "Nice to have Python, must have Java" — AI misclassifies Python as Must) | High   | Prompt engineering: Force LLM to output a `reasoning` field for each classification. If reasoning is missing or ambiguous, reject the response and re-prompt.                         |
| R2  | **Ambiguous experience/education logic** (e.g., "5 years experience OR Master with 2 years")                    | Medium | Backend schema must support `condition_groups` (an array of alternative conditions) rather than a single `min_years` field.                                                           |
| R3  | **Drag-position vs. weight desync** — HR drags item to #1, but backend weight doesn't update in real-time       | Medium | Use client-side rank-order weighting (e.g., normalized exponential decay) and recalculate immediately on drag-end. Display the updated weight number next to the tag within 200ms.    |
| R4  | **JD noise from "culture fluff"** (e.g., "We are family", "fast-paced") pollutes tokens and confuses extraction | Low    | Pre-process: Strip common corporate buzzwords using a stopword list before sending to LLM. Also add system instruction: "Ignore all subjective adjectives and cultural descriptions." |

---

## 5. User Needs Beyond the Obvious (Top 1 Priority)

### 🔍 Need #1: "I need to know WHY the AI made this decision, or I won't trust it."

**Problem:** HR users are skeptical of black-box AI. They will not approve a candidate shortlist based on tags they cannot verify.

**Solution — "Source Traceability" (Explanatory Tags):**

- Every extracted skill/requirement card MUST display a **small "📌" icon** or a **"View Source"** link.
- On hover/click, a popover shows the **exact original sentence(s)** from the pasted JD that the AI used to make that classification.
- **Example:**
  - Tag: `Python (Must)`
  - Click "📌" → Popover shows: _"Extracted from: 'Must have 5+ years of production-level Python development.'"_

**Non-negotiable:** If this evidence layer is missing, the feature will NOT pass UAT (User Acceptance Testing).

---

## 6. Fixed JSON Schema (Backend Contract)

```json
{
  "jd_id": "uuid",
  "extracted_at": "ISO-8601",
  "skills": {
    "must": [
      {
        "skill": "Python",
        "evidence": "Must have 5+ years of production-level Python development.",
        "weight": 0.95
      }
    ],
    "preferred": [
      {
        "skill": "AWS",
        "evidence": "Nice to have AWS certification.",
        "weight": 0.60
      }
    ]
  },
  "experience": {
    "min_years": 5,
    "condition_groups": [
      { "type": "or", "criteria": "Master's degree + 2 years" }
    ],
    "evidence": "5 years experience or Master with 2 years"
  },
  "education": {
    "min_degree": "Bachelor",
    "preferred_degree": "Master",
    "evidence": "Bachelor's required, Master's preferred"
  },
  "language": [
    {
      "name": "English",
      "proficiency": "TOEIC 800+",
      "evidence": "English proficiency: TOEIC 800 or equivalent"
    }
  ],
  "visa_sponsorship": {
    "provided": null,
    "evidence": null
  },
  "missing_fields": ["visa_sponsorship", "salary_range"]
}

## 7. UX Flow (User Journey)

1. **Paste JD** → User pastes raw text into the input box and clicks "Analyze".
2. **Loading State** → Show skeleton screen with a progress message: "Extracting skills... locating evidence..."
3. **Confirmation Dashboard** → Display:
   - Left panel: **Original JD** with highlighted sentences (color-coded: yellow for Must, blue for Preferred).
   - Right panel: **Structured tag list**, each with a "📌 evidence" tooltip.
4. **Missing Field Modal** → If `visa_sponsorship` or `salary` is missing, a modal pops up with button options to fill them.
5. **Drag & Re-rank** → User drags skills to reorder. Weight updates in real-time.
6. **Confirm & Export** → User clicks "Confirm" → System locks the structure and provides a "Copy JSON" button + a printable summary card.

---

## 8. Success Metrics (KPIs for v1)

| Metric | Target |
|--------|--------|
| Extraction Accuracy (Must/Preferred) | ≥ 90% (tested against 20 real JDs) |
| Evidence Click-through Rate | ≥ 70% of users click at least one "📌" per session |
| Time to Confirm (from paste to export) | ≤ 2 minutes (baseline: manual parsing takes 10+ mins) |
| Missing-field completion rate | ≥ 85% via button modal (no drop-off) |

---

## 9. Future Considerations (Post-MVP)

- Multi-language JD support
- Auto-suggest "alternative equivalent conditions" (e.g., "Certification can replace 1 year of experience")
- Export to ATS plugins (Greenhouse, Lever) via API
- Integration with internal candidate database for auto-matching
- Generate interview question bank based on extracted skills
- Boolean search string generator for LinkedIn/Sourcing

---

**PRD Owner Sign-off:** _________________  **Date:** _________
```
