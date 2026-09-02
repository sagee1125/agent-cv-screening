---
name: pipeline
description: "Run the full candidate screening pipeline end-to-end in one command: (optionally fetch a PolyU JD) parse JD -> build scoring config -> parse candidate CVs -> score & rank -> generate PDF one-pagers and an Excel comparison. Use when: (1) screening one or more candidates against a JD in a single run, (2) reproducing the REST demo flow offline without the API, or (3) chaining polyu-import, jd-parser, scorer, cv-parser, and report-gen together."
---

# Pipeline Skill (Agent Screening Orchestrator)

Run the whole screening pipeline in one command by chaining the other skill CLIs
(`polyu-import` -> `jd-parser` -> `scorer build-config` -> `cv-parser` -> `scorer score` -> `report-gen`).
It shells out to the exact same entry points documented in each skill, so behavior is identical
to running the steps manually. No backend code is duplicated or modified, and the REST demo
(frontend + `POST /api/v1/...` endpoints) is unaffected.

## Prerequisites

- Backend dependencies installed: `venv/Scripts/python.exe -m pip install -r backend/requirements.txt`.
- `.env` at repo root with `ZAI_API_KEY` and `LLM_BASE_URL` (the cv-parser step calls the Zhipu LLM).
- Run every command from the repository root.
- Network access to `https://jobs.polyu.edu.hk` only when using `--polyu-ref` / `--polyu-detail-url`.

## Run

```bash
venv/Scripts/python.exe .codex/skills/pipeline/scripts/run_pipeline.py \
  --jd-file jd.txt \
  --cv cv1.pdf --cv cv2.pdf \
  --position "Backend Engineer" \
  --output-dir data/pipeline_out
```

| flag                              | meaning                                                                                                                                 |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **JD source (choose one)**        |                                                                                                                                         |
| `--jd-file <txt>`                 | JD text file; parsed with the jd-parser skill                                                                                           |
| `--jd-json <json>`                | Already-parsed JD (jd-parser output, polyu-parsed output, or pure `structured_data`); skips parsing                                     |
| `--polyu-ref <REF>`               | PolyU external ref; fetched + parsed with the polyu-import skill (network)                                                              |
| `--polyu-detail-url <URL>`        | PolyU detail URL fallback used together with `--polyu-ref`                                                                              |
| **Candidates**                    |                                                                                                                                         |
| `--cv <pdf>` (repeatable)         | CV PDF to parse and score via the cv-parser skill                                                                                       |
| `--extracted <json>` (repeatable) | Already-extracted candidate JSON; skips cv-parser                                                                                       |
| **Reports**                       |                                                                                                                                         |
| `--position <title>`              | Job title shown on reports (required unless `--skip-reports`)                                                                           |
| `--refno <id>`                    | Job reference number. Together with each CV's application no. (from the filename) this is the only candidate label; names are never shown |
| `--engine <legacy\|matching>`     | Scoring engine: `legacy` (default, ScorerService) or `matching` (six-dimension engine that renders the modal-style radar/interview PDF) |
| `--reference-date <YYYY-MM-DD>`   | Reference date for the matching engine (default: today)                                                                                 |
| `--skip-reports`                  | Score + rank only; skip PDF/Excel generation                                                                                            |
| `--output-dir <dir>`              | Output directory for intermediate JSONs and reports (default `data/pipeline_out`)                                                       |
| **L1 reliability**                |                                                                                                                                         |
| `--max-retries <N>`               | Extra attempts per candidate step after the first (default `2`)                                                                         |
| `--resume`                        | Skip JD parse / CV parse / score when usable JSON exists **and** JD/CV bytes match the last run. If the JD or a CV file changed, cache is rebuilt. Unchanged PDFs/HTML are skipped by fingerprint even without this flag |
| `--fail-fast`                     | Abort the batch on the first per-candidate failure (legacy all-or-nothing behavior)                                                     |

## What it runs

1. **JD source**: `polyu fetch-and-parse` (if `--polyu-ref`/`--polyu-detail-url`), or `jd-parser` on `--jd-file`, or reuses `--jd-json` as-is.
2. **Config**: `scorer build-config --jd-structured <jd json> --output config.json`.
3. **Extraction**: `cv-parser --file <cv> [--jd-file jd-context.txt] --output extracted-<slug>.json` per `--cv` (`slug` is the source filename stem). One CV failing does not stop the others unless `--fail-fast`.
4. **Scoring**: `scorer score --extracted extracted-<slug>.json --config config.json --output score-<slug>.json` per successful parse (matching engine writes `detail-<slug>.json`).
5. **Ranking**: successful candidates sorted by `total_score` descending, `rank` 1..N.
6. **Reports**: PDF one-pager per successful candidate + Excel across those rows only.

## Engine modes

- **`legacy` (default)**: `scorer build-config` + `scorer score` -> `dimension_scores` + `interview_suggestions`. PDF radar is drawn from `dimension_scores`.
- **`matching`**: `scorer match` per candidate -> the same radar/interview-question detail payload the frontend candidate-match modal shows (`match_score`, `fit_band`, `eligibility`, `evidence_confidence`, `radar_dimensions` with per-dimension reasoning/gaps, `interview_questions`). PDFs render the modal content: radar chart, dimension details, and suggested interview questions. The Excel rows map `core_skill_match` / `relevant_experience` / `education_certification` / `evidence_impact` to the standard comparison columns.

## Output manifest

stdout prints a JSON manifest:

