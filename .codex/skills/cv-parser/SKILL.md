---
name: cv-parser
description: "Parse a candidate CV/PDF into structured candidate data (name, email, phone, skills, education, experience, publications) by running the project CV Parser Python service directly via CLI. Use when: (1) a resume/CV file needs parsing into structured JSON, (2) re-parsing an existing resume, (3) extracting candidate profile fields for later scoring, or (4) a user asks to run the CV Parser skill or replicate the /candidates/upload parsing logic offline."
---

# CV Parser Skill

Run the project CV Parser service directly as a Python script (no HTTP).

## Prerequisites

- Python dependencies: `venv/Scripts/python.exe -m pip install -r backend/requirements.txt` (parser still uses the same packages).
- `.env` at repo root with `ZAI_API_KEY` and `LLM_BASE_URL` (the parser calls the Zhipu LLM).
- Run every command from the repository root.

The parser implementation lives in this skill (`src/cv_parser/`), not in `backend/`. Shared LLM/settings/taxonomy code is `.codex/skills/_shared/src/screening_core/`. FastAPI re-exports the same functions.

## Run

```bash
venv/Scripts/python.exe .codex/skills/cv-parser/scripts/run_cv_parse.py --file <path-to-cv.pdf> [--jd-file <jd.txt> | --jd-text "<jd text>"] [--output <result.json>]
```

| flag | meaning |
|---|---|
| `--file` (required) | Path to the CV PDF |
| `--jd-file` / `--jd-text` (optional) | JD context that improves parsing |
| `--output` (optional) | Write JSON to file instead of stdout |

## Output JSON

```json
{
  "file_hash": "md5 of the CV",
  "cache_hit": false,
  "status": "success",
  "parse_path": "vision | vision_focus | text_fallback | rule_fallback",
  "structured_data": {
    "name": "Alice",
    "email": "alice@example.com",
    "phone": null,
    "skills": ["Python", "FastAPI"],
    "education": [{"school": "NTU", "degree": "MSc", "major": "CS", "period": "2020-2023"}],
    "experience": [{"company": "Acme", "job_title": "Engineer", "period": "2021-01 - 2024-01", "description": "..."}],
    "publications": [{"title": "...", "journal": "IEEE", "year": "2023"}]
  },
  "raw_llm_response": {...} | null,
  "extraction_model": "glm-4v-flash",
  "extraction_seed": 42,
  "error_message": null
}
```

- `status` is `"success"` or `"fallback"`; `error_message` is non-null only on fallback.
- `structured_data` is what the Scorer skill consumes as `--extracted`.

## Behavior notes

- Results cache under `./data/cache` keyed by file MD5; re-parsing the same file returns cached output.
- On failure the script prints `{"status": "error", "error_message": "..."}` to stderr and exits 1; on success it exits 0.
- The REST endpoint `POST /api/v1/candidates/upload` runs the exact same code path.

## Example

Run the bundled `examples/sample-cv.pdf`:

```bash
venv/Scripts/python.exe .codex/skills/cv-parser/scripts/run_cv_parse.py --file .codex/skills/cv-parser/examples/sample-cv.pdf
```

Parsing requires the live LLM, so no sample output is bundled; the first run prints the result to stdout (or write it with `--output`).

## Ownership

`src/cv_parser/` is the source of truth. `backend/app/services/cv_parser` and `backend/app/skills/cv_parse.py` re-export the same functions for the REST API.
