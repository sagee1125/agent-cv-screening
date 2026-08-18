# TODO(agent-migration): This legacy REST router exists for the traditional frontend.
# It invokes the shared skill layer (app.skills.jd_parse) for JD parsing, then persists
# results to the DB. When the API is deprecated, delete this router; the integrated agent
# calls .codex/skills/jd-parser/scripts/run_jd_parse.py directly instead.
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_db_session, get_jd_parser_service
from app.config import settings
from app.models.database import JobPost, JobPostStatus, Resume
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
    PolyUCatalogItem,
    PolyUCatalogResponse,
    PolyUImportRequest,
    PolyUImportResponse,
)
from app.skills.jd_parse import parse_jd_skill
from app.services.jd_parser import JDParserService
from app.services.polyu_jobs import (
    POLYU_SOURCE,
    PolyUListing,
    build_job_description,
    fetch_polyu_detail,
    fetch_polyu_listings,
)

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
        parse_result = await parse_jd_skill(description, parser=parser)
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


@router.get("/sync-polyu/catalog", response_model=PolyUCatalogResponse)
async def list_polyu_catalog(db: AsyncSession = Depends(get_db_session)) -> PolyUCatalogResponse:
    """Fetch the PolyU general jobs table and mark rows already imported."""
    try:
        listings = await fetch_polyu_listings()
    except httpx.HTTPError as exc:
        logger.exception("Failed to fetch PolyU job catalog.")
        raise HTTPException(status_code=502, detail="Failed to fetch PolyU job listings.") from exc

    refs = [item.external_ref for item in listings]
    existing: set[str] = set()
    if refs:
        existing_stmt = select(JobPost.external_ref).where(
            JobPost.source == POLYU_SOURCE,
            JobPost.external_ref.in_(refs),
        )
        existing = {row[0] for row in (await db.execute(existing_stmt)).all() if row[0]}

    items = [
        PolyUCatalogItem(
            job_code=item.job_code,
            external_ref=item.external_ref,
            title=item.title,
            department=item.department,
            closing_date=item.closing_date,
            detail_url=item.detail_url,
            already_imported=item.external_ref in existing,
        )
        for item in listings
    ]
    return PolyUCatalogResponse(
        version=settings.app_version,
        items=items,
        total=len(items),
        new_count=sum(1 for item in items if not item.already_imported),
    )


