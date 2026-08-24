---
name: cv-screening-agent
description: "Orchestrate end-to-end CV screening for HR: source a JD (PolyU ref, pasted text, or file), parse requirements, build a scoring config, batch-parse CVs, rank candidates, and export PDF/Excel reports. Use when HR asks to screen candidates, import a PolyU job, rank CVs, explain a score, or export a shortlist. Delegates all parsing/scoring to existing skills under .codex/skills/."
---

# CV Screening Agent (Orchestrator)

Top-level agent that plans and runs the screening pipeline by calling existing skill CLIs. Configuration lives in `orchestrator.yaml`; step-by-step CLI mapping and envelope contracts live in `workflows/screen-job.yaml`.

## Prerequisites

- Run every command from the **repository root**.
- Backend deps installed: `pip install -r backend/requirements.txt`
- `.env` at repo root with `ZAI_API_KEY` and `LLM_BASE_URL` (required for `cv-parser` only).
- JD parsing uses `jd-parser` (default `rule` mode = no LLM); PolyU import needs HTTPS to `jobs.polyu.edu.hk`.

## Configuration files

| File | Purpose |
|------|---------|
| `orchestrator.yaml` | Skills registry, state machine, checkpoints, intents, guardrails |
| `workflows/screen-job.yaml` | Full pipeline with CLI commands and envelope formats per step |
| `workflows/import-polyu.yaml` | PolyU catalog / fetch only |
| `workflows/explain-candidate.yaml` | Read-only score explanation |
| `workspace.schema.json` | `workspace.state.json` JSON Schema |

## Job workspace layout

Create one folder per screening job under `data/agent-workspaces/{workspace_id}/`:

```
data/agent-workspaces/{workspace_id}/
  workspace.state.json      # orchestrator state (see workspace.schema.json)
  agent.audit.jsonl         # append-only action log
  jd.raw.txt                # raw JD text
  jd.structured.json        # jd-parser or polyu fetch-and-parse output
  scoring.config.json       # inner config dict from build-config --output
  cvs/
    {stem}.extracted.json   # cv-parser output per candidate
    parse-failures.json     # failed CV parses (optional)
  scores/
    {stem}.score.json       # scorer output per candidate
    rank-items.json         # [{candidate_id, total_score}] — agent-built
    ranking.json            # {score, ranking} from scorer --rank
    comparison-rows.json    # report-gen rows — agent-built
  reports/
    shortlist.xlsx
    {stem}.report.pdf
```

Use `examples/workspace.state.example.json` as a starting template.

## When to pause (mandatory checkpoints)

1. **After JD parse** (`checkpoint_jd_review`): ALWAYS show `must_skills`, `preferred_skills`, language/education/visa requirements, and provenance summary. Wait for HR `confirm` before `build-config`.
2. **After build-config** (`checkpoint_config_review`): ALWAYS show `weights`, `hard_filters`, `required_skills`. Wait for HR `confirm` before parsing any CVs.
3. **Before batch CV parse** (if >5 uncached files): warn HR about estimated LLM API usage.
4. **Weight changes** (`intent: weight`): require explicit HR confirmation before rewriting `scoring.config.json` and re-scoring.

## How to run the full pipeline

### Option A — workflow runner (recommended)

```bash
# JD only (validate parse + config, no LLM for CVs)
python .codex/agents/cv-screening-agent/scripts/run_screen_job.py \
  --workspace data/agent-workspaces/demo \
  --job-source jd_file \
  --jd-file .codex/skills/jd-parser/examples/sample-jd.txt \
  --position-title "Backend Engineer" \
  --yes --jd-only

# Full run with CVs + Excel export
python .codex/agents/cv-screening-agent/scripts/run_screen_job.py \
  --workspace data/agent-workspaces/demo \
  --job-source jd_file \
  --jd-file .codex/skills/jd-parser/examples/sample-jd.txt \
  --cv path/to/cv1.pdf --cv path/to/cv2.pdf \
  --position-title "Backend Engineer" \
  --yes --export --export-pdf 3

# PolyU source
python .codex/agents/cv-screening-agent/scripts/run_screen_job.py \
  --workspace data/agent-workspaces/polyu-260818008-IE \
  --job-source polyu_ref \
  --polyu-ref 260818008-IE \
  --cv uploads/cv.pdf \
  --yes --export
```

Flags:

| Flag | Meaning |
|------|---------|
| `--yes` | Auto-confirm JD and config checkpoints |
| `--jd-only` | Stop after `build-config` (no CV parse) |
| `--export` | Write `reports/shortlist.xlsx` after ranking |
| `--export-pdf N` | Write PDF one-pagers for top N candidates |

### Option B — manual skill CLI chain

Follow `workflows/screen-job.yaml` in order. Quick copy-paste (replace paths):

