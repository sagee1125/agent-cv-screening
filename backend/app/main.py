# FastAPI application entry point, middleware, and startup hooks.
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.dependencies import AsyncSessionFactory, engine
from app.api.matching_errors import MatchingAPIError, matching_api_error_handler
from app.api.routes import candidates, feedback, jobs, matching, reports, scoring
from app.config import settings
from app.services.matching_service import (
    recover_recalculation_tasks,
    run_recalculation_watchdog,
    schedule_recalculation_task,
    shutdown_recalculation_tasks,
)
from app.services.taxonomy_sync import sync_taxonomy_to_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)
_matching_watchdog_task: asyncio.Task[None] | None = None

app = FastAPI(
    title="Agent-CV-Screening API",
    description="AI-powered CV screening system with deterministic LLM parsing",
    version=settings.app_version,
)
app.add_exception_handler(MatchingAPIError, matching_api_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candidates.router, prefix="/api/v1", tags=["candidates"])
app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
app.include_router(scoring.router, prefix="/api/v1", tags=["scoring"])
app.include_router(matching.router, prefix="/api/v1", tags=["candidate-matching"])
app.include_router(reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize local resources and recover persisted background work."""
    global _matching_watchdog_task

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.report_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.cache_dir).mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await _ensure_polyu_sync_columns(conn)
        await _ensure_resume_job_columns(conn)

    # Keep the skill_taxonomy table in sync with the curated YAML (idempotent upsert).
    async with AsyncSessionFactory() as session:
        counts = await sync_taxonomy_to_db(session)
        logger.info("Skill taxonomy synced: %s", counts)
    if settings.matching_enabled:
        async with AsyncSessionFactory() as session:
            pending_recalculations = await recover_recalculation_tasks(session)
        for recalc_job_id in pending_recalculations:
            schedule_recalculation_task(recalc_job_id)
        _matching_watchdog_task = asyncio.create_task(run_recalculation_watchdog())
        if pending_recalculations:
            logger.info(
                "Recovered %d pending candidate matching recalculation(s).",
                len(pending_recalculations),
            )
    logger.info("Application startup complete.")


# Stop the watchdog and local recalculation tasks during graceful shutdown.
@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _matching_watchdog_task

    if _matching_watchdog_task is not None:
        _matching_watchdog_task.cancel()
        await asyncio.gather(_matching_watchdog_task, return_exceptions=True)
        _matching_watchdog_task = None
    await shutdown_recalculation_tasks()


async def _ensure_polyu_sync_columns(connection) -> None:
    """Add PolyU sync columns/index on existing databases that predate create_all."""
    await connection.execute(text("ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS source VARCHAR(50)"))
    await connection.execute(
        text("ALTER TABLE job_posts ADD COLUMN IF NOT EXISTS external_ref VARCHAR(64)")
    )
    await connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_job_posts_source_external_ref
            ON job_posts (source, external_ref)
            """
        )
    )


async def _ensure_resume_job_columns(connection) -> None:
    """Add job_post_id/source_channel to resumes, enforce one resume per (candidate, job), and widen phone column."""
    await connection.execute(text("ALTER TABLE resumes ADD COLUMN IF NOT EXISTS job_post_id UUID"))
    await connection.execute(text("ALTER TABLE resumes ADD COLUMN IF NOT EXISTS source_channel VARCHAR(64) DEFAULT 'manual_upload'"))
    # Drop legacy orphan resumes that predate the job-scoped model, then enforce NOT NULL.
    # Delete dependents first to satisfy foreign keys (scoring_results -> resumes, extracted_data -> resumes).
    await connection.execute(
        text(
            "DELETE FROM scoring_results WHERE resume_id IN (SELECT id FROM resumes WHERE job_post_id IS NULL)"
        )
    )
    await connection.execute(
        text(
            "DELETE FROM extracted_data WHERE resume_id IN (SELECT id FROM resumes WHERE job_post_id IS NULL)"
        )
    )
    await connection.execute(text("DELETE FROM resumes WHERE job_post_id IS NULL"))
    await connection.execute(text("ALTER TABLE resumes ALTER COLUMN job_post_id SET NOT NULL"))

    # Widen candidates.phone so long international numbers no longer cause 500s.
    await connection.execute(text("ALTER TABLE candidates ALTER COLUMN phone TYPE VARCHAR(64)"))

    # Replace the old (candidate_id, file_hash) uniqueness rule with one resume per (candidate, job).
    await connection.execute(text("DROP INDEX IF EXISTS uq_resumes_candidate_file_hash"))
    await connection.execute(text("DROP INDEX IF EXISTS resumes_file_hash_key"))
    # Collapse any pre-existing duplicate (candidate, job) rows before adding the unique constraint.
    # Keep the newest resume per pair (max uploaded_at, then max id as tiebreaker) and delete the rest.
    await connection.execute(
        text(
            """
            DELETE FROM resumes
            WHERE id IN (
                SELECT r.id
                FROM resumes r
                JOIN (
                    SELECT candidate_id, job_post_id,
                           (array_agg(id ORDER BY uploaded_at DESC, id DESC))[1] AS keep_id
                    FROM resumes
                    GROUP BY candidate_id, job_post_id
                    HAVING COUNT(*) > 1
                ) kept
                  ON r.candidate_id = kept.candidate_id
                 AND r.job_post_id = kept.job_post_id
                WHERE r.id <> kept.keep_id
            )
            """
        )
    )
    # Remove dependents of any duplicate resumes that were just deleted, then drop the legacy non-unique index.
    await connection.execute(
        text(
            """
            DELETE FROM extracted_data
            WHERE resume_id NOT IN (SELECT id FROM resumes)
            """
        )
    )
    await connection.execute(
        text(
            """
            DELETE FROM scoring_results
            WHERE resume_id NOT IN (SELECT id FROM resumes)
            """
        )
    )
    await connection.execute(text("DROP INDEX IF EXISTS idx_resumes_candidate_job"))
    await connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_resumes_candidate_job
            ON resumes (candidate_id, job_post_id)
            """
        )
    )
    await connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_resumes_job_uploaded
            ON resumes (job_post_id, uploaded_at)
            """
        )
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"version": settings.app_version, "error": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"version": settings.app_version, "error": "Internal server error"},
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"version": settings.app_version, "status": "ok"}
