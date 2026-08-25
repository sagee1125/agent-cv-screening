---
name: screening-agent
description: "Run screening orchestration on top of the pipeline skill: L1 rule loop (need_input, partial retry, resume) or an LLM planner that only chooses run/resume/ask/finish. Scoring stays deterministic."
---

# Screening Agent Skill (L1 + LLM planner)

Two modes share the same pipeline / scorer path (no LLM scoring):

- **`--planner rules` (default):** deterministic L1 loop — validate input, retry partial failures with `--resume`, persist `agent-state.json`.
- **`--planner llm`:** an LLM chooses allowlisted tools (`run_screening`, `resume_run`, `ask_user`, `get_run_status`, `finish`). File paths still come from CLI flags; the model cannot change weights or scores.

## Prerequisites

- Python packages: `pip install -r backend/requirements.txt`.
- `.env` at repo root with `ZAI_API_KEY` and `LLM_BASE_URL` for `--planner llm` and for CV parsing.
- Run commands from the repository root. Planner LLM uses `screening_core.llm_client` (`.codex/skills/_shared`), not `backend/app`.

## Run (L1 rules, default)

```bash
python .codex/skills/screening-agent/scripts/run_agent.py \
  --jd-file jd.txt \
  --cv cv1.pdf --cv cv2.pdf \
  --position "Backend Engineer" \
  --output-dir data/pipeline_out
```

## Run (LLM planner)

```bash
python .codex/skills/screening-agent/scripts/run_agent.py \
  --planner llm \
  --goal "Screen these candidates and retry transient parse failures." \
  --jd-json .codex/skills/scorer/examples/sample-jd-structured.json \
  --extracted .codex/skills/report-gen/examples/sample-extracted.json \
  --position "Backend Engineer" \
  --skip-reports \
  --output-dir data/agent_planner_out
```

| flag | meaning |
|---|---|
| **JD source (choose one)** | |
| `--jd-file <txt>` | JD text file |
| `--jd-json <json>` | Parsed JD JSON |
| `--polyu-ref <REF>` | Fetch and parse PolyU JD |
| `--polyu-detail-url <URL>` | Detail page fallback with `--polyu-ref` |
| **Candidates** | |
| `--cv <pdf>` (repeatable) | Candidate CV files |
| `--extracted <json>` (repeatable) | Pre-parsed candidate profiles |
| **Execution** | |
| `--position <title>` | Job title used for reports |
| `--engine <legacy\|matching>` | Pipeline scoring engine |
| `--skip-reports` | Skip PDF/Excel generation |
| `--output-dir <dir>` | Shared output directory |
| `--pipeline-max-retries <N>` | Per-candidate retries inside each pipeline run |
| `--max-rounds <N>` | L1 screening-agent rounds (default `2` for rules, `1` for `--planner llm`) |
| `--resume` | Rules mode: start round 1 with pipeline `--resume`. LLM mode: ignored on `run_screening`; use `resume_run` |
| `--fail-fast` | Passes through pipeline `--fail-fast` behavior |
| `--planner rules\|llm` | `rules` (default) or LLM tool picker |
| `--planner-max-steps <N>` | Max planner turns (default `8`; llm mode only) |
| `--goal <text>` | Optional natural-language goal for the planner |

## Output JSON

The script prints one JSON envelope with `runs[]` history and the final pipeline payload. LLM mode also adds `planner: "llm"` and `planner_steps`.

- `status` can be `success`, `partial_success`, `need_input`, or `error`.
- On `need_input`, the exit code is `2` and `result.ask` carries missing fields/questions.
- On hard failures, exit code is `1` and the JSON prints to stderr.
- `output_dir/agent-state.json` is updated after each L1 round (`retry_decision` for audit).
- `--planner llm` also writes `output_dir/planner-state.json` (tool history).

## Behavior notes

- L1 is deterministic and rule-driven; it does not introduce LLM scoring decisions.
- The L1 loop reruns the full pipeline command with `--resume` in later rounds so previous successes are reused.
- Retry policy is `stage + error-message` based: transient/network-style errors retry, while permanent failures stop extra rounds.
- The LLM planner cannot pass extra file paths; `run_screening` / `resume_run` use the original CLI arguments only.
- `run_screening` always starts a fresh L1 loop (`resume=false`). Only `resume_run` sets pipeline `--resume`.
- `--planner llm` defaults `--max-rounds` to `1` so L1 retries do not stack on planner `resume_run`. Pass `--max-rounds` to override.
- Planner LLM prompts send compact, redacted observations (no emails/paths, truncated errors). Full failures stay in `agent-state.json`.
- `finish` returns the in-memory L1 envelope, or rebuilds one from `agent-state.json` when reopening `output_dir`.
- `ask_user.missing` is allowlisted to `jd` / `candidates` / `position`.
- Skill/pipeline JD parse is **rule-only**. REST may still inject hybrid/qwen providers.
- `pipeline` remains the source of truth for ranking, reports, and failure details.
