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
