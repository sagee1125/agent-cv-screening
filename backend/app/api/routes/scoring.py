from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_db_session, get_scorer_service
from app.config import settings
from app.models.database import Candidate, DepartmentConfig, ExtractedData, Resume, ScoringResult
from app.models.schemas import ScoreDetailResponse, ScoreStartResponse, ScoringListItem, ScoringListResponse
from app.services.scorer import ScorerService

router = APIRouter(prefix="/jobs")
logger = logging.getLogger(__name__)


@router.post("/{job_id}/score", response_model=ScoreStartResponse)
async def score_job_candidates(
    job_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    scorer: ScorerService = Depends(get_scorer_service),
) -> ScoreStartResponse:
    job = (
        await db.execute(select(DepartmentConfig).where(DepartmentConfig.id == job_id, DepartmentConfig.is_active.is_(True)))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    stmt = (
        select(Resume, Candidate, ExtractedData)
        .join(Candidate, Candidate.id == Resume.candidate_id)
        .join(ExtractedData, ExtractedData.resume_id == Resume.id)
        .where(ExtractedData.status == "success")
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return ScoreStartResponse(
            version=settings.app_version,
            job_id=job_id,
            status="scoring_started",
            candidates_queued=0,
        )

    scored_items: list[dict[str, object]] = []
    for resume, candidate, extracted in rows:
        score_payload = scorer.score_candidate(extracted.structured_data, job.config)
        scored_items.append(
            {
                "candidate_id": candidate.id,
                "resume_id": resume.id,
                "score_payload": score_payload,
            }
        )

    ranked = scorer.rank(
        [
            {
                "candidate_id": item["candidate_id"],
                "total_score": item["score_payload"]["total_score"],
            }
            for item in scored_items
        ]
    )
    candidate_rank_map = {item["candidate_id"]: item["rank"] for item in ranked}

    for item in scored_items:
        payload = item["score_payload"]
        result = ScoringResult(
            resume_id=item["resume_id"],
            config_id=job.id,
            config_version_at_time=job.config_version,
            dimension_scores=payload["dimension_scores"],
            total_score=payload["total_score"],
            tier=payload["tier"],
            rank=candidate_rank_map[item["candidate_id"]],
            full_snapshot=payload["full_snapshot"],
        )
        db.add(result)

    await db.commit()
    return ScoreStartResponse(
        version=settings.app_version,
        job_id=job_id,
        status="scoring_started",
        candidates_queued=len(scored_items),
    )


@router.get("/{job_id}/results", response_model=ScoringListResponse)
async def list_scoring_results(
    job_id: UUID,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    tier: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> ScoringListResponse:
    offset = (page - 1) * limit
    filters = [ScoringResult.config_id == job_id]
    if tier:
        filters.append(ScoringResult.tier == tier)

    count_stmt = select(func.count(ScoringResult.id)).where(*filters)
    data_stmt = (
        select(ScoringResult, Resume, Candidate)
        .join(Resume, Resume.id == ScoringResult.resume_id)
        .join(Candidate, Candidate.id == Resume.candidate_id)
        .where(*filters)
        .order_by(ScoringResult.rank.asc())
        .offset(offset)
        .limit(limit)
    )

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(data_stmt)).all()
    items = [
        ScoringListItem(
            rank=scoring.rank,
            candidate_id=candidate.id,
            total_score=Decimal(str(scoring.total_score)),
            tier=scoring.tier,
        )
        for scoring, _, candidate in rows
    ]
    return ScoringListResponse(version=settings.app_version, items=items, total=total, page=page, limit=limit)


@router.get("/{job_id}/results/{candidate_id}", response_model=ScoreDetailResponse)
async def get_candidate_score_detail(
    job_id: UUID,
    candidate_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ScoreDetailResponse:
    stmt = (
        select(ScoringResult)
        .join(Resume, Resume.id == ScoringResult.resume_id)
        .where(ScoringResult.config_id == job_id, Resume.candidate_id == candidate_id)
        .options(selectinload(ScoringResult.resume))
        .order_by(ScoringResult.scored_at.desc())
    )
    score = (await db.execute(stmt)).scalars().first()
    if not score:
        raise HTTPException(status_code=404, detail="Scoring result not found.")

    return ScoreDetailResponse(
        version=settings.app_version,
        candidate_id=candidate_id,
        dimension_scores={key: float(value) for key, value in score.dimension_scores.items()},
        total_score=Decimal(str(score.total_score)),
        tier=score.tier,
        skill_match_details=score.full_snapshot.get("skill_match_details", {}),
        rank=score.rank,
    )
