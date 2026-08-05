from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.config import settings
from app.models.database import DepartmentConfig
from app.models.schemas import JobConfigUpdateRequest, JobConfigUpdateResponse, JobCreateRequest, JobResponse

router = APIRouter(prefix="/jobs")
logger = logging.getLogger(__name__)


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreateRequest, db: AsyncSession = Depends(get_db_session)) -> JobResponse:
    try:
        config = dict(payload.config)
        config["jd_text"] = payload.jd_text
        job = DepartmentConfig(
            department_name=payload.department_name,
            position_name=payload.position_name,
            config_version="v1.0",
            config=config,
            is_active=True,
            created_by=payload.created_by,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return JobResponse(
            version=settings.app_version,
            id=job.id,
            department_name=job.department_name,
            position_name=job.position_name,
            config_version=job.config_version,
            config=job.config,
        )
    except Exception as exc:
        logger.exception("Failed to create job.")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create job.") from exc


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db_session)) -> JobResponse:
    stmt = select(DepartmentConfig).where(DepartmentConfig.id == job_id, DepartmentConfig.is_active.is_(True))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    return JobResponse(
        version=settings.app_version,
        id=job.id,
        department_name=job.department_name,
        position_name=job.position_name,
        config_version=job.config_version,
        config=job.config,
    )


@router.put("/{job_id}/config", response_model=JobConfigUpdateResponse)
async def update_job_config(
    job_id: UUID,
    payload: JobConfigUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JobConfigUpdateResponse:
    stmt = select(DepartmentConfig).where(DepartmentConfig.id == job_id, DepartmentConfig.is_active.is_(True))
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    try:
        job.config = payload.config
        current_version = job.config_version.replace("v", "")
        major, minor = current_version.split(".")
        job.config_version = f"v{major}.{int(minor) + 1}"
        job.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(job)
        return JobConfigUpdateResponse(
            version=settings.app_version,
            id=job.id,
            config_version=job.config_version,
            updated_at=job.updated_at,
        )
    except Exception as exc:
        logger.exception("Failed to update job config.")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update config.") from exc
