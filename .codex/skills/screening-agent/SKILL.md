---
name: screening-agent
description: "Run an L1 screening-agent loop on top of the pipeline skill: validate input, return need_input when required fields are missing, retry partial failures for additional rounds with --resume, and persist run state for traceability."
---

# Screening Agent Skill (L1 Phase 2)

Run a thin orchestration loop that repeatedly calls the `pipeline` skill until:

- all candidates succeed (`status=success`),
- input is missing (`status=need_input`), or
- retry rounds are exhausted (`status=partial_success` or `status=error`).

This keeps scoring deterministic because all scoring still happens in the `pipeline` / scorer path.

## Prerequisites

- Backend dependencies installed: `pip install -r backend/requirements.txt`.
- `.env` at repo root with required parser credentials (`ZAI_API_KEY`, `LLM_BASE_URL`) when CV parsing is used.
- Run commands from the repository root.

## Run

```bash
python .codex/skills/screening-agent/scripts/run_agent.py \
  --jd-file jd.txt \
  --cv cv1.pdf --cv cv2.pdf \
  --position "Backend Engineer" \
  --output-dir data/pipeline_out
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
| `--max-rounds <N>` | Total screening-agent rounds (default `2`) |
| `--resume` | Starts round 1 with pipeline `--resume` |
| `--fail-fast` | Passes through pipeline `--fail-fast` behavior |

## Output JSON

The script prints one JSON envelope with `runs[]` history and the final pipeline payload:

```json
{
  "status": "partial_success",
  "output_dir": ".../data/pipeline_out",
  "runs": [
    { "round": 1, "status": "partial_success", "exit_code": 0, "candidates_count": 1, "failures_count": 1, "payload": { "...": "..." } },
    { "round": 2, "status": "success", "exit_code": 0, "candidates_count": 2, "failures_count": 0, "payload": { "...": "..." } }
  ],
  "result": { "... final pipeline payload ..." },
  "ask": null
}
```

- `status` can be `success`, `partial_success`, `need_input`, or `error`.
- On `need_input`, the exit code is `2` and `result.ask` carries missing fields/questions.
- On hard failures, exit code is `1` and the JSON prints to stderr.
- `output_dir/agent-state.json` is updated after each round and includes `retry_decision` (`action` + `reason`) for auditability.

## Behavior notes

- This skill is deterministic and rule-driven; it does not introduce LLM scoring decisions.
- The loop reruns the full pipeline command with `--resume` in later rounds so previous successes are reused.
- Retry policy is `stage + error-message` based: transient/network-style errors retry, while permanent failures (missing files, invalid args, auth/certificate issues) stop extra rounds.
- `pipeline` remains the source of truth for ranking, reports, and failure details.

