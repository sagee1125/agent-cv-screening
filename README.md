<<<<<<< HEAD
# Agent-CV-Screening

**AI-powered CV screening system with deterministic LLM parsing & multi-department scoring.**

Built for university departments to automatically parse, match, and rank candidates based on job descriptions.

## Features

- 📄 **PDF/DOCX parsing** with GPT-4o-mini (deterministic: temp=0, seed=42)
- 🧠 **Skill taxonomy** with hierarchical matching & synonym mapping
- ⚖️ **Multi-dimensional scoring** with department-customizable weights
- 🔁 **Hash-based caching** for reproducible LLM outputs
- 📊 **Exportable reports** (PDF, Excel, JSON)
- 🔍 **Feedback logging** for continuous improvement

## Tech Stack

| Layer       | Technology                         |
| :---------- | :--------------------------------- |
| Backend     | Python 3.11+ / FastAPI             |
| Database    | PostgreSQL 15+ (JSONB)             |
| LLM         | OpenAI GPT-4o-mini                 |
| PDF Parsing | PyPDF2 / pdfplumber                |
| Reports     | ReportLab (PDF) / openpyxl (Excel) |
| Deployment  | Docker + docker-compose            |

## Quick Start

```bash
# 1. Clone
git clone {}
cd agent-cv-screening

# 2. Copy environment config
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# 3. Start services
docker-compose up -d

# 4. Run database migrations
docker-compose exec backend alembic upgrade head

# 5. Open API docs
open http://localhost:8000/docs
```
=======
# agent-cv-screening
>>>>>>> 03982fd (first commit)
