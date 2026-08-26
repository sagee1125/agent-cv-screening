---
name: scorer
description: "Score an extracted candidate profile against a scoring config (five dimension scores, weighted total, tier, rejection reasons, interview suggestions), build scoring configs from JD parser output, rank candidates, or run the deterministic matching engine (radar + interview questions) by running the project Scorer Python service directly via CLI. Use when: (1) a parsed candidate profile needs scoring, (2) ranking multiple candidates, (3) a scoring config needs to be built from a JD, (4) radar/interview-question matching detail is needed for a report, or (5) a user asks to run the Scorer skill or replicate the /jobs/{id}/score logic offline."
---

# Scorer Skill

Run the project Scorer service directly as a Python script (no HTTP). Deterministic, no LLM.

## Pipeline

JD text → **jd-parser** → `structured_data` → **build-config** → scoring config → **score** → scored candidate.

```bash
# 1. Parse the JD
python .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-file jd.txt --output jd-out.json

# 2. Build the scoring config from the parsed JD (no hand-written config needed)
python .codex/skills/scorer/scripts/run_score.py build-config --jd-structured jd-out.json --output config.json

# 3. Score an extracted candidate profile against that config
#    extracted.json may be the cv-parser --output envelope; the CLI auto-unwraps structured_data.
python .codex/skills/scorer/scripts/run_score.py score --extracted extracted.json --config config.json
```

## Run

### `score` — score an extracted candidate

```bash
python .codex/skills/scorer/scripts/run_score.py score --extracted <extracted.json> --config <config.json> [--rank --items <scored-items.json>] [--output <result.json>]
```

| flag | meaning |
|---|---|
| `--extracted` (required) | JSON file with CV Parser `structured_data` (a full cv-parser envelope is auto-unwrapped) |
| `--config` (required) | JSON file with the scoring config (a build-config envelope is auto-unwrapped) |
| `--rank` (optional) | Also rank a list of scored items |
| `--items` (optional) | JSON file with a list of `{"candidate_id", "total_score"}` items to rank |
| `--output` (optional) | Write JSON to file instead of stdout |

### `build-config` — build a scoring config from a JD

```bash
python .codex/skills/scorer/scripts/run_score.py build-config --jd-structured <jd_structured.json> [--base-config <base.json>] [--output <config.json>]
```

| flag | meaning |
|---|---|
| `--jd-structured` (required) | JD parser full output (contains `structured_data`) or a pure `structured_data` dict; the CLI auto-unwraps the full output |
| `--base-config` (optional) | Base scoring config JSON to merge/override before JD-derived keys are applied |
| `--output` (optional) | Write JSON to file instead of stdout |

Output JSON:

```json
{
  "status": "success",
  "config": { ... scoring config ... }
}
```

- `stdout` always prints the envelope above.
- With `--output <config.json>`, the file contains ONLY the inner scoring config dict (no `status`/`config` wrapper), so it can be passed straight to `score --config <config.json>`.
- The built config fills `required_skills` / `preferred_skills` (from `must_skills` / `preferred_skills`), `target_experience_years`, `target_degrees`, `language_requirements`, `visa_requirement`, `location`, `weights`, and `hard_filters`.
- Only dimensions whose requirements are present in the JD are activated in `weights` (e.g. `language_match`, `work_authorization_match`, `location_match`).
- Feed the `--jd-structured` output of the JD Parser skill directly; the CLI unwraps the `structured_data` key automatically.

### `match` - run the deterministic matching engine (radar + interview questions)

Runs the same pure six-dimension engine the frontend candidate-match modal uses. The output detail payload (`match_score`, `fit_band`, `eligibility`, `evidence_confidence`, `radar_dimensions`, `top_strengths`, `key_gaps`, `interview_questions`) feeds `report-gen candidate --detail` to render the modal-style PDF.

```bash
python .codex/skills/scorer/scripts/run_score.py match --jd-structured <jd_structured.json> --cv-extracted <extracted.json> [--reference-date YYYY-MM-DD] [--output detail.json]
```

