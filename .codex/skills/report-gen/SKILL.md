---
name: report-gen
description: "Generate candidate PDF one-pager or Excel comparison reports from parsed CV data and scorer output by running the project Reporter service directly via CLI. Use when: (1) a scored candidate needs a PDF report, (2) multiple ranked candidates need an Excel comparison, or (3) completing the agent pipeline after scoring."
---

# Report Generator Skill

Generate a candidate PDF report with a radar profile, dimension details, and suggested interview questions (mirroring the frontend candidate-match modal), or an Excel comparison report for multiple ranked candidates, by running the project Reporter service directly as a Python script (no HTTP, no DB).

## Prerequisites

Install the backend Python dependencies from the repository root:

```bash
pip install -r backend/requirements.txt
```

Run all commands from the repository root so `_bootstrap.py` can locate `backend/app`.

## Pipeline

JD text → **jd-parser** → **build-config** → **score** → **report-gen** → PDF / Excel.

```bash
# 1. Score a candidate (scorer skill)
python .codex/skills/scorer/scripts/run_score.py score \
  --extracted extracted.json --config config.json --output score.json

# 2. Generate the candidate PDF one-pager
python .codex/skills/report-gen/scripts/run_report.py candidate \
  --extracted extracted.json --score score.json --position "Backend Engineer" --rank 1 --output candidate-report.pdf

# 3. Generate the Excel comparison (ranked rows)
python .codex/skills/report-gen/scripts/run_report.py comparison \
  --position "Backend Engineer" --rows rows.json --output comparison.xlsx
```

## Run

### `candidate` — one-page PDF report

```bash
python .codex/skills/report-gen/scripts/run_report.py candidate \
  --extracted <extracted.json> \
  --score <score.json> \
  --position "<job title>" \
  [--name "Override Name"] \
  [--rank 1] \
  --output <report.pdf>
```

| flag | meaning |
|---|---|
| `--extracted` (required) | JSON file with CV Parser `structured_data` (name, education, experience) |
| `--score` (optional) | JSON file with Scorer output (`total_score`, `tier`, `dimension_scores`, `skill_match_details`, `full_snapshot`); a ranked `{"score": {...}, "ranking": [...]}` envelope is auto-unwrapped. Required when `--detail` is not given |
| `--detail` (optional) | Matching-engine detail JSON (radar_dimensions, interview_questions, eligibility, evidence_confidence, fit_band, top_strengths, key_gaps) — the same payload the frontend candidate-match modal shows. When given, the PDF renders a radar chart + dimension details + suggested interview questions |
| `--position` (required) | Job position name shown on the report |
| `--name` (optional) | Override candidate name; defaults to `extracted_data.name` or `Unknown` |
| `--rank` (optional) | Candidate rank shown on the report (default `0`) |
| `--output` (required) | Path to write the PDF report file |

### `comparison` — Excel comparison report

```bash
python .codex/skills/report-gen/scripts/run_report.py comparison \
  --position "<job title>" \
  --rows <rows.json> \
  --output <report.xlsx>
```

| flag | meaning |
|---|---|
| `--position` (required) | Job position name shown on the report |
| `--rows` (required) | JSON file with a list of ranked candidate rows |
| `--output` (required) | Path to write the XLSX report file |

## Input JSON fields

### `--score` (candidate)

- `total_score` (number), `tier` (string)
- `dimension_scores` (object) — `skill_match` is used as the hit rate (same as the REST endpoint)
- `skill_match_details` (object) — `hit` / `miss` arrays (or `full_snapshot.skill_match_details`)
- `full_snapshot.interview_suggestions` (array) — or top-level `interview_suggestions`

### `--detail` (candidate, optional)

Matching-engine output (from `scorer match` or the REST match-detail endpoint):

- `match_score` (number), `fit_band` (string), `evidence_confidence` (number)
- `radar_dimensions` (array) - each with `label`, `score` (or null), `status`, `normalized_weight`, `reasoning.summary`, `gaps[]`
- `interview_questions` (array) - each with `question`, `priority`, `template_id`
- `eligibility` (object) - `status` + `results[]`
- `top_strengths` / `key_gaps` (string arrays)

When `--detail` is given, the PDF shows the frontend modal content: radar chart, dimension details (score/status/weight/reasoning/gaps), and suggested interview questions. Without it, the PDF falls back to the scorer `dimension_scores` radar and `interview_suggestions`.
### `--rows` (comparison)

Each row uses the same fields as the REST `/reports/comparison` endpoint:

`rank`, `name`, `total_score`, `skill_match`, `experience_match`, `education_match`, `research_quality`, `tier`, `suggestion_summary`

## Output

- stdout prints a JSON result: `{"status": "success", "format": "pdf" | "excel", "output_path": "..."}`
- `--output` is the report file path (`.pdf` / `.xlsx`), not a JSON path
- On failure the script prints `{"status": "error", "error_message": "..."}` to stderr and exits 1; on success it exits 0

## Integration with the Scorer skill

Feed the Scorer skill output directly as `--score`:

- Without `--rank`: `run_score.py score --output score.json` writes a plain score object (`total_score`, `dimension_scores`, `skill_match_details`, `full_snapshot`) that works as-is.
- With `--rank`: the scorer writes `{"score": {...}, "ranking": [...]}`; the report-gen CLI auto-unwraps the top-level `score` key before generating the PDF.
- `--extracted` may also be a CV Parser full output; its `structured_data` dict is auto-unwrapped.
- Invalid score input (no `total_score`, and no `full_snapshot.dimension_scores`) fails fast: the CLI prints `{"status": "error", "error_message": "..."}` to stderr and exits 1 — no silent zero-score PDF.

## Example

```bash
python .codex/skills/report-gen/scripts/run_report.py candidate \
  --extracted .codex/skills/report-gen/examples/sample-extracted.json \
  --score .codex/skills/report-gen/examples/sample-score.json \
  --position "Backend Engineer" --rank 1 --output /tmp/candidate-report.pdf

python .codex/skills/report-gen/scripts/run_report.py comparison \
  --position "Backend Engineer" \
  --rows .codex/skills/report-gen/examples/sample-comparison-rows.json \
  --output /tmp/comparison.xlsx
```

## Ownership

`src/report_gen/` is the source of truth. REST re-exports the same report functions.
