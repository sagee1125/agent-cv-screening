from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.config import settings
from app.models.database import Candidate, DepartmentConfig, ExtractedData, Resume, ScoringResult
from app.models.schemas import ComparisonReportRequest, ReportGenerationRequest, ReportGenerationResponse
from app.services.reporter import ReporterService

router = APIRouter(prefix="/reports")
reporter = ReporterService()


@router.post("/candidate/{candidate_id}", response_model=ReportGenerationResponse)
async def generate_candidate_report(
    candidate_id: UUID,
    payload: ReportGenerationRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ReportGenerationResponse:
    stmt = (
        select(ScoringResult, Resume, Candidate, ExtractedData, DepartmentConfig)
        .join(Resume, Resume.id == ScoringResult.resume_id)
        .join(Candidate, Candidate.id == Resume.candidate_id)
        .join(ExtractedData, ExtractedData.resume_id == Resume.id)
        .join(DepartmentConfig, DepartmentConfig.id == ScoringResult.config_id)
        .where(ScoringResult.config_id == payload.job_id, Candidate.id == candidate_id)
        .order_by(ScoringResult.scored_at.desc())
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Scoring result not found for candidate.")

    scoring, _, candidate, extracted, job = row
    report_id = uuid4().hex
    output_path = Path(settings.report_dir) / f"{report_id}.pdf"

    snapshot = scoring.full_snapshot or {}
    skill_details = snapshot.get("skill_match_details", {})
    dimension_scores = snapshot.get("dimension_scores", scoring.dimension_scores or {})

    await asyncio.to_thread(
        reporter.generate_candidate_one_pager_pdf,
        str(output_path),
        display_label=str(candidate.id),
        position_name=job.position_name,
        report_date=datetime.utcnow(),
        total_score=float(scoring.total_score),
        tier=scoring.tier,
        rank=scoring.rank,
        education=extracted.structured_data.get("education", []),
        experience=extracted.structured_data.get("experience", []),
        skill_hit=skill_details.get("hit", []),
        skill_miss=skill_details.get("miss", []),
        hit_rate=float(dimension_scores.get("skill_match", 0)),
        dimension_scores={k: float(v) for k, v in dimension_scores.items()},
        interview_suggestions=snapshot.get("interview_suggestions", []),
        version=settings.app_version,
    )

    return ReportGenerationResponse(
        version=settings.app_version,
        report_id=report_id,
        download_url=f"/api/v1/reports/download/{report_id}",
    )


@router.post("/comparison/{job_id}", response_model=ReportGenerationResponse)
async def generate_comparison_report(
    job_id: UUID,
    payload: ComparisonReportRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ReportGenerationResponse:
    if payload.format.lower() != "excel":
        raise HTTPException(status_code=400, detail="Comparison report currently supports `excel` only.")

    stmt = (
        select(ScoringResult, Resume, Candidate, DepartmentConfig)
        .join(Resume, Resume.id == ScoringResult.resume_id)
        .join(Candidate, Candidate.id == Resume.candidate_id)
        .join(DepartmentConfig, DepartmentConfig.id == ScoringResult.config_id)
        .where(ScoringResult.config_id == job_id)
        .order_by(ScoringResult.rank.asc())
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No scoring results found.")

    report_id = uuid4().hex
    output_path = Path(settings.report_dir) / f"{report_id}.xlsx"

    first_job = rows[0][3]
    excel_rows: list[dict[str, object]] = []
    for scoring, _, candidate, _ in rows:
        snapshot = scoring.full_snapshot or {}
        dimensions = snapshot.get("dimension_scores", scoring.dimension_scores or {})
        suggestions = snapshot.get("interview_suggestions", [])
        suggestion_summary = "; ".join(
            f"{item.get('rule_id', '')}:{item.get('severity', '')}" for item in suggestions[:3]
        )
        excel_rows.append(
            {
                "rank": scoring.rank,
                "refno": None,
                "appno": str(candidate.id),
                "total_score": float(scoring.total_score),
                "skill_match": float(dimensions.get("skill_match", 0)),
                "experience_match": float(dimensions.get("experience_match", 0)),
                "education_match": float(dimensions.get("education_match", 0)),
                "research_quality": float(dimensions.get("research_quality", 0)),
                "tier": scoring.tier,
                "suggestion_summary": suggestion_summary,
            }
        )

    await asyncio.to_thread(
        reporter.generate_comparison_excel,
        str(output_path),
        position_name=first_job.position_name,
        report_date=datetime.utcnow(),
        rows=excel_rows,
    )
    return ReportGenerationResponse(
        version=settings.app_version,
        report_id=report_id,
        download_url=f"/api/v1/reports/download/{report_id}",
    )


@router.get("/download/{report_id}")
async def download_report(report_id: str) -> FileResponse:
    report_dir = Path(settings.report_dir)
    candidates = list(report_dir.glob(f"{report_id}.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Report not found.")
    path = candidates[0]
    media_type = "application/octet-stream"
    if path.suffix == ".json":
        media_type = "application/json"
    elif path.suffix == ".xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif path.suffix == ".pdf":
        media_type = "application/pdf"
    return FileResponse(path=str(path), filename=path.name, media_type=media_type)
