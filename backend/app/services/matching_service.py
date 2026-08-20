# Coordinates candidate matching configuration, versioning, persistence, and publication.
from __future__ import annotations

import asyncio
import copy
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import AsyncSessionFactory, taxonomy_loader
from app.config import settings
from app.models.database import (
    CandidateMatchScore,
    ExtractedData,
    JobPost,
    MatchingRecalcJob,
    Resume,
)
from app.services.candidate_matching.config_builder import build_matching_config
from app.services.candidate_matching.contracts import EffectiveConfig, MatchingConfigError
from app.services.candidate_matching.ranker import rank_candidates

logger = logging.getLogger(__name__)
_local_recalculation_tasks: dict[UUID, asyncio.Task[None]] = {}
_debounce_tasks: dict[UUID, asyncio.Task[None]] = {}
_debounce_payload: dict[UUID, dict[str, Any]] = {}
_deferred_recalc_jobs: set[UUID] = set()


class MatchingRateLimitError(RuntimeError):
    """Signal that a Job Post exceeded its recalculation request allowance."""


# Return one active Job Post, optionally locking it for version reservation.
async def get_matching_job(
    db: AsyncSession,
    job_post_id: UUID,
    *,
    for_update: bool = False,
) -> JobPost | None:
    statement = select(JobPost).where(
        JobPost.id == job_post_id,
        JobPost.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


# Build the validated effective config using persisted and parser inputs.
def effective_matching_config(job: JobPost) -> EffectiveConfig:
    explicit = copy.deepcopy(job.matching_config_json or {})
    explicit["taxonomy_version"] = settings.matching_taxonomy_version
    explicit["reference_date_policy"] = "recalculation_created_at_utc"
    return build_matching_config(
        job.jd_parsed_json,
        explicit_config=explicit,
        legacy_weight_config=job.weight_config_json,
    )


# Persist a validated explicit config and mark existing scores stale.
async def save_matching_config(
    db: AsyncSession,
    job: JobPost,
    explicit_config: dict[str, Any],
) -> EffectiveConfig:
    effective_input = copy.deepcopy(explicit_config)
    effective_input["taxonomy_version"] = settings.matching_taxonomy_version
    effective_input["reference_date_policy"] = "recalculation_created_at_utc"
    effective = build_matching_config(
        job.jd_parsed_json,
        explicit_config=effective_input,
        legacy_weight_config=job.weight_config_json,
    )
    job.matching_config_json = explicit_config
    job.matching_schema_version = effective.config["schema_version"]
    job.matching_status = "stale" if job.current_score_version > 0 else "unscored"
    job.updated_at = _utcnow()
    await db.commit()
    await db.refresh(job)
    return effective


# Reserve an idempotent job-scoped score version for recalculation.
async def create_recalculation(
    db: AsyncSession,
    *,
    job_post_id: UUID,
    idempotency_key: str,
    trigger: str,
    reason: str | None,
    requested_by: str | None,
) -> tuple[MatchingRecalcJob, bool]:
    job = await get_matching_job(db, job_post_id, for_update=True)
    if job is None:
        raise LookupError("MATCHING_JOB_NOT_FOUND")

    existing_statement = select(MatchingRecalcJob).where(
        MatchingRecalcJob.job_post_id == job_post_id,
        MatchingRecalcJob.idempotency_key == idempotency_key,
    )
    existing = (await db.execute(existing_statement)).scalar_one_or_none()
    if existing:
        await db.commit()
        return existing, False

    active_statement = (
        select(MatchingRecalcJob)
        .where(
            MatchingRecalcJob.job_post_id == job_post_id,
            MatchingRecalcJob.status.in_(("pending", "running")),
        )
        .with_for_update()
    )
    active_jobs = (await db.execute(active_statement)).scalars().all()
    active = None
    for candidate in active_jobs:
        if _recalculation_is_stale(candidate):
            _expire_recalculation(candidate)
        elif active is None:
            active = candidate
    if active:
        await db.commit()
        raise RuntimeError(str(active.id))

    recent_count_statement = select(func.count(MatchingRecalcJob.id)).where(
        MatchingRecalcJob.job_post_id == job_post_id,
        MatchingRecalcJob.created_at >= _utcnow() - timedelta(minutes=1),
    )
    recent_count = int((await db.execute(recent_count_statement)).scalar_one())
    if recent_count >= 10:
        raise MatchingRateLimitError("MATCHING_RATE_LIMITED")

    effective = effective_matching_config(job)

    latest_target_statement = select(
        func.coalesce(func.max(MatchingRecalcJob.target_score_version), 0)
    ).where(MatchingRecalcJob.job_post_id == job_post_id)
    latest_target = int((await db.execute(latest_target_statement)).scalar_one())
    target_version = max(job.current_score_version, latest_target) + 1

    candidate_count_statement = (
        select(func.count(Resume.id))
        .join(ExtractedData, ExtractedData.resume_id == Resume.id)
        .where(
            Resume.job_post_id == job_post_id,
            ExtractedData.status == "success",
        )
    )
    candidates_total = int((await db.execute(candidate_count_statement)).scalar_one())
    recalc = MatchingRecalcJob(
        job_post_id=job_post_id,
        target_score_version=target_version,
        status="pending",
        trigger=trigger,
        reason=reason,
        idempotency_key=idempotency_key,
        config_hash=effective.config_hash,
        algorithm_version=effective.config["algorithm_version"],
        candidates_total=candidates_total,
        requested_by=requested_by,
    )
    db.add(recalc)
    job.matching_status = "pending"
    job.last_matching_error_code = None
    await db.commit()
    await db.refresh(recalc)
    return recalc, True


# Return one recalculation only when it belongs to the requested Job Post.
async def get_recalculation(
    db: AsyncSession,
    job_post_id: UUID,
    recalc_job_id: UUID,
) -> MatchingRecalcJob | None:
    statement = select(MatchingRecalcJob).where(
        MatchingRecalcJob.id == recalc_job_id,
        MatchingRecalcJob.job_post_id == job_post_id,
    )
    return (await db.execute(statement)).scalar_one_or_none()


# Return one published candidate score from the requested or current version.
async def get_published_candidate_score(
    db: AsyncSession,
    *,
    job: JobPost,
    candidate_id: UUID,
    score_version: int | None = None,
) -> CandidateMatchScore | None:
    version = score_version if score_version is not None else job.current_score_version
    statement = select(CandidateMatchScore).where(
        CandidateMatchScore.job_post_id == job.id,
        CandidateMatchScore.candidate_id == candidate_id,
        CandidateMatchScore.score_version == version,
        CandidateMatchScore.is_published.is_(True),
    )
    return (await db.execute(statement)).scalar_one_or_none()


# Schedule one debounced backend recalculation after CV or config changes.
def request_matching_recalculation(
    job_post_id: UUID,
    *,
    trigger: str,
    reason: str | None = None,
) -> None:
    if not settings.matching_enabled:
        return
    payload = _debounce_payload.setdefault(
        job_post_id,
        {"trigger": trigger, "upload_count": 0, "reason": reason},
    )
    payload["trigger"] = trigger
    payload["upload_count"] = int(payload.get("upload_count", 0)) + 1
    if reason:
        payload["reason"] = reason

    existing = _debounce_tasks.get(job_post_id)
    if existing is not None and not existing.done():
        existing.cancel()

    delay = max(settings.matching_recalc_debounce_seconds, 1)
    task = asyncio.create_task(_debounced_recalculation_worker(job_post_id, delay))
    _debounce_tasks[job_post_id] = task


# Wait for the debounce window, then enqueue one coalesced recalculation.
async def _debounced_recalculation_worker(job_post_id: UUID, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        payload = _debounce_payload.pop(job_post_id, {})
        upload_count = int(payload.get("upload_count", 0))
        reason = payload.get("reason")
        if upload_count > 1:
            reason = f"{upload_count} CV upload(s) parsed successfully"
        await _enqueue_matching_recalculation(
            job_post_id,
            trigger=str(payload.get("trigger") or "cv_uploaded"),
            reason=reason,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Debounced candidate matching enqueue failed.",
            extra={"job_post_id": str(job_post_id)},
        )
    finally:
        if _debounce_tasks.get(job_post_id) is asyncio.current_task():
            _debounce_tasks.pop(job_post_id, None)


# Create and schedule one automatic recalculation, deferring when another is active.
async def _enqueue_matching_recalculation(
    job_post_id: UUID,
    *,
    trigger: str,
    reason: str | None,
) -> None:
    async with AsyncSessionFactory() as db:
        try:
            recalc, created = await create_recalculation(
                db,
                job_post_id=job_post_id,
                idempotency_key=f"auto-{trigger}-{job_post_id}-{uuid4()}",
                trigger=trigger,
                reason=reason,
                requested_by=None,
            )
        except RuntimeError:
            _deferred_recalc_jobs.add(job_post_id)
            logger.info(
                "Candidate matching recalculation deferred while another job is active.",
                extra={"job_post_id": str(job_post_id), "trigger": trigger},
            )
            return
        except MatchingRateLimitError:
            logger.warning(
                "Automatic candidate matching was rate limited; scheduling retry.",
                extra={"job_post_id": str(job_post_id), "trigger": trigger},
            )
            request_matching_recalculation(
                job_post_id,
                trigger=trigger,
                reason=reason,
            )
            return
        except (MatchingConfigError, LookupError) as exc:
            logger.warning(
                "Automatic candidate matching was skipped: %s",
                exc,
                extra={"job_post_id": str(job_post_id), "trigger": trigger},
            )
            return

    if created:
        schedule_recalculation_task(recalc.id)


# Retry deferred work after an active recalculation finishes.
async def _process_deferred_recalculation(job_post_id: UUID) -> None:
    if job_post_id not in _deferred_recalc_jobs:
        return
    _deferred_recalc_jobs.discard(job_post_id)
    request_matching_recalculation(
        job_post_id,
        trigger="cv_uploaded",
        reason="Deferred until the active recalculation completed",
    )


# Execute one persisted recalculation in an isolated background session.
async def run_recalculation_task(recalc_job_id: UUID) -> None:
    job_post_id = (
        await _lookup_recalculation_job_post_id(recalc_job_id)
    )
    async with AsyncSessionFactory() as db:
        try:
            await _run_recalculation(db, recalc_job_id)
        except asyncio.CancelledError:
            await db.rollback()
            await _mark_recalculation_failed(
                db,
                recalc_job_id,
                RuntimeError("MATCHING_RECALC_CANCELLED"),
            )
            raise
        except Exception as exc:
            logger.exception(
                "Candidate matching recalculation failed.",
                extra={"recalc_job_id": str(recalc_job_id)},
            )
            await db.rollback()
            await _mark_recalculation_failed(db, recalc_job_id, exc)
    if job_post_id is not None:
        await _process_deferred_recalculation(job_post_id)


# Resolve the Job Post id for one recalculation task.
async def _lookup_recalculation_job_post_id(recalc_job_id: UUID) -> UUID | None:
    async with AsyncSessionFactory() as db:
        return (
            await db.execute(
                select(MatchingRecalcJob.job_post_id).where(
                    MatchingRecalcJob.id == recalc_job_id
                )
            )
        ).scalar_one_or_none()


# Schedule one local execution while preventing duplicate in-process tasks.
def schedule_recalculation_task(recalc_job_id: UUID) -> None:
    existing = _local_recalculation_tasks.get(recalc_job_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(run_recalculation_task(recalc_job_id))
    _local_recalculation_tasks[recalc_job_id] = task
    task.add_done_callback(_remove_completed_recalculation_task)


# Remove a completed local task from the in-process registry.
def _remove_completed_recalculation_task(task: asyncio.Task[None]) -> None:
    completed_ids = [
        recalc_job_id
        for recalc_job_id, current in _local_recalculation_tasks.items()
        if current is task
    ]
    for recalc_job_id in completed_ids:
        _local_recalculation_tasks.pop(recalc_job_id, None)


# Periodically recover pending work and expire abandoned task leases.
async def run_recalculation_watchdog() -> None:
    interval = min(
        max(settings.matching_recalc_timeout_seconds // 3, 5),
        60,
    )
    while True:
        try:
            await asyncio.sleep(interval)
            async with AsyncSessionFactory() as db:
                pending_ids = await recover_recalculation_tasks(db)
            for recalc_job_id in pending_ids:
                schedule_recalculation_task(recalc_job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Candidate matching watchdog iteration failed.")


# Cancel local matching executions during graceful application shutdown.
async def shutdown_recalculation_tasks() -> None:
    debounce_tasks = [
        task for task in _debounce_tasks.values() if not task.done()
    ]
    for task in debounce_tasks:
        task.cancel()
    if debounce_tasks:
        await asyncio.gather(*debounce_tasks, return_exceptions=True)
    _debounce_tasks.clear()
    _debounce_payload.clear()
    _deferred_recalc_jobs.clear()

    tasks = [
        task
        for task in _local_recalculation_tasks.values()
        if not task.done()
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _local_recalculation_tasks.clear()


# Recover pending work and terminate abandoned jobs after a process restart.
async def recover_recalculation_tasks(db: AsyncSession) -> list[UUID]:
    job_ids_statement = (
        select(MatchingRecalcJob.job_post_id)
        .where(MatchingRecalcJob.status.in_(("pending", "running")))
        .distinct()
        .order_by(MatchingRecalcJob.job_post_id.asc())
    )
    job_post_ids = (await db.execute(job_ids_statement)).scalars().all()
    pending_ids: list[UUID] = []
    for job_post_id in job_post_ids:
        job = await get_matching_job(db, job_post_id, for_update=True)
        if job is None:
            continue
        statement = (
            select(MatchingRecalcJob)
            .where(
                MatchingRecalcJob.job_post_id == job_post_id,
                MatchingRecalcJob.status.in_(("pending", "running")),
            )
            .order_by(MatchingRecalcJob.created_at.asc())
            .with_for_update()
        )
        recalculations = (await db.execute(statement)).scalars().all()
        expired = False
        for recalc in recalculations:
            if _recalculation_is_stale(recalc):
                _expire_recalculation(recalc)
                expired = True
            elif recalc.status == "pending":
                pending_ids.append(recalc.id)
        if expired:
            has_pending = any(recalc.status == "pending" for recalc in recalculations)
            job.matching_status = (
                "pending"
                if has_pending
                else "stale"
                if job.current_score_version > 0
                else "failed"
            )
            job.last_matching_error_code = (
                None if has_pending else "MATCHING_RECALC_TIMEOUT"
            )
    await db.commit()
    return pending_ids


# Calculate every parsed resume and atomically publish one complete version.
async def _run_recalculation(db: AsyncSession, recalc_job_id: UUID) -> None:
    job_post_id = (
        await db.execute(
            select(MatchingRecalcJob.job_post_id).where(
                MatchingRecalcJob.id == recalc_job_id
            )
        )
    ).scalar_one_or_none()
    if job_post_id is None:
        return
    job = await get_matching_job(db, job_post_id, for_update=True)
    if job is None:
        raise LookupError("MATCHING_JOB_NOT_FOUND")
    recalc = (
        await db.execute(
            select(MatchingRecalcJob)
            .where(MatchingRecalcJob.id == recalc_job_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if recalc is None or recalc.status != "pending":
        return

    recalc.status = "running"
    recalc.started_at = _utcnow()
    recalc.heartbeat_at = recalc.started_at
    job.matching_status = "running"
    await db.commit()

    effective = effective_matching_config(job)
    if effective.config_hash != recalc.config_hash:
        raise ValueError("MATCHING_CONFIG_CHANGED")
    rows_statement = (
        select(Resume)
        .join(ExtractedData, ExtractedData.resume_id == Resume.id)
        .where(
            Resume.job_post_id == job.id,
            ExtractedData.status == "success",
        )
        .options(selectinload(Resume.extracted_data))
        .order_by(Resume.candidate_id.asc())
    )
    resumes = (await db.execute(rows_statement)).scalars().all()
    input_identity = {
        (
            str(resume.id),
            resume.file_hash,
            _iso(resume.extracted_data.extracted_at),
        )
        for resume in resumes
    }
    reference_date = recalc.created_at.date()
    calculated: list[tuple[Resume, dict[str, Any]]] = []
    for index, resume in enumerate(resumes, start=1):
        result = _score_resume(
            cv_data=resume.extracted_data.structured_data,
            effective=effective,
            reference_date=reference_date,
        )
        calculated.append((resume, result))
        recalc.candidates_processed = index
        recalc.heartbeat_at = _utcnow()
        await db.commit()

    locked_job = await get_matching_job(db, recalc.job_post_id, for_update=True)
    if locked_job is None:
        raise LookupError("MATCHING_JOB_NOT_FOUND")
    job = locked_job
    current_effective = effective_matching_config(job)
    if current_effective.config_hash != recalc.config_hash:
        raise ValueError("MATCHING_CONFIG_CHANGED")
    current_identity_statement = (
        select(Resume.id, Resume.file_hash, ExtractedData.extracted_at)
        .join(ExtractedData, ExtractedData.resume_id == Resume.id)
        .where(
            Resume.job_post_id == job.id,
            ExtractedData.status == "success",
        )
    )
    current_identity = {
        (str(resume_id), file_hash, _iso(extracted_at))
        for resume_id, file_hash, extracted_at in (
            await db.execute(current_identity_statement)
        ).all()
    }
    if current_identity != input_identity:
        raise ValueError("MATCHING_INPUT_CHANGED")

    _assign_dense_ranks(calculated)
    await db.execute(
        delete(CandidateMatchScore).where(
            CandidateMatchScore.recalc_job_id == recalc.id,
            CandidateMatchScore.is_published.is_(False),
        )
    )
    for resume, result in calculated:
        db.add(
            CandidateMatchScore(
                job_post_id=job.id,
                candidate_id=resume.candidate_id,
                resume_id=resume.id,
                recalc_job_id=recalc.id,
                score_version=recalc.target_score_version,
                algorithm_version=effective.config["algorithm_version"],
                schema_version=effective.config["schema_version"],
                config_hash=effective.config_hash,
                cv_file_hash=resume.file_hash,
                eligibility_status=result["eligibility"]["status"],
                total_score=Decimal(str(result["match_score"])),
                fit_band=result["fit_band"],
                evidence_confidence=Decimal(str(result["evidence_confidence"])),
                recommendation_rank=result["recommendation_rank"],
                dimension_results=result["radar_dimensions"],
                eligibility_results=result["eligibility"]["results"],
                interview_questions=result["interview_questions"],
                config_snapshot=effective.config,
                input_snapshot={
                    "jd_updated_at": _iso(job.updated_at),
                    "cv_extracted_at": _iso(resume.extracted_data.extracted_at),
                    "reference_date": reference_date.isoformat(),
                    "taxonomy_version": effective.config["taxonomy_version"],
                },
                top_strengths=result["top_strengths"],
                key_gaps=result["key_gaps"],
                is_published=True,
            )
        )

    recalc.status = "succeeded"
    recalc.finished_at = _utcnow()
    recalc.heartbeat_at = recalc.finished_at
    job.current_score_version = recalc.target_score_version
    job.matching_status = "ready"
    job.last_scored_at = recalc.finished_at
    job.last_matching_error_code = None
    await db.commit()


# Adapt the pure engine public API to the persistence result contract.
def _score_resume(
    *,
    cv_data: dict[str, Any],
    effective: EffectiveConfig,
    reference_date: date,
) -> dict[str, Any]:
    from app.services.candidate_matching.engine import match_candidate

    return match_candidate(
        cv_data,
        effective,
        reference_date,
        relation_resolver=_taxonomy_related,
    )


# Resolve taxonomy-approved parent or child relationships for canonical skills.
def _taxonomy_related(candidate_skill: str, required_skill: str) -> bool:
    candidate_text = candidate_skill.replace("_", " ")
    required_text = required_skill.replace("_", " ")
    candidate = taxonomy_loader.normalize_skill(candidate_text) or candidate_text
    required = taxonomy_loader.normalize_skill(required_text) or required_text
    return taxonomy_loader.related(candidate, required)


# Assign SQL-style dense ranks on documented business sort values.
def _assign_dense_ranks(calculated: list[tuple[Resume, dict[str, Any]]]) -> None:
    by_candidate_id = {
        str(resume.candidate_id): (resume, result)
        for resume, result in calculated
    }
    ranked = rank_candidates(
        [
            {"candidate_id": str(resume.candidate_id), **result}
            for resume, result in calculated
        ]
    )
    ordered: list[tuple[Resume, dict[str, Any]]] = []
    for ranked_result in ranked:
        candidate_id = str(ranked_result["candidate_id"])
        resume, result = by_candidate_id[candidate_id]
        result["recommendation_rank"] = ranked_result["recommendation_rank"]
        ordered.append((resume, result))
    calculated[:] = ordered


# Preserve prior published results while marking a failed attempt terminal.
async def _mark_recalculation_failed(
    db: AsyncSession,
    recalc_job_id: UUID,
    exc: Exception,
) -> None:
    job_post_id = (
        await db.execute(
            select(MatchingRecalcJob.job_post_id).where(
                MatchingRecalcJob.id == recalc_job_id
            )
        )
    ).scalar_one_or_none()
    if job_post_id is None:
        return
    job = await get_matching_job(db, job_post_id, for_update=True)
    recalc = (
        await db.execute(
            select(MatchingRecalcJob)
            .where(MatchingRecalcJob.id == recalc_job_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if recalc is None:
        return
    if recalc.status in {"succeeded", "failed", "cancelled"}:
        return
    code = _error_code(exc)
    recalc.status = "failed"
    remaining = max(recalc.candidates_total - recalc.candidates_processed, 0)
    recalc.candidates_failed = remaining
    recalc.error_code = code
    recalc.error_message = str(exc)[:1000]
    recalc.finished_at = _utcnow()
    recalc.heartbeat_at = recalc.finished_at
    if job is not None:
        job.matching_status = "stale" if job.current_score_version > 0 else "failed"
        job.last_matching_error_code = code
    await db.execute(
        delete(CandidateMatchScore).where(
            CandidateMatchScore.recalc_job_id == recalc_job_id,
            CandidateMatchScore.is_published.is_(False),
        )
    )
    await db.commit()


# Mark one abandoned task terminal while preserving any published version.
def _expire_recalculation(recalc: MatchingRecalcJob) -> None:
    remaining = max(recalc.candidates_total - recalc.candidates_processed, 0)
    recalc.status = "failed"
    recalc.candidates_failed = remaining
    recalc.error_code = "MATCHING_RECALC_TIMEOUT"
    recalc.error_message = "Recalculation heartbeat exceeded the configured timeout."
    recalc.finished_at = _utcnow()
    recalc.heartbeat_at = recalc.finished_at


# Return whether a pending or running task has exceeded its activity lease.
def _recalculation_is_stale(recalc: MatchingRecalcJob) -> bool:
    activity = recalc.heartbeat_at or recalc.started_at or recalc.created_at
    if activity is None:
        return True
    if activity.tzinfo is not None:
        activity = activity.astimezone(timezone.utc).replace(tzinfo=None)
    timeout = timedelta(seconds=max(settings.matching_recalc_timeout_seconds, 1))
    return activity < _utcnow() - timeout


# Convert internal exceptions into stable operational error codes.
def _error_code(exc: Exception) -> str:
    text = str(exc)
    if text.startswith("MATCHING_"):
        return text.split(":", 1)[0]
    return "MATCHING_RECALC_FAILED"


# Return a naive UTC value compatible with existing application timestamps.
def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Serialize an optional timestamp for immutable JSON snapshots.
def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
