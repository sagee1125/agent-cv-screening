---
name: scorer
description: "Score an extracted candidate profile against a scoring config (five dimension scores, weighted total, tier, rejection reasons, interview suggestions) and rank candidates by running the project Scorer Python service directly via CLI. Use when: (1) a parsed candidate profile needs scoring, (2) ranking multiple candidates, or (3) a user asks to run the Scorer skill or replicate the /jobs/{id}/score logic offline."
---

# Scorer Skill

Run the project Scorer service directly as a Python script (no HTTP). Deterministic, no LLM.

## Run

```bash
python .codex/skills/scorer/scripts/run_score.py --extracted <extracted.json> --config <config.json> [--rank --items <scored-items.json>] [--output <result.json>]
```

| flag | meaning |
|---|---|
| `--extracted` (required) | JSON file with CV Parser `structured_data` |
| `--config` (required) | JSON file with the scoring config |
| `--rank` (optional) | Also rank a list of scored items |
| `--items` (optional) | JSON file with a list of `{"candidate_id", "total_score"}` items to rank |
| `--output` (optional) | Write JSON to file instead of stdout |

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
- The REST endpoint `POST /api/v1/jobs/{job_id}/score` runs the exact same code path.

## Example

See `examples/sample-extracted.json`, `examples/sample-config.json`, and `examples/sample-output.json` in this skill folder; reproduce with:

```bash
python .codex/skills/scorer/scripts/run_score.py --extracted .codex/skills/scorer/examples/sample-extracted.json --config .codex/skills/scorer/examples/sample-config.json
```

## Future migration

TODO(agent-migration): When the legacy REST API (traditional frontend) is deprecated, merge the shared logic currently in `backend/app/skills/` (and the services it wraps) into this folder so this skill becomes fully self-contained and can be composed into a single integrated agent pipeline.