| flag | meaning |
|---|---|
| `--jd-structured` (required) | JD parser output (auto-unwrapped) or pure `structured_data` |
| `--cv-extracted` (required) | CV parser output (auto-unwrapped) or pure `structured_data` |
| `--reference-date` (optional) | Reference date used for experience/recency (default: today) |
| `--output` (optional) | Write the raw detail JSON (no envelope) so it feeds `report-gen candidate --detail` |

- Deterministic, no LLM, no DB.
- With `--output`, the file contains ONLY the inner detail dict, ready for `report-gen candidate --detail`.

Example:

```bash
python .codex/skills/scorer/scripts/run_score.py match \
  --jd-structured .codex/skills/scorer/examples/sample-jd-structured.json \
  --cv-extracted .codex/skills/scorer/examples/sample-extracted.json \
  --output detail.json
```
## Scoring config keys

| key | type | default |
|---|---|---|
| `required_skills` | string[] | `[]` |
| `target_experience_years` | number | `0` |
| `target_degrees` | string[] | `[]` |
| `weights` | object | `{skill_match: 0.35, experience_match: 0.2, education_match: 0.15, research_quality: 0.15, experience_quality: 0.15}` |
| `tiers` | `[{name, min_score, max_score}]` | default Tier 1-4 |
| `hard_filters` | object | `{}` — keys: `min_experience_years`, `min_required_skill_hits`, `required_skills`, `required_degrees`, `reference_date` |

## Output JSON

```json
{
  "dimension_scores": {"skill_match": 86.5, "experience_match": 0.0, "education_match": 100.0, "research_quality": 30.0, "experience_quality": 55.0},
  "total_score": 58.7,
  "tier": "Tier 3",
  "rejected": false,
  "rejection_reasons": [],
  "skill_match_details": {"hit": [{"required": "Python", "matched_with": "Python"}], "miss": [], "quality": 0.55},
  "full_snapshot": {"dimension_scores": {...}, "skill_match_details": {...}, "interview_suggestions": [...], "hard_filter_status": "passed"}
}
```

- Dimension scores are 0-100; `total_score` is a weighted 0-100 decimal.
- `rejected` is `true` when a hard filter fails (then `total_score` is `0`).
- With `--rank`, the result is `{"score": {...}, "ranking": [{..., "rank": 1}, ...]}`.

## Behavior notes

- On failure the script prints `{"status": "error", "error_message": "..."}` to stderr and exits 1; on success it exits 0.
- The `score` subcommand auto-unwraps a build-config envelope passed as `--config`, and a CV parser envelope passed as `--extracted` (a pure `structured_data` dict also works).
- Invalid `--extracted` input (no `structured_data`, and no `name`/`skills`/`education`/`experience`/`publications` fields) fails fast with an error envelope (exit 1) instead of scoring an empty profile.
- A flat invocation without a subcommand (just `--extracted`/`--config`) defaults to the `score` subcommand (backward compatible).
- `build-config` fails fast with an error envelope (exit 1) when the JD input is invalid (e.g. `structured_data` is null, or no usable JD requirement fields).
- The REST endpoint `POST /api/v1/jobs/{job_id}/score` runs the exact same code path.

## Example

See `examples/sample-extracted.json`, `examples/sample-config.json`, and `examples/sample-output.json` in this skill folder; reproduce with:

```bash
python .codex/skills/scorer/scripts/run_score.py score --extracted .codex/skills/scorer/examples/sample-extracted.json --config .codex/skills/scorer/examples/sample-config.json
```

`examples/sample-jd-structured.json` is the `structured_data` from the JD Parser sample output; build a config from it with:

```bash
python .codex/skills/scorer/scripts/run_score.py build-config --jd-structured .codex/skills/scorer/examples/sample-jd-structured.json
```

## Ownership

`src/scorer/` is the source of truth (legacy scorer, skill matcher, candidate matching). REST re-exports the same functions.
