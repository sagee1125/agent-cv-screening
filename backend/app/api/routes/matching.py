# Exposes versioned candidate matching configuration, recalculation, and detail APIs.
from __future__ import annotations

import copy
import math
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.matching_errors import MatchingAPIError
from app.config import settings
from app.models.database import Resume
from app.models.matching_schemas import (
    CandidateMatchDetailResponse,
    LegacyWeightConfigUpdateRequest,
    MatchingConfigResponse,
    MatchingConfigUpdateRequest,
    MatchingRecalculateRequest,
    MatchingRecalculateResponse,
    MatchingRecalculationStatusResponse,
)
from app.services.candidate_matching.contracts import MatchingConfigError
from app.services.matching_service import (
    MatchingRateLimitError,
    create_recalculation,
    effective_matching_config,
    get_matching_job,
    get_published_candidate_score,
    get_recalculation,
    save_matching_config,
    schedule_recalculation_task,
)

router = APIRouter(prefix="/jobs")


# Reject matching routes when the deployment feature flag is disabled.
def _require_matching_enabled() -> None:
    if not settings.matching_enabled:
        raise MatchingAPIError(
            "MATCHING_DISABLED",
            "Candidate matching is disabled.",
            status_code=503,
            retryable=True,
        )


# Normalize weak and quoted entity tags for optimistic concurrency checks.
def _normalize_etag(value: str | None) -> str | None:
    if value is None:
        return None
    return value.removeprefix("W/").strip().strip('"')


# Convert config validation failures into stable matching API errors.
def _config_error(exc: MatchingConfigError) -> MatchingAPIError:
    status_code = 409 if exc.code == "MATCHING_JD_NOT_READY" else 422
    return MatchingAPIError(
        exc.code,
        str(exc),
        status_code=status_code,
        details={"field_errors": []},
    )


