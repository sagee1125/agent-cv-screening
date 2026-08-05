from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.config import settings
from app.models.database import DepartmentConfig, FeedbackLog, Resume, ScoringResult
from app.models.schemas import FeedbackAnalyticsResponse, FeedbackLogRequest, FeedbackLogResponse

router = APIRouter(prefix="/feedback")


@router.post("", response_model=FeedbackLogResponse, status_code=status.HTTP_201_CREATED)
async def log_feedback(payload: FeedbackLogRequest, db: AsyncSession = Depends(get_db_session)) -> FeedbackLogResponse:
    exists_stmt = select(ScoringResult.id).where(ScoringResult.id == payload.scoring_result_id)
    exists = (await db.execute(exists_stmt)).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=404, detail="Scoring result not found.")

    row = FeedbackLog(
        scoring_result_id=payload.scoring_result_id,
        user_id=payload.user_id,
        action=payload.action,
        context=payload.context,
    )
    db.add(row)
    await db.commit()
    return FeedbackLogResponse(version=settings.app_version, status="logged")


@router.get("/analytics/{job_id}", response_model=FeedbackAnalyticsResponse)
async def feedback_analytics(job_id: UUID, db: AsyncSession = Depends(get_db_session)) -> FeedbackAnalyticsResponse:
    job = (await db.execute(select(DepartmentConfig).where(DepartmentConfig.id == job_id))).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    rows_stmt = (
        select(FeedbackLog, ScoringResult, Resume)
        .join(ScoringResult, ScoringResult.id == FeedbackLog.scoring_result_id)
        .join(Resume, Resume.id == ScoringResult.resume_id)
        .where(ScoringResult.config_id == job_id)
    )
    rows = (await db.execute(rows_stmt)).all()
    if not rows:
        return FeedbackAnalyticsResponse(
            version=settings.app_version,
            top_10_hit_rate=0.0,
            average_score_invited=0.0,
            avg_time_to_hire_days=0.0,
        )

    invited_rows = [row for row in rows if row[0].action == "invite"]
    top_10_hits = [row for row in invited_rows if row[1].rank <= 10]
    top_10_hit_rate = len(top_10_hits) / len(invited_rows) if invited_rows else 0.0

    average_score_invited = (
        sum(float(row[1].total_score) for row in invited_rows) / len(invited_rows) if invited_rows else 0.0
    )

    last_feedback_ts = max(
        (row[0].created_at for row in rows if isinstance(row[0].created_at, datetime)),
        default=None,
    )
    candidate_count_stmt = (
        select(func.count(distinct(Resume.candidate_id)))
        .select_from(ScoringResult)
        .join(Resume, Resume.id == ScoringResult.resume_id)
        .where(ScoringResult.config_id == job_id)
    )
    candidate_count = (await db.execute(candidate_count_stmt)).scalar_one() or 0
    avg_days = 0.0
    if last_feedback_ts and isinstance(job.created_at, datetime) and candidate_count > 0:
        elapsed_days = (last_feedback_ts - job.created_at).total_seconds() / 86400
        avg_days = elapsed_days / candidate_count

    return FeedbackAnalyticsResponse(
        version=settings.app_version,
        top_10_hit_rate=round(top_10_hit_rate, 4),
        average_score_invited=round(average_score_invited, 2),
        avg_time_to_hire_days=round(avg_days, 2),
    )
