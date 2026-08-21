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

- Backend dependencies installed: `pip install -r backend/requirements.txt`.
- `.env` at repo root with `ZAI_API_KEY` and `LLM_BASE_URL` (the cv-parser step calls the Zhipu LLM).
- Run every command from the repository root.
- Network access to `https://jobs.polyu.edu.hk` only when using `--polyu-ref` / `--polyu-detail-url`.

## Run

```bash
python .codex/skills/pipeline/scripts/run_pipeline.py \
  --jd-file jd.txt \
  --cv cv1.pdf --cv cv2.pdf \
  --position "Backend Engineer" \
  --output-dir data/pipeline_out
```

| flag | meaning |
|---|---|
| **JD source (choose one)** | |
| `--jd-file <txt>` | JD text file; parsed with the jd-parser skill |
| `--jd-json <json>` | Already-parsed JD (jd-parser output, polyu-parsed output, or pure `structured_data`); skips parsing |
| `--polyu-ref <REF>` | PolyU external ref; fetched + parsed with the polyu-import skill (network) |
| `--polyu-detail-url <URL>` | PolyU detail URL fallback used together with `--polyu-ref` |
| **Candidates** | |
| `--cv <pdf>` (repeatable) | CV PDF to parse and score via the cv-parser skill |
| `--extracted <json>` (repeatable) | Already-extracted candidate JSON; skips cv-parser |
| **Reports** | |
| `--position <title>` | Job title shown on reports (required unless `--skip-reports`) |
| `--engine <legacy\|matching>` | Scoring engine: `legacy` (default, ScorerService) or `matching` (six-dimension engine that renders the modal-style radar/interview PDF) |
| `--reference-date <YYYY-MM-DD>` | Reference date for the matching engine (default: today) |
| `--skip-reports` | Score + rank only; skip PDF/Excel generation |
| `--output-dir <dir>` | Output directory for intermediate JSONs and reports (default `data/pipeline_out`) |

## What it runs

1. **JD source**: `polyu fetch-and-parse` (if `--polyu-ref`/`--polyu-detail-url`), or `jd-parser` on `--jd-file`, or reuses `--jd-json` as-is.
2. **Config**: `scorer build-config --jd-structured <jd json> --output config.json`.
3. **Extraction**: `cv-parser --file <cv> [--jd-file jd-context.txt] --output extracted-<i>.json` per `--cv`.
4. **Scoring**: `scorer score --extracted extracted-<i>.json --config config.json --output score-<i>.json` per candidate.
5. **Ranking**: candidates sorted by `total_score` descending, `rank` 1..N.
6. **Reports**: `report-gen candidate` PDF one-pager per candidate + `report-gen comparison` Excel across all ranked candidates.

## Engine modes

- **`legacy` (default)**: `scorer build-config` + `scorer score` -> `dimension_scores` + `interview_suggestions`. PDF radar is drawn from `dimension_scores`.
- **`matching`**: `scorer match` per candidate -> the same radar/interview-question detail payload the frontend candidate-match modal shows (`match_score`, `fit_band`, `eligibility`, `evidence_confidence`, `radar_dimensions` with per-dimension reasoning/gaps, `interview_questions`). PDFs render the modal content: radar chart, dimension details, and suggested interview questions. The Excel rows map `core_skill_match` / `relevant_experience` / `education_certification` / `evidence_impact` to the standard comparison columns.
## Output manifest

stdout prints a JSON manifest:

```json
{
  "status": "success",
  "output_dir": ".../data/pipeline_out",
  "jd_source": ".../data/pipeline_out/jd-parse.json",
  "config_json": ".../data/pipeline_out/config.json",
  "candidates": [
    {
      "rank": 1,
      "name": "Alice",
      "source": "cv1.pdf",
      "total_score": 85.2,
      "tier": "Tier 1",
      "extracted_json": "...",
      "score_json": "...",
      "report_pdf": "..."
    }
  ],
  "reports": {"comparison_xlsx": "..."}
}
```

- Intermediate files (`jd-parse.json`, `config.json`, `extracted-*.json`, `score-*.json`, `rows.json`) are kept in `--output-dir` for inspection and re-runs.
- On failure the script prints `{"status": "error", "error_message": "..."}` to stderr and exits 1; on success it exits 0.

## Behavior notes

- Reuses the other skill CLIs as subprocesses (`sys.executable`), so it inherits the venv/python that launched it.
- `--jd-file` text is written to `jd-context.txt` and passed to the cv-parser as JD context.
- `--jd-json` from `polyu fetch-and-parse` supplies its `jd_text` as CV context; from `jd-parser` there is no original text, so no JD context is passed to cv-parser.
- `--polyu-detail-url` is only accepted together with `--polyu-ref` (catalog fallback); it cannot be combined with `--jd-file` or `--jd-json`.
- No DB writes, no REST API calls — this is the offline equivalent of the web demo flow.

## Offline example (no LLM, no network)

```bash
python .codex/skills/pipeline/scripts/run_pipeline.py \
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

## Future migration

TODO(agent-migration): When the legacy REST API is deprecated, merge the shared logic currently in `backend/app/skills/` (and the services it wraps) into this folder so this skill becomes fully self-contained and can be composed into a single integrated agent pipeline.