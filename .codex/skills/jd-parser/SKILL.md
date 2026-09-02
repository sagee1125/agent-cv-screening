---
name: jd-parser
description: "Parse job description (JD) text into structured requirement data (must_skills, preferred_skills, language, education, visa, experience requirements) by running the project JD Parser Python service directly via CLI. Use when: (1) a JD needs parsing into structured skills/requirements, (2) preparing scoring config from a JD, or (3) a user asks to run the JD Parser skill or replicate the /jobs parse-jd logic offline."
---

# JD Parser Skill

Run the project JD Parser service directly as a Python script (no HTTP). Rule-based, deterministic, no LLM.

## Run

```bash
venv/Scripts/python.exe .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-file <jd.txt>
venv/Scripts/python.exe .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-text "<jd text>"
```

| flag | meaning |
|---|---|
| `--jd-file` or `--jd-text` (one required) | Source JD text |
| `--output` (optional) | Write JSON to file instead of stdout |

## Output JSON

```json
{
  "status": "success",
  "parse_path": "jd_preprocessed_rule_parser",
  "error_message": null,
  "structured_data": {
    "must_skills": [{"skill_id": "python_1", "display_name": "Python", "canonical_skill": "python", "priority_order": 1, "weight": 1.0, "provenance": {"source_sentence": "...", "source_char_start": 0, "source_char_end": 42, "confidence": 0.75}}],
    "preferred_skills": [],
    "language_requirements": [{"language": "English", "level": "business", "is_mandatory": false, "provenance": "..."}],
    "education_requirement": {"minimum_degree": "bachelor", "field_of_study": null, "is_mandatory": true, "provenance": "..."},
    "visa_requirement": {"requirement_type": "unknown", "target_region": null, "provenance": "..."},
    "experience_requirement": {"minimum_years": 3}
  },
  "raw_llm_response": {"preprocessed_for_llm": {...}, "llm_refine_request": {...}}
}
```

- `status` is `"success"` or `"invalid_input"` (empty JD); empty input also sets `structured_data` to `null`.
- `must_skills` and `preferred_skills` each hold at most 5 items.
- Feed `must_skills`/`preferred_skills` display names into the Scorer skill `config.required_skills` when building scoring configs.

## Behavior notes

- On failure the script prints `{"status": "error", "error_message": "..."}` to stderr and exits 1; on success it exits 0.
- The REST endpoints `POST /api/v1/jobs` and `POST /api/v1/jobs/{id}/parse-jd` share the same rule parser. Hybrid/qwen LLM enrichment stays on the REST adapter only.

## Example

See `examples/sample-jd.txt` and `examples/sample-output.json` in this skill folder; reproduce with:

```bash
venv/Scripts/python.exe .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-file .codex/skills/jd-parser/examples/sample-jd.txt
```

## Ownership

`src/jd_parser/` is the rule-parser source of truth. `backend/app/services/jd_parser/providers/` keeps hybrid/qwen LLM backup for REST.