```bash
WORKSPACE=data/agent-workspaces/demo
mkdir -p "$WORKSPACE"/{cvs,scores,reports}

# A) PolyU source
python .codex/skills/polyu-import/scripts/run_polyu_import.py fetch-and-parse \
  --external-ref 260818008-IE --output "$WORKSPACE/jd.structured.json"
# Also save jd_text → $WORKSPACE/jd.raw.txt from output field

# B) Or JD text source
python .codex/skills/jd-parser/scripts/run_jd_parse.py \
  --jd-file "$WORKSPACE/jd.raw.txt" --output "$WORKSPACE/jd.structured.json"

# ── CHECKPOINT: HR confirms JD ──

python .codex/skills/scorer/scripts/run_score.py build-config \
  --jd-structured "$WORKSPACE/jd.structured.json" \
  --output "$WORKSPACE/scoring.config.json"

# ── CHECKPOINT: HR confirms config ──

python .codex/skills/cv-parser/scripts/run_cv_parse.py \
  --file path/to/cv.pdf --jd-file "$WORKSPACE/jd.raw.txt" \
  --output "$WORKSPACE/cvs/alice.extracted.json"

python .codex/skills/scorer/scripts/run_score.py score \
  --extracted "$WORKSPACE/cvs/alice.extracted.json" \
  --config "$WORKSPACE/scoring.config.json" \
  --output "$WORKSPACE/scores/alice.score.json"

# Build rank-items.json (agent writes this — see screen-job.yaml step build_rank_items)
# [{"candidate_id": "alice", "total_score": 58.7}, ...]

python .codex/skills/scorer/scripts/run_score.py score \
  --extracted "$WORKSPACE/cvs/alice.extracted.json" \
  --config "$WORKSPACE/scoring.config.json" \
  --rank --items "$WORKSPACE/scores/rank-items.json" \
  --output "$WORKSPACE/scores/ranking.json"

# Build comparison-rows.json (agent writes — see screen-job.yaml step build_comparison_rows)
# See .codex/skills/report-gen/examples/sample-comparison-rows.json

python .codex/skills/report-gen/scripts/run_report.py comparison \
  --position "Job Title" \
  --rows "$WORKSPACE/scores/comparison-rows.json" \
  --output "$WORKSPACE/reports/shortlist.xlsx"
```

## Envelope unwrapping rules (fail-fast)

These match `backend/tests/unit/test_skill_cli_compat.py`:

| Step | Input flag | Accepts | Unwrap behavior |
|------|------------|---------|-----------------|
| `build-config` | `--jd-structured` | jd-parser output, polyu `fetch-and-parse`, pure `structured_data` | `jd_parse.structured_data` → `structured_data` → requirement fields |
| `score` | `--config` | raw config or `{status, config}` | inner `config` when `status==success` |
| `score` | `--extracted` | cv-parser envelope or pure profile | inner `structured_data` |
| `score --rank` | `--items` | JSON array | `[{candidate_id, total_score}, ...]` |
| `report-gen candidate` | `--score` | plain score or `{score, ranking}` | top-level `score` key |
| `report-gen candidate` | `--extracted` | cv-parser envelope | inner `structured_data` |

On any skill failure: stderr prints `{"status":"error","error_message":"..."}` and exit code is `1`.

## How to explain scores

- Read `scores/{stem}.score.json` — never invent reasons.
- Quote `skill_match_details.hit` / `.miss`, `dimension_scores`, and `full_snapshot.interview_suggestions`.
- For comparisons, read two score files and diff `dimension_scores` only.
- Do not use protected characteristics (gender, age, ethnicity, photo).

## Error handling

| Failure | Action |
|---------|--------|
| PolyU fetch fails | Ask HR to paste JD text; switch to `source_jd_text` branch |
| JD parse partial | Ask closed-option clarification; do not proceed to build-config until `structured_data` has requirements |
| CV parse fails (one file) | Record in `cvs/parse-failures.json`; continue other files |
| CV parse fails (all files) | Stop; report failures; do not run scorer |
| build-config invalid input | Show `error_message`; ask HR to fix JD or reparse |

## Audit log

Append one JSON line per action to `agent.audit.jsonl`:

```json
{"ts":"2026-08-24T06:00:00Z","actor":"agent","action":"skill_invoke","skill":"jd-parser","input_hash":"abc","output":"jd.structured.json","state_before":"jd_sourced","state_after":"jd_parsed"}
```

Never log email, phone, or raw CV text.

## REST API mode

When HR uses the React frontend, prefer `execution_modes.api` mappings in `orchestrator.yaml` instead of CLI. The same `backend/app/skills/*` functions power both paths.

## Related skills

Delegate to these skills — do not reimplement their logic:

- `$skill-polyu-import` — PolyU catalog / JD fetch
- `$skill-jd-parser` — JD → structured requirements
- `$skill-scorer` — build-config, score, rank
- `$skill-cv-parser` — PDF → structured profile
- `$skill-report-gen` — PDF one-pager / Excel comparison
