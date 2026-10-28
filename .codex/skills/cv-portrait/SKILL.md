---
name: cv-portrait
description: "Build a JD-independent capability portrait of one candidate from their CV: headline, overview, capability tags, evidence-cited strengths/gaps, reliability flags and interview probes. Every claim must quote the (masked) CV verbatim with a page number; quotes are verified locally and unverifiable ones are flagged. Cached by CV file hash - re-evaluated only when the file bytes change. Use when HR wants a per-person ability summary that stays stable across different job ads."
---

# CV Portrait Skill

A JD-independent, evidence-cited LLM assessment of one candidate's CV.

## Design boundaries

- **CV-only and JD-independent on purpose**: the portrait is keyed to the CV
  file alone, so it is cached by `md5(CV bytes) + portrait-v1` and reused for
  every job ad until the file itself changes. JD-specific matching stays in
  the deterministic scorer/matching engine.
- **Privacy identical to cv-parser**: the CV is extracted and redacted locally
  (`mask_pii_text_aggressive`); only masked text is sent to the LLM, guarded by
  the same pre-send check (`_assert_prompt_clean`). Evidence quotes inherit the
  masking. Attachments (cover letters, transcripts) are NOT read in this
  version - a future extension would key the cache on the document-set hash.
- **Evidence is verified, not trusted**: the prompt text carries `[Page N]`
  anchors and the model must attach `{"page", "quote"}` to every claim. Each
  quote is then checked locally against the masked page text; a quote that
  cannot be found is kept but flagged `"verified": false` (honest display),
  never silently passed off as sourced.

## Run

```bash
venv/Scripts/python.exe .codex/skills/cv-portrait/scripts/run_cv_portrait.py --file <cv.pdf|cv.doc> --output <portrait.json> [--converted-pdf <reuse.pdf>]
```

| flag | meaning |
|---|---|
| `--file` (required) | CV file (any extension; Word is converted locally first) |
| `--output` (required) | Target JSON path |
| `--converted-pdf` (optional) | Reuse an existing converted PDF (e.g. `converted-<slug>.pdf` from the parse stage) |

## Output JSON

```json
{
  "file_hash": "md5 of the submitted CV bytes",
  "cache_hit": false,
  "status": "success",
  "portrait": {
    "headline": "one-sentence capability headline",
    "overview": ["..."],
    "capability_tags": ["LLM application development", "..."],
    "strengths": [{"text": "...", "evidence": [{"page": 1, "quote": "...", "verified": true}]}],
    "gaps": [{"text": "...", "evidence": [...]}],
    "reliability_flags": ["self-reported only, no verifiable deliverable"],
    "interview_probes": ["..."]
  },
  "evidence_stats": {"verified": 6, "unverified": 1}
}
```

Fallbacks (LLM failure, unreadable scan) return `"status": "fallback"` and are
never cached, so a later run retries.

## Pipeline integration

`run_pipeline.py --with-portrait` builds `portrait-<slug>.json` for every
candidate after parsing (parallel, heartbeat progress, `--resume` reuse via
the `portrait_logic` stamp). The ranking table gains a Headline column and
each match page renders the portrait section with expandable evidence.