@router.post("/sync-polyu/import", response_model=PolyUImportResponse)
async def import_polyu_job(
    payload: PolyUImportRequest,
    db: AsyncSession = Depends(get_db_session),
    parser: JDParserService = Depends(get_jd_parser_service),
) -> PolyUImportResponse:
    """Import one PolyU job, parse its JD, and persist it as a draft Job Post."""
    existing_stmt = select(JobPost).where(
        JobPost.source == POLYU_SOURCE,
        JobPost.external_ref == payload.external_ref.strip(),
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        return PolyUImportResponse(
            version=settings.app_version,
            action="skipped",
            job=_serialize_job(existing),
        )

    listing = PolyUListing(
        job_code=payload.job_code.strip(),
        external_ref=payload.external_ref.strip(),
        title=payload.title.strip(),
        department=payload.department.strip(),
        closing_date=payload.closing_date,
        detail_url=payload.detail_url.strip(),
    )
    try:
        detail_text, posting_date = await fetch_polyu_detail(listing)
    except httpx.HTTPError as exc:
        logger.exception("Failed to fetch PolyU job detail for %s.", listing.external_ref)
        raise HTTPException(status_code=502, detail="Failed to fetch PolyU job detail.") from exc

    description = _normalize_description(build_job_description(listing, detail_text))
    parsed: dict[str, Any] = {}
    parse_error: str | None = None
    try:
        parse_result = await parse_jd_skill(description, parser=parser)
        structured = parse_result.get("structured_data")
        if isinstance(structured, dict):
            parsed = structured
        else:
            parse_error = str(parse_result.get("error_message") or "Failed to parse JD.")
    except Exception as exc:
        logger.exception("Failed to parse imported PolyU JD %s.", listing.external_ref)
        parse_error = str(exc)

    job = JobPost(
        title=listing.title,
        description=description,
        head_count=1,
        status=JobPostStatus.DRAFT,
        start_date=posting_date or _utcnow(),
        closed_date=listing.closing_date,
        jd_parsed_json=parsed,
        weight_config_json=_default_weight_config(parsed) if parsed else {},
        source=POLYU_SOURCE,
        external_ref=listing.external_ref,
    )
    db.add(job)
    try:
        await db.commit()
        await db.refresh(job)
    except IntegrityError:
        await db.rollback()
        existing_after_conflict = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing_after_conflict:
            return PolyUImportResponse(
                version=settings.app_version,
                action="skipped",
                job=_serialize_job(existing_after_conflict),
            )
        raise HTTPException(status_code=500, detail="Failed to save imported PolyU job.")
    except Exception as exc:
        logger.exception("Failed to save imported PolyU job %s.", listing.external_ref)
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save imported PolyU job.") from exc

    return PolyUImportResponse(
        version=settings.app_version,
        action="created",
        job=_serialize_job(job),
        parse_error=parse_error,
    )


@router.get("/{job_id}", response_model=JobPostDetailResponse)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db_session)) -> JobPostDetailResponse:
    stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    candidates_stmt = (
        select(Resume)
        .where(Resume.job_post_id == job_id)
        .options(
            selectinload(Resume.candidate),
            selectinload(Resume.extracted_data),
        )
        .order_by(Resume.uploaded_at.desc())
    )
    resume_rows = (await db.execute(candidates_stmt)).scalars().all()

    candidates = [
        {
            "candidate_id": row.candidate_id,
            "resume_id": row.id,
            "candidate_name": row.candidate.name if row.candidate else None,
            "candidate_email": row.candidate.email if row.candidate else None,
            "original_filename": row.original_filename,
            "source_channel": row.source_channel,
            "cv_parse_status": (row.extracted_data.status if row.extracted_data else "pending"),
            "extracted_data": (row.extracted_data.structured_data if row.extracted_data else None),
            "uploaded_at": row.uploaded_at,
        }
        for row in resume_rows
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

    total_stmt = select(func.count(Resume.id)).where(Resume.job_post_id == job_id)
    total = (await db.execute(total_stmt)).scalar_one()
    offset = (page - 1) * limit
    rows_stmt = (
        select(Resume)
        .where(Resume.job_post_id == job_id)
        .options(
            selectinload(Resume.candidate),
            selectinload(Resume.extracted_data),
        )
        .order_by(Resume.uploaded_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return JobCandidateListResponse(
        version=settings.app_version,
        items=[
            JobCandidateSummaryItem(
                candidate_id=row.candidate_id,
                resume_id=row.id,
                candidate_name=row.candidate.name if row.candidate else None,
                candidate_email=row.candidate.email if row.candidate else None,
                original_filename=row.original_filename,
                source_channel=row.source_channel,
                cv_parse_status=(row.extracted_data.status if row.extracted_data else "pending"),
                extracted_data=(row.extracted_data.structured_data if row.extracted_data else None),
                uploaded_at=row.uploaded_at,
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
            Resume.source_channel,
            func.count(Resume.id).label("candidate_count"),
        )
        .where(Resume.job_post_id == job_id)
        .group_by(Resume.source_channel)
        .order_by(func.count(Resume.id).desc())
    )
    rows = (await db.execute(stats_stmt)).all()
    by_channel = [
        JobChannelStatItem(
            source_channel=row.source_channel,
            candidate_count=int(row.candidate_count),
            avg_match_score=0.0,
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

    rows_stmt = select(Resume).where(Resume.job_post_id == job_id)
    rows = (await db.execute(rows_stmt)).scalars().all()
    total = len(rows)
    if total == 0 or len(must_skills) == 0:
        return JobDiagnosisResponse(version=settings.app_version, job_post_id=job_id, must_skill_satisfaction=[])

    # Scoring is not yet wired to resumes, so satisfaction is unknown until scores are populated.
    base_rate = 0.0
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

    parse_result = await parse_jd_skill(payload.jd_text, parser=parser)
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
