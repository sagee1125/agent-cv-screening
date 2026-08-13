from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_jd_parser_service
from app.config import settings
from app.models.database import JobCandidate, JobPost, JobPostStatus
from app.models.schemas import (
    JDParseRequest,
    JDParseResponse,
    JobCandidateListResponse,
    JobCandidateSummaryItem,
    JobChannelStatItem,
    JobChannelStatsResponse,
    JobDiagnosisItem,
    JobDiagnosisResponse,
    JobPostCreateRequest,
    JobPostDetailResponse,
    JobPostDuplicateResponse,
    JobPostItemResponse,
    JobPostListResponse,
    JobPostMutationResponse,
    JobPostStatusUpdateRequest,
    JobPostUpdateRequest,
)
from app.services.jd_parser import JDParserService

router = APIRouter(prefix="/jobs")
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _status_from_string(value: str) -> JobPostStatus:
    mapping = {
        "draft": JobPostStatus.DRAFT,
        "active": JobPostStatus.ACTIVE,
        "closed": JobPostStatus.CLOSED,
    }
    normalized = value.strip().lower()
    if normalized not in mapping:
        raise HTTPException(status_code=400, detail="Invalid status, expected draft|active|closed.")
    return mapping[normalized]


def _normalize_description(value: str) -> str:
    # Keep user-authored line breaks while normalizing line-ending styles.
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _serialize_job(job: JobPost) -> JobPostItemResponse:
    description = job.description or ""
    return JobPostItemResponse(
        id=job.id,
        title=job.title,
        description=description,
        jd_summary_200=description[:200],
        head_count=job.head_count,
        status=job.status.value,
        start_date=job.start_date,
        closed_date=job.closed_date,
        jd_parsed_json=job.jd_parsed_json,
        weight_config_json=job.weight_config_json,
        created_at=job.created_at or _utcnow(),
        updated_at=job.updated_at or _utcnow(),
    )


@router.get("", response_model=JobPostListResponse)
async def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=12, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> JobPostListResponse:
    filters = [JobPost.deleted_at.is_(None)]
    if status_filter:
        filters.append(JobPost.status == _status_from_string(status_filter))

    total_stmt = select(func.count(JobPost.id)).where(*filters)
    total = (await db.execute(total_stmt)).scalar_one()

    offset = (page - 1) * limit
    rows_stmt = (
        select(JobPost)
        .where(*filters)
        .order_by(JobPost.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return JobPostListResponse(
        version=settings.app_version,
        items=[_serialize_job(row) for row in rows],
        total=total,
        page=page,
        limit=limit,
    )


@router.post("", response_model=JobPostItemResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobPostCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    parser: JDParserService = Depends(get_jd_parser_service),
) -> JobPostItemResponse:
    try:
        description = _normalize_description(payload.description)
        if not description.strip():
            raise HTTPException(status_code=422, detail="JD description is required.")
        ## parse the JD
        parse_result = await parser.parse_jd(description)
        parsed = parse_result.get("structured_data")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=422, detail=parse_result.get("error_message", "Failed to parse JD."))

        job = JobPost(
            title=payload.title.strip(),
            description=description,
            head_count=payload.head_count,
            status=_status_from_string(payload.status),
            start_date=payload.start_date,
            closed_date=payload.closed_date,
            jd_parsed_json=parsed,
            weight_config_json=_default_weight_config(parsed),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return _serialize_job(job)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create job.")
        await db.rollback()
        detail = f"Failed to create job: {exc}" if settings.debug else "Failed to create job."
        raise HTTPException(status_code=500, detail=detail) from exc


@router.get("/{job_id}", response_model=JobPostDetailResponse)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db_session)) -> JobPostDetailResponse:
    stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    candidates_stmt = select(JobCandidate).where(JobCandidate.job_post_id == job_id).order_by(JobCandidate.match_score.desc())
    candidate_rows = (await db.execute(candidates_stmt)).scalars().all()

    candidates = [
        {
            "candidate_id": row.candidate_id,
            "match_score": float(row.match_score),
            "fit_level": row.fit_level.value,
            "source_channel": row.source_channel,
            "cv_parse_status": row.cv_parse_status.value,
            "score_breakdown": row.score_breakdown_json,
        }
        for row in candidate_rows
    ]

    return JobPostDetailResponse(
        version=settings.app_version,
        job=_serialize_job(job),
        candidates=candidates,
    )


