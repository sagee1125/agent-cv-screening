---
name: polyu-import
description: "Fetch PolyU job listings and job detail pages into plain JD text (optionally parse JD) by running the project PolyU import service directly via CLI. Use when: (1) importing jobs from jobs.polyu.edu.hk, (2) bootstrapping JD text for jd-parser, or (3) one-click job catalog sync without the REST API."
---

# PolyU Import Skill

Fetch PolyU job listings (catalog) and individual job detail pages as plain JD text, optionally parsing the JD, by running the project PolyU import service directly as a Python script (no HTTP API, no DB writes).

## Prerequisites

- Network access to `https://jobs.polyu.edu.hk` (the public PolyU jobs board).
- `httpx` is already in `backend/requirements.txt`.
- Run all commands from the repository root so `_bootstrap.py` can locate `backend/app`.

## Run

### `catalog` — fetch the job catalog

```bash
python .codex/skills/polyu-import/scripts/run_polyu_import.py catalog [--output catalog.json]
```

Output:

```json
{
  "status": "success",
  "source": "polyu",
  "total": 42,
  "items": [
    {
      "job_code": "260818008",
      "external_ref": "260818008-IE",
      "title": "Assistant Officer",
      "department": "Office of Faculty of Science",
      "closing_date": "2026-08-24T00:00:00",
      "detail_url": "https://jobs.polyu.edu.hk/job_detail.php?job=260818008"
    }
  ]
}
```

- `closing_date` is an ISO-8601 string or `null`.

### `fetch` — fetch one job detail page as JD text

```bash
python .codex/skills/polyu-import/scripts/run_polyu_import.py fetch \
  [--external-ref REF] \
  [--detail-url URL] \
  [--job-code CODE --title TITLE --department DEPT] \
  [--output job.json]
```

At least one of `--external-ref` / `--detail-url` is required.

- With `--external-ref`, the CLI first fetches the catalog to find the matching listing.
- If the catalog does not contain the ref and `--detail-url` is given, a minimal listing is built from the URL (job code parsed from the query string).
- If the ref is not in the catalog and no `--detail-url` is given, the command errors (exit 1) with `external_ref not found in catalog; provide --detail-url as fallback`.
- Output includes `external_ref`, `title`, `department`, `detail_url`, `posting_date`, and `jd_text` (full description).

### `fetch-and-parse` — fetch and parse one job

```bash
python .codex/skills/polyu-import/scripts/run_polyu_import.py fetch-and-parse \
  [--external-ref REF | --detail-url URL] \
  [--output result.json]
```

Output combines fetch metadata with the JD parser result:

```json
{
  "status": "success",
  "source": "polyu",
  "external_ref": "...",
  "title": "...",
  "jd_text": "...",
  "structured_data": { "...": "same as jd_parse.structured_data" },
  "jd_parse": { "...": "full parse_jd_skill output" }
}
```

- `structured_data` mirrors `jd_parse.structured_data` at the top level so the file can be fed straight into `scorer build-config --jd-structured`.
- Use `--mode rule|hybrid|qwen` to choose the JD parser mode (defaults to `settings.jd_parser_mode`).

## Behavior notes

- On failure (network error, missing ref/url, parse failure) the script prints `{"status": "error", "error_message": "..."}` to stderr and exits 1; on success it exits 0.
- `fetch-and-parse` fails fast (exit 1) when the JD parser returns a non-`success` status or `structured_data` is not a dict — it never returns a top-level `success` for a failed parse.
- An `--external-ref` not found in the catalog requires a `--detail-url` fallback, otherwise the command errors with exit 1.
- No DB writes: the skill never persists listings or jobs.
- `httpx` network errors are surfaced as-is so the agent can decide whether to retry.

## Pipeline with other skills

PolyU JD text feeds directly into the JD parser and the rest of the screening pipeline:

> Tip: you can also run the whole chain in one command with the `pipeline` skill (`.codex/skills/pipeline`).

```bash
# 1. Fetch + parse one PolyU job into structured JD requirements
python .codex/skills/polyu-import/scripts/run_polyu_import.py fetch-and-parse --external-ref <REF> --output polyu-parsed.json

# 2. Build a scoring config from the parsed JD (scorer skill)
python .codex/skills/scorer/scripts/run_score.py build-config --jd-structured polyu-parsed.json --output config.json

# 3. Parse a candidate CV (cv-parser skill) -> score -> report (report-gen skill)
python .codex/skills/cv-parser/scripts/run_cv_parse.py --file cv.pdf --output extracted.json
python .codex/skills/scorer/scripts/run_score.py score --extracted extracted.json --config config.json --output score.json
python .codex/skills/report-gen/scripts/run_report.py candidate --extracted extracted.json --score score.json --position "..." --output report.pdf
```

`build-config --jd-structured` accepts any of:
- the whole `polyu-parsed.json` (its top-level `structured_data`, or `jd_parse.structured_data`, is auto-unwrapped),
- the jd-parser full output, or
- a pure `structured_data` dict.

Full pipeline: `polyu fetch-and-parse → scorer build-config → cv-parse → score → report-gen`.

## Example

`examples/sample-catalog-item.json` is a static catalog item (no network needed) showing the listing shape:

```json
{
  "job_code": "260818008",
  "external_ref": "260818008-IE",
  "title": "Assistant Officer",
  "department": "Office of Faculty of Science",
  "closing_date": "2026-08-24T00:00:00",
  "detail_url": "https://jobs.polyu.edu.hk/job_detail.php?job=260818008"
}
```

## Ownership

`src/polyu_import/` is the source of truth for fetch/catalog. CLI JD parse is rule-only; REST `fetch_and_parse` may still apply hybrid/qwen.