```json
{
  "status": "success",
  "engine": "legacy",
  "refno": "260818001",
  "output_dir": ".../data/pipeline_out",
  "jd_source": ".../data/pipeline_out/jd-parse.json",
  "config_json": ".../data/pipeline_out/config.json",
  "candidates": [
    {
      "rank": 1,
      "refno": "260818001",
      "appno": "123456",
      "display_label": "260818001/123456",
      "source": ".../123456.pdf",
      "total_score": 85.2,
      "tier": "Tier 1",
      "extracted_json": "...",
      "score_json": "...",
      "report_pdf": "..."
    }
  ],
  "failures": [],
  "ask": null,
  "reports": { "screening_board_html": "..." }
}
```

- `status` is `success` (everyone succeeded), `partial_success` (at least one candidate succeeded and at least one failed), `error` (JD/config hard-fail or zero candidates succeeded), or `need_input` (missing JD, CVs, or `--position`).
- Candidates in the manifest are labeled by `refno` + `appno` (`display_label`). Personal names are never included.
- Intermediate files (`jd-parse.json`, `config.json`, `extracted-<slug>.json`, `score-<slug>.json`, `manifest.json`, `rows.json`) are kept in `--output-dir` for inspection and `--resume`.
- Exit codes: `0` for `success` / `partial_success`; `2` for `need_input` (stdout JSON with `missing` + `questions`); `1` for `error` (stderr JSON).

## Behavior notes

- Reuses the other skill CLIs as subprocesses (`sys.executable`), so it inherits the venv/python that launched it.
- `--jd-file` text is written to `jd-context.txt` and passed to the cv-parser as JD context.
- `--jd-json` from `polyu fetch-and-parse` supplies its `jd_text` as CV context; from `jd-parser` there is no original text, so no JD context is passed to cv-parser.
- `--polyu-detail-url` is only accepted together with `--polyu-ref` (catalog fallback); it cannot be combined with `--jd-file` or `--jd-json`.
- Per-candidate steps (CV parse, score/match, PDF) retry `--max-retries` extra times; JD fetch/parse and `build-config` remain batch-hard failures.
- `--resume` skips a step when the target JSON in `--output-dir` already loads as an object **and** the JD/CV input fingerprint matches the last run. A changed JD disables resume; a replaced CV file rebuilds only that candidate.
- No DB writes, no REST API calls — this is the offline equivalent of the web demo flow.

## Offline example (no LLM, no network)

```bash
venv/Scripts/python.exe .codex/skills/pipeline/scripts/run_pipeline.py \
  --jd-json .codex/skills/scorer/examples/sample-jd-structured.json \
  --extracted .codex/skills/report-gen/examples/sample-extracted.json \
  --position "Backend Engineer" \
  --engine matching \
  --output-dir /tmp/pipeline_demo
```

## Pipeline diagram

```mermaid
flowchart LR
    A["polyu-import"] --> B["jd-parser"]
    B --> C["scorer build-config"]
    C --> E["scorer score + rank"]
    D["cv-parser"] --> E
    E --> F["report-gen PDF / Excel"]
```

## Ownership

Pipeline only orchestrates sibling skill CLIs. Domain logic lives in those skills, not in `backend/`.


## Input policy (PII boundary)

This skill only accepts **file paths or allowlisted http(s) URLs** as JD/CV inputs.

- Inline content is refused: base64 blobs, `data:` URIs, pasted text, and
  over-length strings cause an immediate `{"status":"error",...}` envelope
  with exit code 1, before any parsing or network call.
- `--cv`, `--jd-file`, `--jd-json`, and `--extracted` must point to
  **existing files**; missing paths are rejected with exit code 1.
- `--polyu-detail-url` must be an http(s) URL whose host is allowlisted
  (default: `jobs.polyu.edu.hk`).
- Do **not** parse file content and pass it in — give the agent the path or
  URL instead. This keeps candidate PII out of the host conversation
  (PIPL/GDPR friendly).
- `--extracted` profiles must live inside `--output-dir` (agent scratch) unless
  `--trust-extracted` is passed for trusted, pre-masked data from elsewhere.

Enforcement lives in `.codex/skills/_shared/src/screening_core/input_policy.py`.


## Live fetch (Phase 1 skeleton)

The pipeline can also accept JAS URLs directly and download them locally before
running the same offline chain:

```bash
venv/Scripts/python.exe .codex/skills/pipeline/scripts/run_pipeline.py \
  --jd-url "https://jobs.polyu.edu.hk/internal/records.php?refno=260818001" \
  --cv-url "https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=123456&refno=260818001" \
  --cookie-file data/jas_cookies.txt \
  --position "Project Associate"
```

- `--jd-url` fetches the records page and parses it into JD text
  (`jd-from-url.txt` in `--output-dir`).
- `--cv-url` (repeatable) downloads each CV into `--scratch-dir`
  (default `data/jas_scratch`) named by application no. Downloads are kept for
  reuse and unchanged CVs are skipped via conditional HTTP (ETag); pass
  `--cleanup-cvs` to delete them after the run.
- `--cookie-file` reads a Netscape `cookies.txt` on disk; cookies are never
  accepted as CLI arguments (they would leak into process lists / the host).
- URL hosts are allowlisted (`jobs.polyu.edu.hk`) by the input policy; the
  initial URL, every redirect, and parsed CV URLs are all validated. For the
  public demo, pass `--allow-host jes-web-demo.vercel.app --base-url
  https://jes-web-demo.vercel.app --no-cookie`.
- This skeleton is unit-tested with mocks; it cannot be validated against the
  real JAS until internal access or an HR-run session is available.