@router.get("/{job_id}/candidates", response_model=JobCandidateListResponse)
async def list_job_candidates(
    job_id: UUID,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> JobCandidateListResponse:
    job_stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(job_stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    total_stmt = select(func.count(JobCandidate.id)).where(JobCandidate.job_post_id == job_id)
    total = (await db.execute(total_stmt)).scalar_one()
    offset = (page - 1) * limit
    rows_stmt = (
        select(JobCandidate)
        .where(JobCandidate.job_post_id == job_id)
        .order_by(JobCandidate.match_score.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return JobCandidateListResponse(
        version=settings.app_version,
        items=[
            JobCandidateSummaryItem(
                candidate_id=row.candidate_id,
                match_score=float(row.match_score),
                fit_level=row.fit_level.value,
                source_channel=row.source_channel,
                cv_parse_status=row.cv_parse_status.value,
                score_breakdown=row.score_breakdown_json,
            )
            for row in rows
        ],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{job_id}/candidates/stats", response_model=JobChannelStatsResponse)
async def job_candidate_channel_stats(
    job_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> JobChannelStatsResponse:
    job_stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(job_stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    stats_stmt = (
        select(
            JobCandidate.source_channel,
            func.count(JobCandidate.id).label("candidate_count"),
            func.coalesce(func.avg(JobCandidate.match_score), 0).label("avg_match_score"),
        )
        .where(JobCandidate.job_post_id == job_id)
        .group_by(JobCandidate.source_channel)
        .order_by(func.count(JobCandidate.id).desc())
    )
    rows = (await db.execute(stats_stmt)).all()
    by_channel = [
        JobChannelStatItem(
            source_channel=row.source_channel,
            candidate_count=int(row.candidate_count),
            avg_match_score=float(row.avg_match_score),
        )
        for row in rows
    ]

    return JobChannelStatsResponse(version=settings.app_version, job_post_id=job_id, by_channel=by_channel)


@router.get("/{job_id}/diagnosis", response_model=JobDiagnosisResponse)
async def job_diagnosis(
    job_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> JobDiagnosisResponse:
    job_stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(job_stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    must_skills = []
    if isinstance(job.jd_parsed_json, dict):
        must_skills = job.jd_parsed_json.get("must_skills", []) or []

    rows_stmt = select(JobCandidate).where(JobCandidate.job_post_id == job_id)
    rows = (await db.execute(rows_stmt)).scalars().all()
    total = len(rows)
    if total == 0 or len(must_skills) == 0:
        return JobDiagnosisResponse(version=settings.app_version, job_post_id=job_id, must_skill_satisfaction=[])

    skill_scores = []
    for row in rows:
        breakdown = row.score_breakdown_json if isinstance(row.score_breakdown_json, dict) else {}
        skill_scores.append(float(breakdown.get("skill", 0)))
    base_rate = sum(1 for score in skill_scores if score >= 60) / total if total else 0.0

    diagnosis = []
    for idx, skill in enumerate(must_skills):
        skill_name = skill.get("display_name") or skill.get("canonical_skill") or f"must_skill_{idx + 1}"
        rate = max(0.0, min(1.0, base_rate - idx * 0.05))
        diagnosis.append(
            JobDiagnosisItem(
                skill=skill_name,
                satisfaction_rate=rate,
                flag_low=rate < 0.2,
            )
        )

    return JobDiagnosisResponse(
        version=settings.app_version,
        job_post_id=job_id,
        must_skill_satisfaction=diagnosis,
    )


@router.put("/{job_id}", response_model=JobPostItemResponse)
async def update_job(
    job_id: UUID,
    payload: JobPostUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JobPostItemResponse:
    stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    try:
        if payload.title is not None:
            job.title = payload.title.strip()
        if payload.description is not None:
            job.description = _normalize_description(payload.description)
        if payload.head_count is not None:
            job.head_count = payload.head_count
        if payload.start_date is not None:
            job.start_date = payload.start_date
        if payload.closed_date is not None:
            job.closed_date = payload.closed_date
        job.updated_at = _utcnow()
        await db.commit()
        await db.refresh(job)
        return _serialize_job(job)
    except Exception as exc:
        logger.exception("Failed to update job.")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update job.") from exc


@router.patch("/{job_id}/status", response_model=JobPostMutationResponse)
async def update_job_status(
    job_id: UUID,
    payload: JobPostStatusUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JobPostMutationResponse:
    stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    job.status = _status_from_string(payload.status)
    if payload.closed_date is not None:
        job.closed_date = payload.closed_date
    elif job.status == JobPostStatus.CLOSED and job.closed_date is None:
        job.closed_date = _utcnow()
    job.updated_at = _utcnow()

    await db.commit()
    await db.refresh(job)
    return JobPostMutationResponse(
        version=settings.app_version,
        id=job.id,
        status=job.status.value,
        updated_at=job.updated_at or _utcnow(),
    )


@router.delete("/{job_id}", response_model=JobPostMutationResponse)
async def archive_job(job_id: UUID, db: AsyncSession = Depends(get_db_session)) -> JobPostMutationResponse:
    stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    job.deleted_at = _utcnow()
    job.status = JobPostStatus.CLOSED
    job.closed_date = job.closed_date or _utcnow()
    job.updated_at = _utcnow()
    await db.commit()
    await db.refresh(job)
    return JobPostMutationResponse(
        version=settings.app_version,
        id=job.id,
        status=job.status.value,
        updated_at=job.updated_at or _utcnow(),
    )


@router.post("/{job_id}/duplicate", response_model=JobPostDuplicateResponse)
async def duplicate_job(job_id: UUID, db: AsyncSession = Depends(get_db_session)) -> JobPostDuplicateResponse:
    stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    source = (await db.execute(stmt)).scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Job not found.")

    duplicated = JobPost(
        title=f"{source.title} (Copy)",
        description=source.description,
        head_count=source.head_count,
        status=JobPostStatus.DRAFT,
        start_date=source.start_date,
        closed_date=None,
        jd_parsed_json=source.jd_parsed_json or {},
        weight_config_json=source.weight_config_json or {},
    )
    db.add(duplicated)
    await db.commit()
    await db.refresh(duplicated)
    return JobPostDuplicateResponse(version=settings.app_version, new_job_id=duplicated.id)


def _default_weight_config(parsed: dict[str, Any]) -> dict[str, Any]:
    skills: list[dict[str, Any]] = []
    for bucket in ("must_skills", "preferred_skills"):
        for item in parsed.get(bucket, []):
            skills.append(
                {
                    "skill_id": item.get("skill_id"),
                    "weight": item.get("weight", 1.0),
                }
            )
    return {"skills": skills}


@router.post("/{job_id}/parse-jd", response_model=JDParseResponse)
async def parse_jd(
    job_id: UUID,
    payload: JDParseRequest,
    db: AsyncSession = Depends(get_db_session),
    parser: JDParserService = Depends(get_jd_parser_service),
) -> JDParseResponse:
    stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    parse_result = await parser.parse_jd(payload.jd_text)
    parsed = parse_result.get("structured_data")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail=parse_result.get("error_message", "Failed to parse JD."))

    job.description = _normalize_description(payload.jd_text)
    job.jd_parsed_json = parsed
    job.weight_config_json = _default_weight_config(parsed)
    job.updated_at = _utcnow()
    await db.commit()
    await db.refresh(job)

    return JDParseResponse(
        version=settings.app_version,
        id=job.id,
        jd_parsed_json=job.jd_parsed_json,
        weight_config_json=job.weight_config_json,
        updated_at=job.updated_at or _utcnow(),
    )
