# Agent CV Screening

Agent CV Screening is a full-stack application for resume screening workflows. It provides:

- CV parsing (PDF-focused, with multimodal parsing and text fallback)
- Structured candidate extraction (name, education, experience, skills, publications)
- Backend APIs (FastAPI) and a frontend UI (React + Vite)
- Cache + reproducible LLM parameters (`temperature` / `seed`)

## Project Structure

- `backend`: FastAPI service, parser logic, and database integration
- `frontend`: React application
- `scripts`: local development utility scripts
- `data`: runtime files (uploads, cache, reports)

## Quick Start

### 1) Prerequisites

- Docker and Docker Compose installed
- `.env` configured (already present in this repository)

### 2) Start backend and database

```bash
docker compose up -d
docker compose exec backend alembic upgrade head
```

Backend API docs:

- `http://localhost:8000/docs`

### 3) Start frontend (optional for local UI development)

```bash
cd frontend
npm install
npm run dev
```

Frontend default URL:

- `http://localhost:5173`

## Scripts

Current utility script in `scripts`:

- `scripts/reset-db.sh`

What it does:

- Truncates all tables in PostgreSQL `public` schema (keeps table structure)
- Clears local `data/cache` and `data/uploads`

Usage:

```bash
bash scripts/reset-db.sh
```

Note:

- The database container must already be running (the script checks the `db` service in `docker compose`)

## Model and Hardcoded Behavior

Current main model in `.env`:

- `LLM_MODEL=glm-4-flash`

Important defaults and fixed behaviors in code:

- `backend/app/config.py`
  - default `llm_model` is `glm-4-flash`
  - default `llm_vision_model` is `glm-4v-flash`
- `docker-compose.yml`
  - `LLM_MODEL` fallback default is `glm-4-flash`
- `backend/app/services/cv_parser/service.py`
  - many parser calls use fixed `temperature=0` and `seed=42`
  - vision retry, focus pass, and text fallback are configurable, but call-time parameters remain fixed

## JD Parser Modes

The JD parser (`backend/app/services/jd_parser/`) supports three pluggable modes:

| Mode | Behavior | parse_path |
| --- | --- | --- |
| `rule` (default) | Deterministic rule-based parsing (skills, years, education, visa) | `jd_preprocessed_rule_parser` |
| `hybrid` | Rule parsing + LLM skill refinement via the shared LLM client (`LLMClient`, e.g. `glm-4-flash`) | `jd_hybrid_parser` |
| `qwen` | Rule parsing + local Qwen3-0.6B fine-tuned overview extraction (`Rithankoushik/job-parser-model-qwen`) | `jd_qwen_parser` |

- On enrichment failure the parser falls back to rule output (`parse_path` ends with
  `_fallback_rule_parser`) and records `enrichment_notes` in `raw_llm_response`.
- `hybrid` uses the existing prompt in `backend/app/services/jd_parser/prompts.py`
  and requires a valid `ZAI_API_KEY` / `LLM_BASE_URL`.
- `qwen` requires `torch` + `transformers`; the model is loaded lazily on first use
  and must/preferred skills still come from the rule parser.
- Enrichment providers are pluggable via `app.services.jd_parser.providers`:
  `LLMRefinerProvider` (hybrid) and `QwenJDExtractorProvider` (qwen).
- Full usage guide: `docs/jd-parser/JD_PARSER_MODES.md`.

### Switching modes (three ways)

1. **Environment variable** (applies to the whole backend, including the REST API and the skill CLI)

   ```bash
   # PowerShell
   $env:JD_PARSER_MODE = "hybrid"   # or "rule" / "qwen"

   # bash
   export JD_PARSER_MODE=hybrid
   ```

2. **Programmatically** (per call)

   ```python
   import asyncio
   from app.skills.jd_parse import parse_jd_skill

   result = asyncio.run(parse_jd_skill("Requirements: Python, FastAPI", mode="hybrid"))

   # Or directly on the service:
   # from app.services.jd_parser import JDParserService
   # result = await JDParserService().parse_jd("Requirements: Python", mode="qwen")
   ```

3. **Evaluation script / CLI**

   ```bash
   python backend/scripts/eval_jd_parsers.py --mode rule --mode qwen --output eval.json
   ```

   > Note: the agent skill CLI (`.codex/skills/jd-parser/scripts/run_jd_parse.py`) has no
   > `--mode` flag; set `JD_PARSER_MODE` in the environment to switch it.

### Running qwen (dependencies + model download)

`qwen` mode needs `torch` + `transformers`, and downloads the fine-tuned model
(~1.2 GB) from Hugging Face on first use.

1. Install dependencies (Python 3.10+):

   ```bash
   pip install torch transformers accelerate
   ```

2. (Optional) Pre-download the model so the first parse is fast:

   ```bash
   pip install huggingface_hub
   huggingface-cli download Rithankoushik/job-parser-model-qwen
   ```

3. Verify with the eval script (it skips automatically when deps are missing):

   ```bash
   python backend/scripts/eval_jd_parsers.py --mode qwen
   ```

4. Tune model settings via env (optional):

   | Env var | Default | Meaning |
   | --- | --- | --- |
   | `JD_QWEN_MODEL_ID` | `Rithankoushik/job-parser-model-qwen` | Hugging Face model id |
   | `JD_QWEN_MAX_NEW_TOKENS` | `512` | Max generated tokens |
   | `JD_QWEN_DEVICE` | `auto` | `auto` / `cuda` / `cpu` |

### Evaluating modes

Compare parser modes on bundled sample JDs (English + Chinese) with:

```bash
python backend/scripts/eval_jd_parsers.py --mode rule --mode qwen --output eval.json
```

- `--jd-file` can be repeated to evaluate custom JDs.
- `--mode qwen` is skipped automatically when `torch`/`transformers` are missing.
- `--mode hybrid` calls the live LLM API (costs tokens), so it is opt-in.
