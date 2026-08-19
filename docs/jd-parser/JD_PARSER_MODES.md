# JD Parser Modes — Usage Guide

This document explains how to use the three pluggable JD parser modes, how to
switch between them, and how to set up the optional local Qwen model.

## Overview

The JD parser lives in `backend/app/services/jd_parser/`. It always runs the
deterministic rule parser first, then optionally enriches the result through a
pluggable provider:

```
JDParserService.parse_jd(jd_text, mode=?)
   |
   |-- mode="rule"   -> rule parsing only (default, deterministic)
   |-- mode="hybrid" -> rule parsing + LLM skill refinement
   |                     (LLMRefinerProvider, uses the shared LLMClient)
   |-- mode="qwen"   -> rule parsing + local Qwen3-0.6B overview extraction
   |                     (QwenJDExtractorProvider)
   |
   +-- provider failure -> automatic fallback to rule output
```

| Mode | Behavior | `parse_path` |
| --- | --- | --- |
| `rule` (default) | Deterministic rule-based parsing (skills, years, education, visa) | `jd_preprocessed_rule_parser` |
| `hybrid` | Rule parsing + LLM skill refinement via the shared LLM client (`LLMClient`, e.g. `glm-4-flash`) | `jd_hybrid_parser` |
| `qwen` | Rule parsing + local Qwen3-0.6B fine-tuned overview extraction (`Rithankoushik/job-parser-model-qwen`) | `jd_qwen_parser` |

Key files:

- `backend/app/services/jd_parser/service.py` — `JDParserService.parse_jd()`
- `backend/app/services/jd_parser/providers/base.py` — provider ABC + result type
- `backend/app/services/jd_parser/providers/llm_refiner.py` — `LLMRefinerProvider`
- `backend/app/services/jd_parser/providers/qwen.py` — `QwenJDExtractorProvider`
- `backend/app/services/jd_parser/providers/__init__.py` — factory (`build_enrichment_provider`, `normalize_mode`)
- `backend/app/skills/jd_parse.py` — shared entry point used by REST API + agent CLI
- `backend/scripts/eval_jd_parsers.py` — evaluation script

## Switching modes (three ways)

### 1) Environment variable (whole backend)

Set `JD_PARSER_MODE` before starting the backend. This applies to the REST API
routes and to the agent skill CLI (which passes `mode=None` and therefore reads
the setting).

```bash
# PowerShell
$env:JD_PARSER_MODE = "hybrid"   # or "rule" / "qwen"

# bash
export JD_PARSER_MODE=hybrid
```

Relevant REST routes (all pass `mode=settings.jd_parser_mode`):

- `POST /api/v1/jobs` (create job, parses JD)
- `POST /api/v1/jobs/{id}/parse-jd`
- `POST /api/v1/jobs/sync-polyu/import`

### 2) Programmatically (per call)

```python
import asyncio
from app.skills.jd_parse import parse_jd_skill

# Single parse with an explicit mode
result = asyncio.run(parse_jd_skill("Requirements: Python, FastAPI", mode="hybrid"))

# Direct service usage
from app.services.jd_parser import JDParserService

service = JDParserService()
result = asyncio.run(service.parse_jd("Requirements: Python, FastAPI", mode="qwen"))
```

You can also inject a custom provider instance:

```python
from app.services.jd_parser import JDParserService
from app.services.jd_parser.providers.llm_refiner import LLMRefinerProvider

provider = LLMRefinerProvider()  # or pass llm_client=... for testing
result = asyncio.run(JDParserService().parse_jd(text, enrichment_provider=provider))
```

### 3) Evaluation script / CLI

```bash
# Compare rule + qwen on the bundled samples (English + Chinese)
python backend/scripts/eval_jd_parsers.py --mode rule --mode qwen --output eval.json

# Evaluate a custom JD file
python backend/scripts/eval_jd_parsers.py --jd-file path/to/jd.txt --mode rule --mode qwen

# Include hybrid (calls the live LLM API, costs tokens)
python backend/scripts/eval_jd_parsers.py --mode rule --mode hybrid --mode qwen
```

> Note: `.codex/skills/jd-parser/scripts/run_jd_parse.py` (the agent skill CLI) has no
> `--mode` flag; switch it with the `JD_PARSER_MODE` environment variable.

## Running qwen (dependencies + model download)

The `qwen` mode requires `torch` + `transformers` and downloads the fine-tuned
model (~1.2 GB) from Hugging Face on first use.

### 1) Install dependencies (Python 3.10+)

```bash
pip install torch transformers accelerate
```

### 2) (Optional) Pre-download the model

This avoids the first-parse download delay:

```bash
pip install huggingface_hub
huggingface-cli download Rithankoushik/job-parser-model-qwen
```

### 3) Verify

```bash
python backend/scripts/eval_jd_parsers.py --mode qwen
```

If the dependencies are missing, the eval script reports `skipped` for `qwen`
instead of failing. When the model is present, the result JSON includes a
`jd_overview` block with fields such as `job_titles`, `company`, `skills`,
`compensation`, `location`, `work_mode`, `experience`, `qualification`,
`industry`, `posted_date`, `notice_period`, and `job_type`.

### 4) Tune model settings (optional, via env)

| Env var | Default | Meaning |
| --- | --- | --- |
| `JD_QWEN_MODEL_ID` | `Rithankoushik/job-parser-model-qwen` | Hugging Face model id |
| `JD_QWEN_MAX_NEW_TOKENS` | `512` | Max generated tokens |
| `JD_QWEN_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |

## Output

`parse_jd()` returns:

- `status` — `"success"` or `"invalid_input"` (empty JD)
- `parse_path` — which path produced the result (see table above; provider
  failures produce `jd_<mode>_fallback_rule_parser`)
- `structured_data` — the parsed fields:
  - `must_skills` / `preferred_skills` (max 5 each)
  - `language_requirements` / `education_requirement` / `visa_requirement` / `experience_requirement`
  - `jd_overview` (qwen mode only; rich fields from the local model)
- `raw_llm_response` — preprocessed payload, LLM refine request, and (when an
  enrichment provider ran) `enrichment_provider`, `enrichment_raw_output`,
  `enrichment_notes`

### Fallback behavior

- If an enrichment provider raises, times out, or returns unusable output, the
  parser keeps the rule-based result and sets `parse_path` to
  `jd_<mode>_fallback_rule_parser`; the reason is recorded in `enrichment_notes`.
- Empty JD input returns `invalid_input` for every mode.

## Adding a new provider

1. Create a class in `backend/app/services/jd_parser/providers/` that extends
   `JDEnrichmentProvider` and implements `refine()`.
2. Return a `JDEnrichmentResult` with refined `must_skills` / `preferred_skills`
   and/or a `jd_overview`.
3. Register the new mode in `VALID_MODES` and `build_enrichment_provider()` in
   `providers/__init__.py`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `qwen` reports skipped | Install `torch transformers accelerate`; see "Running qwen" above |
| `hybrid` falls back to rule | Check `ZAI_API_KEY` / `LLM_BASE_URL` in `.env`; check `enrichment_notes` |
| First qwen parse is slow | Pre-download the model with `huggingface-cli download` |
| Want a different local model | Set `JD_QWEN_MODEL_ID` to another HF repo with the same output schema |