from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_db_session, get_parser_service
from app.config import settings
from app.models.database import Candidate, ExtractedData, Resume
from app.models.schemas import (
    CandidateDetailResponse,
    CandidateListItem,
    CandidateListResponse,
    CandidateUploadResponse,
)
from app.services.parser import CVParserService

router = APIRouter(prefix="/candidates")
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=CandidateUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_candidate_cv(
    file: UploadFile = File(...),
    job_id: UUID | None = Form(default=None),
    email: str | None = Form(default=None),
    name: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db_session),
    parser: CVParserService = Depends(get_parser_service),
) -> CandidateUploadResponse:
    del job_id  # kept for API compatibility
    extracted: ExtractedData | None = None
    try:
        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(file.filename or "").suffix.lower()
        if ext != ".pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")

        stored_name = f"{uuid4().hex}{ext}"
        saved_path = upload_dir / stored_name
        content = await file.read()
        await asyncio.to_thread(saved_path.write_bytes, content)
        initial_hash = await parser.cache.md5_for_file(str(saved_path))

        candidate_email = email or f"unknown-{uuid4().hex[:8]}@example.com"
        candidate_name = name or "Unknown Candidate"
        candidate_phone = phone

        candidate = Candidate(email=candidate_email, name=candidate_name, phone=candidate_phone)
        db.add(candidate)
        await db.flush()

        resume = Resume(
            candidate_id=candidate.id,
            original_filename=file.filename or "uploaded.pdf",
            file_path=str(saved_path),
            file_hash=initial_hash,
        )
        db.add(resume)
        await db.flush()

        extracted = ExtractedData(
            resume_id=resume.id,
            structured_data={},
            raw_llm_response=None,
            extraction_model=settings.llm_model,
            extraction_seed=42,
            status="pending",
        )
        db.add(extracted)
        await db.flush()

        parse_result = await parser.parse_cv(str(saved_path))
        structured = parse_result["structured_data"]

        # Backfill candidate profile with parsed fields when available.
        if not email and structured.get("email"):
            candidate.email = str(structured["email"])
        if not name and structured.get("name"):
            candidate.name = str(structured["name"])
        if not phone and structured.get("phone"):
            candidate.phone = str(structured["phone"])

        resume.file_hash = parse_result["file_hash"]
        extracted.structured_data = structured
        extracted.raw_llm_response = parse_result.get("raw_llm_response")
        extracted.extraction_model = parse_result.get("extraction_model", settings.llm_model)
        extracted.extraction_seed = 42
        extracted.status = "success"
        extracted.error_message = None

        await db.commit()

        return CandidateUploadResponse(
            version=settings.app_version,
            id=candidate.id,
            status="processing",
            extracted_id=extracted.id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to upload candidate CV.")
        if extracted is not None:
            extracted.status = "failed"
            extracted.error_message = str(exc)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
        else:
            await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to upload CV.") from exc


@router.get("/{candidate_id}", response_model=CandidateDetailResponse)
async def get_candidate_detail(
    candidate_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> CandidateDetailResponse:
    stmt = (
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .options(selectinload(Candidate.resumes).selectinload(Resume.extracted_data))
    )
    candidate = (await db.execute(stmt)).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    extracted = None
    if candidate.resumes and candidate.resumes[0].extracted_data:
        extracted = candidate.resumes[0].extracted_data.structured_data

    return CandidateDetailResponse(
        version=settings.app_version,
        id=candidate.id,
        email=candidate.email,
        name=candidate.name,
        phone=candidate.phone,
        extracted_data=extracted,
    )


@router.get("", response_model=CandidateListResponse)
async def list_candidates(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> CandidateListResponse:
    offset = (page - 1) * limit
    filters = []
    if search:
        term = f"%{search}%"
        filters.append(or_(Candidate.name.ilike(term), Candidate.email.ilike(term)))

    count_stmt = select(func.count(Candidate.id))
    data_stmt = select(Candidate).order_by(Candidate.created_at.desc()).offset(offset).limit(limit)
    if filters:
        count_stmt = count_stmt.where(*filters)
        data_stmt = data_stmt.where(*filters)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(data_stmt)).scalars().all()
    items = [
        CandidateListItem(id=row.id, email=row.email, name=row.name, phone=row.phone, created_at=row.created_at)
        for row in rows
    ]
    return CandidateListResponse(version=settings.app_version, items=items, total=total, page=page, limit=limit)