@router.get(
    "/{job_id}/matching/config",
    response_model=MatchingConfigResponse,
    dependencies=[Depends(_require_matching_enabled)],
)
async def get_matching_config(
    job_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> MatchingConfigResponse:
    """Return the effective validated configuration and its normalized weights."""
    job = await get_matching_job(db, job_id)
    if job is None:
        raise MatchingAPIError(
            "MATCHING_JOB_NOT_FOUND",
            "Job Post was not found.",
            status_code=404,
        )
    try:
        effective = effective_matching_config(job)
    except MatchingConfigError as exc:
        raise _config_error(exc) from exc
    response.headers["ETag"] = f'"{effective.config_hash}"'
    normalized = {
        dimension_id: float(config["normalized_weight"])
        for dimension_id, config in effective.config["dimensions"].items()
    }
    return MatchingConfigResponse(
        version=settings.app_version,
        schema_version=settings.matching_schema_version,
        job_post_id=job.id,
        config=effective.config,
        normalized_weights=normalized,
        config_hash=effective.config_hash,
        updated_at=job.updated_at,
    )


@router.put(
    "/{job_id}/matching/config",
    response_model=MatchingConfigResponse,
    dependencies=[Depends(_require_matching_enabled)],
)
async def update_matching_config(
    job_id: UUID,
    payload: MatchingConfigUpdateRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: AsyncSession = Depends(get_db_session),
) -> MatchingConfigResponse:
    """Validate and replace one Job Post matching configuration."""
    job = await get_matching_job(db, job_id, for_update=True)
    if job is None:
        raise MatchingAPIError(
            "MATCHING_JOB_NOT_FOUND",
            "Job Post was not found.",
            status_code=404,
        )
    try:
        current = effective_matching_config(job)
        if if_match is not None and _normalize_etag(if_match) != current.config_hash:
            raise MatchingAPIError(
                "MATCHING_CONFIG_CONFLICT",
                "Matching configuration changed since it was read.",
                status_code=409,
                details={"current_config_hash": current.config_hash},
            )
        explicit = payload.config.model_dump(mode="json")
        effective = await save_matching_config(db, job, explicit)
    except MatchingConfigError as exc:
        await db.rollback()
        raise _config_error(exc) from exc

    response.headers["ETag"] = f'"{effective.config_hash}"'
    normalized = {
        dimension_id: float(config["normalized_weight"])
        for dimension_id, config in effective.config["dimensions"].items()
    }
    return MatchingConfigResponse(
        version=settings.app_version,
        schema_version=settings.matching_schema_version,
        job_post_id=job.id,
        config=effective.config,
        normalized_weights=normalized,
        config_hash=effective.config_hash,
        updated_at=job.updated_at,
    )


# Remove derived activation fields before persisting a compatibility config.
def _persistable_config(config: dict[str, Any]) -> dict[str, Any]:
    persisted = copy.deepcopy(config)
    persisted.pop("education_requirement", None)
    persisted.pop("target_seniority", None)
    for dimension in persisted.get("dimensions", {}).values():
        if isinstance(dimension, dict):
            dimension.pop("active", None)
            dimension.pop("normalized_weight", None)
    return persisted


@router.put(
    "/{job_id}/weight",
    response_model=MatchingConfigResponse,
    dependencies=[Depends(_require_matching_enabled)],
    include_in_schema=False,
)
async def update_legacy_job_weight(
    job_id: UUID,
    payload: LegacyWeightConfigUpdateRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> MatchingConfigResponse:
    """Map existing frontend skill weights into the matching configuration."""
    job = await get_matching_job(db, job_id, for_update=True)
    if job is None:
        raise MatchingAPIError(
            "MATCHING_JOB_NOT_FOUND",
            "Job Post was not found.",
            status_code=404,
        )
    try:
        current = effective_matching_config(job)
        explicit = _persistable_config(current.config)
        incoming_skills = payload.weight_config_json.get("skills") or []
        weight_by_id = {
            str(item.get("skill_id") or item.get("skillId")): float(item["weight"])
            for item in incoming_skills
            if isinstance(item, dict)
            and (item.get("skill_id") or item.get("skillId"))
            and item.get("weight") is not None
        }
        if any(weight <= 0 or not math.isfinite(weight) for weight in weight_by_id.values()):
            raise ValueError("skill weights must be finite and positive")
        for skill in explicit.get("must_skills", []):
            if skill.get("skill_id") in weight_by_id:
                skill["weight"] = weight_by_id[skill["skill_id"]]
        job.weight_config_json = payload.weight_config_json
        effective = await save_matching_config(db, job, explicit)
    except (MatchingConfigError, TypeError, ValueError) as exc:
        await db.rollback()
        if isinstance(exc, MatchingConfigError):
            raise _config_error(exc) from exc
        raise MatchingAPIError(
            "MATCHING_CONFIG_INVALID",
            "Legacy skill weights are invalid.",
            status_code=422,
        ) from exc

    response.headers["ETag"] = f'"{effective.config_hash}"'
    normalized = {
        dimension_id: float(config["normalized_weight"])
        for dimension_id, config in effective.config["dimensions"].items()
    }
    return MatchingConfigResponse(
        version=settings.app_version,
        schema_version=settings.matching_schema_version,
        job_post_id=job.id,
        config=effective.config,
        normalized_weights=normalized,
        config_hash=effective.config_hash,
        updated_at=job.updated_at,
    )


@router.post(
    "/{job_id}/matching/recalculate",
    response_model=MatchingRecalculateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_require_matching_enabled)],
)
async def recalculate_matching(
    job_id: UUID,
    payload: MatchingRecalculateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    requested_by: str | None = Header(default=None, alias="X-User-ID"),
    db: AsyncSession = Depends(get_db_session),
) -> MatchingRecalculateResponse:
    """Persist and enqueue one idempotent matching recalculation."""
    if not idempotency_key or len(idempotency_key) > 128:
        raise MatchingAPIError(
            "MATCHING_CONFIG_INVALID",
            "A valid Idempotency-Key header is required.",
            status_code=400,
        )
    try:
        recalc, created = await create_recalculation(
            db,
            job_post_id=job_id,
            idempotency_key=idempotency_key,
            trigger=payload.trigger,
            reason=payload.reason,
            requested_by=requested_by,
        )
    except LookupError as exc:
        raise MatchingAPIError(
            "MATCHING_JOB_NOT_FOUND",
            "Job Post was not found.",
            status_code=404,
        ) from exc
    except MatchingConfigError as exc:
        raise _config_error(exc) from exc
    except MatchingRateLimitError as exc:
        raise MatchingAPIError(
            "MATCHING_RATE_LIMITED",
            "Too many recalculation requests for this Job Post.",
            status_code=429,
            retryable=True,
        ) from exc
    except RuntimeError as exc:
        raise MatchingAPIError(
            "MATCHING_RECALC_IN_PROGRESS",
            "Recalculation is already running.",
            status_code=409,
            retryable=True,
            details={"recalc_job_id": str(exc)},
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        try:
            recalc, created = await create_recalculation(
                db,
                job_post_id=job_id,
                idempotency_key=idempotency_key,
                trigger=payload.trigger,
                reason=payload.reason,
                requested_by=requested_by,
            )
        except Exception as retry_exc:
            raise MatchingAPIError(
                "MATCHING_RECALC_IN_PROGRESS",
                "A concurrent recalculation already reserved this version.",
                status_code=409,
                retryable=True,
            ) from retry_exc

    if created:
        schedule_recalculation_task(recalc.id)
    return MatchingRecalculateResponse(
        version=settings.app_version,
        schema_version=settings.matching_schema_version,
        job_post_id=job_id,
        recalc_job_id=recalc.id,
        target_score_version=recalc.target_score_version,
        status=recalc.status,
        candidates_queued=recalc.candidates_total,
    )


@router.post(
    "/{job_id}/recalculate",
    response_model=MatchingRecalculateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_require_matching_enabled)],
    include_in_schema=False,
)
async def recalculate_matching_legacy(
    job_id: UUID,
    payload: MatchingRecalculateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> MatchingRecalculateResponse:
    """Trigger recalculation for the existing frontend without an idempotency header."""
    try:
        recalc, _ = await create_recalculation(
            db,
            job_post_id=job_id,
            idempotency_key=f"legacy-{uuid4()}",
            trigger=payload.trigger,
            reason=payload.reason,
            requested_by=None,
        )
    except LookupError as exc:
        raise MatchingAPIError(
            "MATCHING_JOB_NOT_FOUND",
            "Job Post was not found.",
            status_code=404,
        ) from exc
    except MatchingConfigError as exc:
        raise _config_error(exc) from exc
    except MatchingRateLimitError as exc:
        raise MatchingAPIError(
            "MATCHING_RATE_LIMITED",
            "Too many recalculation requests for this Job Post.",
            status_code=429,
            retryable=True,
        ) from exc
    except RuntimeError as exc:
        raise MatchingAPIError(
            "MATCHING_RECALC_IN_PROGRESS",
            "Recalculation is already running.",
            status_code=409,
            retryable=True,
            details={"recalc_job_id": str(exc)},
        ) from exc

    schedule_recalculation_task(recalc.id)
    return MatchingRecalculateResponse(
        version=settings.app_version,
        schema_version=settings.matching_schema_version,
        job_post_id=job_id,
        recalc_job_id=recalc.id,
        target_score_version=recalc.target_score_version,
        status=recalc.status,
        candidates_queued=recalc.candidates_total,
    )


@router.get(
    "/{job_id}/matching/recalculations/{recalc_job_id}",
    response_model=MatchingRecalculationStatusResponse,
    dependencies=[Depends(_require_matching_enabled)],
)
async def get_matching_recalculation(
    job_id: UUID,
    recalc_job_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> MatchingRecalculationStatusResponse:
    """Return matching recalculation progress and terminal diagnostics."""
    recalc = await get_recalculation(db, job_id, recalc_job_id)
    if recalc is None:
        raise MatchingAPIError(
            "MATCHING_RECALC_NOT_FOUND",
            "Recalculation job was not found.",
            status_code=404,
        )
    return MatchingRecalculationStatusResponse(
        version=settings.app_version,
        schema_version=settings.matching_schema_version,
        recalc_job_id=recalc.id,
        job_post_id=recalc.job_post_id,
        target_score_version=recalc.target_score_version,
        status=recalc.status,
        candidates_total=recalc.candidates_total,
        candidates_processed=recalc.candidates_processed,
        candidates_failed=recalc.candidates_failed,
        error_code=recalc.error_code,
        error_message=recalc.error_message,
        created_at=recalc.created_at,
        started_at=recalc.started_at,
        heartbeat_at=recalc.heartbeat_at,
        finished_at=recalc.finished_at,
    )


@router.get(
    "/{job_id}/matching/candidates/{candidate_id}",
    response_model=CandidateMatchDetailResponse,
    dependencies=[Depends(_require_matching_enabled)],
)
async def get_candidate_matching_detail(
    job_id: UUID,
    candidate_id: UUID,
    score_version: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db_session),
) -> CandidateMatchDetailResponse:
    """Return one complete published radar, evidence, eligibility, and question result."""
    job = await get_matching_job(db, job_id)
    if job is None:
        raise MatchingAPIError(
            "MATCHING_JOB_NOT_FOUND",
            "Job Post was not found.",
            status_code=404,
        )
    linked = (
        await db.execute(
            select(Resume.id).where(
                Resume.job_post_id == job_id,
                Resume.candidate_id == candidate_id,
            )
        )
    ).scalar_one_or_none()
    if linked is None:
        raise MatchingAPIError(
            "MATCHING_CANDIDATE_NOT_FOUND",
            "Candidate is not linked to this Job Post.",
            status_code=404,
        )
    score = await get_published_candidate_score(
        db,
        job=job,
        candidate_id=candidate_id,
        score_version=score_version,
    )
    if score is None:
        raise MatchingAPIError(
            "MATCHING_SCORE_NOT_READY",
            "Candidate score is not ready.",
            status_code=409,
            retryable=True,
        )

    stale = score.score_version != job.current_score_version or job.matching_status != "ready"
    snapshot = score.input_snapshot or {}
    metadata: dict[str, Any] = {
        "config_hash": score.config_hash,
        "cv_file_hash": score.cv_file_hash,
        "jd_updated_at": snapshot.get("jd_updated_at"),
        "cv_extracted_at": snapshot.get("cv_extracted_at"),
        "reference_date": snapshot.get("reference_date"),
        "scored_at": score.scored_at,
    }
    return CandidateMatchDetailResponse(
        version=settings.app_version,
        schema_version=score.schema_version,
        job_post_id=job.id,
        candidate_id=score.candidate_id,
        resume_id=score.resume_id,
        score_version=score.score_version,
        algorithm_version=score.algorithm_version,
        scoring_status="stale" if stale else "ready",
        stale=stale,
        recommendation_rank=score.recommendation_rank,
        match_score=float(score.total_score),
        fit_band=score.fit_band,
        eligibility={
            "status": score.eligibility_status,
            "results": score.eligibility_results,
        },
        evidence_confidence=float(score.evidence_confidence),
        radar_dimensions=score.dimension_results,
        interview_questions=score.interview_questions,
        metadata=metadata,
    )
