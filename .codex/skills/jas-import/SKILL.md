---
name: jas-import
description: "Parse internal PolyU JAS records pages into JD text and appno-keyed CV references, either from HR-exported HTML or allowlisted authenticated URLs."
---

# JAS Import Skill

Parse the internal PolyU Job Application System (JAS) HTML pages into structured JSON, without pulling candidate identity fields into the pipeline.

## PII boundary

- The candidate table contains identity data (name, email, phone, HKID, salary, relationship/criminal declarations).
- This skill **drops those columns by design** and returns only what the pipeline needs: `appno`, HR `status`, and file URLs (`cv_url`, `supp_url`, `record_detail_url`).
- The JD block (`Job advertisement information`) is the only textual content passed downstream.

## Prerequisites

- Python 3.10+ (`httpx` is required for optional live URL mode).
- Run all commands from the repository root so `_bootstrap.py` can locate `screening_core` and the skill packages.

## Run

### `parse-list` — parse the records list page

```bash
python .codex/skills/jas-import/scripts/run_jas_import.py parse-list --html-file <list.html> [--base-url URL] [--output catalog.json]
```

Output:

```json
{
  "status": "success",
  "source": "jas",
  "total": 1,
  "items": [
    {
      "refno": "190001010",
      "job_group": "Research / Project Posts",
      "unit": "Institute for Higher Education Research and Development",
      "post_title": "Project Associate",
      "posting_date": "1900-01-01",
      "closing_date": "1900-01-01",
      "off_shelf_date": "1900-01-01",
      "list_type": "External Advertisement",
      "application_count": "01",
      "records_url": "https://jobs.polyu.edu.hk/internal/records.php?refno=190001010"
    }
  ]
}
```

### `parse-job` — parse one job-detail page

```bash
python .codex/skills/jas-import/scripts/run_jas_import.py parse-job --html-file <records.html> [--base-url URL] [--output job.json]
```

Output:

```json
{
  "status": "success",
  "source": "jas",
  "refno": "190001010",
  "job": {
    "refno": "190001010",
    "job_group": "Research / Project Posts",
    "unit": "Institute for Higher Education Research and Development",
    "post_title": "Project Associate",
    "appointment_period": null,
    "project_title": null,
    "posting_date": "1900-01-01",
    "list_type": "External Advertisement"
  },
  "jd_text": "Reference number: 190001010\n...\nDescription: ...",
  "candidates": [
    {
      "appno": "123456",
      "status": "TBC",
      "cv_url": "https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=123456&refno=190001010",
      "supp_url": null,
      "record_detail_url": "https://jobs.polyu.edu.hk/internal/record_detail.php?id=123456&refno=190001010"
    }
  ]
}
```

## Behavior notes

- On failure the script prints `{"status": "error", "error_message": "..."}` to stderr and exits 1; on success it exits 0.
- `parse-list` and `parse-job` are local and synchronous; live network access is isolated to `run_jas_screening.py --records-url`.
- `jd_text` is built from the `Job advertisement information` table rows in order, so it can be fed directly into the `jd-parser` skill.
- `cv_url` / `record_detail_url` are resolved against `--base-url` (default `https://jobs.polyu.edu.hk`).
- The candidate `status` is inferred as the plain-text label among TBC / P / S / N; clickable status labels are treated as actions and ignored.
- Candidate rows with no `Application no.` are skipped from the result.

## Pipeline with other skills

JAS JD text feeds the same downstream chain as the public `polyu-import` path:

```bash
# 1. Parse an HR-exported job-detail page
python .codex/skills/jas-import/scripts/run_jas_import.py parse-job --html-file records.html --output jas-job.json

# 2. Parse the JD into structured requirements (jd-parser skill)
python .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-text "$(cat jas-job.json | jq -r .jd_text)" --output jd-structured.json

# 3. Download each CV (later phase) into data/jas_scratch/<refno>/<refno>_<appno>.pdf,
#    then feed those PDFs to cv-parser / scorer / report-gen exactly like public CVs.
```

> Direct import commands remain offline. Live records/CV fetch is available through the allowlisted URL mode described below.

## Ownership

Domain parsing logic lives in `src/jas_import/`; the CLI script only wraps it.

## Offline screening without internal access

No JAS login is required when HR exports the pages and CVs. Use the offline orchestrator:

```bash
# Folder layout expected by the orchestrator
#   <jas-dir>/
#       records.html                (saved records.php?refno=... page)
#       cvs/123456.pdf              (CV PDFs named by Application no.)
#       cvs/190001010_654321.pdf    (optional refno_ prefix is stripped)

python .codex/skills/jas-import/scripts/run_jas_screening.py \
  --jas-dir <jas-dir> \
  --output-dir data/jas_out \
  [--engine matching] [--skip-reports]
```

- Parses the JD from `records.html`, delegates to the `pipeline` skill for
  JD parse -> build-config -> cv parse -> score/rank -> reports.
- Writes `jd.txt`, `jas-manifest.json` (appno + status + cv_path only, no PII)
  and the pipeline manifest into `--output-dir`.
- Exit codes: `0` success/partial_success, `1` pipeline error, `2` need_input
  (missing `records.html` or CVs).
- `candidates_without_cv` in `jas-manifest.json` lists appnos from the records
  page that have no matching CV file, so HR can be asked to export them.
- When some CV downloads fail in URL mode, `download_failures` is included in
  `jas-manifest.json` and the stdout JSON envelope even if screening continues.

### What HR needs to do (no technical skills)

1. Open the internal job record page (`records.php?refno=...`).
2. Save the page as HTML (`Ctrl+S` -> "Webpage, HTML only") into a folder.
3. Download each CV from the applicant table and save it as `<Application no.>.pdf`
   into a `cvs/` subfolder (e.g. `cvs/123456.pdf`).
4. Hand the folder to the agent. The agent never needs JAS login.


## Live URL mode (--records-url, Phase 1 skeleton)

When internal access (or an HR-run session with a cookie jar) is available:

```bash
python .codex/skills/jas-import/scripts/run_jas_screening.py \
  --records-url "https://jobs.polyu.edu.hk/internal/records.php?refno=260818001" \
  --cookie-file data/jas_cookies.txt
```

- Fetches the records page, parses it into JD text + candidate references
  (identity columns are dropped at parse time).
- Automatically downloads every candidate CV into
  `data/jas_scratch/<refno>/<appno>.pdf` (private, appno-keyed).
- Runs the same pipeline tail (JD parse -> cv parse -> score/rank -> reports).
- **Downloaded CVs are deleted after the run by default**; pass `--keep-cvs`
  to retain them for inspection.
- `--cookie-file` reads a Netscape `cookies.txt` on disk; cookies are never
  accepted as CLI arguments.
- The records URL host must be allowlisted (`jobs.polyu.edu.hk`), enforced by
  the input policy before any fetch.
- This skeleton is unit-tested with mocks; it cannot be validated against the
  real JAS until internal access is granted.
