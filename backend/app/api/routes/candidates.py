# TODO(agent-migration): This legacy REST router exists for the traditional frontend.
# It invokes the shared skill layer (app.skills.cv_parse) for CV parsing, then persists
# results to the DB. When the API is deprecated, delete this router; the integrated agent
# calls .codex/skills/cv-parser/scripts/run_cv_parse.py directly instead.
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_cv_parser_service, get_db_session
from app.config import settings
from app.models.database import Candidate, ExtractedData, JobPost, Resume
from app.models.schemas import (
    CandidateDetailResponse,
    CandidateListItem,
    CandidateListResponse,
    CandidateUploadResponse,
)
from app.skills.cv_parse import parse_cv_skill
from app.services.cv_parser import CVParserService

router = APIRouter(prefix="/candidates")
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=CandidateUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_candidate_cv(
    file: UploadFile = File(...),
    job_id: UUID = Form(...),
    email: str | None = Form(default=None),
    name: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db_session),
    parser: CVParserService = Depends(get_cv_parser_service),
) -> CandidateUploadResponse:
    # Persist the uploaded PDF, parse it, and link the resulting resume to the given job.
    extracted: ExtractedData | None = None
    try:
        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(file.filename or "").suffix.lower()
        if ext != ".pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")

        logger.info(f"Uploading candidate CV: {file.filename}")
        content = await file.read()
        initial_hash = hashlib.md5(content).hexdigest()

        stored_name = f"{uuid4().hex}{ext}"
        saved_path = upload_dir / stored_name
        await asyncio.to_thread(saved_path.write_bytes, content)

        logger.info(f"Parsing candidate CV: {saved_path}")
        structured: dict = {}
        parse_status = "pending"
        parse_error_message: str | None = None
        parse_result: dict | None = None
        try:
            parse_result = await parse_cv_skill(str(saved_path), parser=parser)
            structured = parse_result["structured_data"]
            parse_status = parse_result.get("status", "success")
            parse_error_message = parse_result.get("error_message")
        except Exception as parse_exc:
            logger.exception("CV parsing failed; persisting failed extracted status.")
            parse_status = "failed"
            parse_error_message = str(parse_exc)

        parse_ok = parse_status != "failed"
        final_hash = parse_result["file_hash"] if parse_ok and parse_result else initial_hash
        raw_llm = parse_result.get("raw_llm_response") if parse_ok and parse_result else None
        extraction_model = (
            parse_result.get("extraction_model", settings.llm_model)
            if parse_ok and parse_result
            else settings.llm_model
        )
        final_structured = structured if parse_ok else {}

        # Resolve the parsed email/name/phone, falling back to form values, to identify the candidate.
        parsed_email = (
            email
            or (str(structured.get("email")).strip() if isinstance(structured, dict) and structured.get("email") else None)
            or f"unknown-{uuid4().hex[:8]}@example.com"
        )
        parsed_name = (
            name
            or (str(structured.get("name")).strip() if isinstance(structured, dict) and structured.get("name") else None)
            or "Unknown Candidate"
        )
        parsed_phone = phone or (
            str(structured.get("phone")).strip() if isinstance(structured, dict) and structured.get("phone") else None
        )

        # Upsert the candidate by email so the same person's CVs converge to one record.
        candidate_stmt = select(Candidate).where(Candidate.email == parsed_email)
        candidate = (await db.execute(candidate_stmt)).scalar_one_or_none()
        if candidate is None:
            candidate = Candidate(email=parsed_email, name=parsed_name, phone=parsed_phone)
            db.add(candidate)
            await db.flush()
        else:
            if name and structured.get("name"):
                candidate.name = parsed_name
            if parsed_phone:
                candidate.phone = parsed_phone

        def _build_extracted(resume_id: UUID) -> ExtractedData:
            # Create a fresh ExtractedData row for a resume with the current parse outcome.
            return ExtractedData(
                resume_id=resume_id,
                structured_data=final_structured,
                raw_llm_response=raw_llm,
                extraction_model=extraction_model,
                extraction_seed=42,
                status=parse_status,
                error_message=parse_error_message,
            )

        def _sync_extracted(existing: ExtractedData) -> None:
            # Overwrite an existing ExtractedData row with the latest parse outcome.
            existing.structured_data = final_structured
            existing.raw_llm_response = raw_llm
            existing.extraction_model = extraction_model
            existing.status = parse_status
            existing.error_message = parse_error_message

        # Override the existing (candidate, job) resume in place, inheriting its UUID.
        job_stmt = select(JobPost).where(JobPost.id == job_id, JobPost.deleted_at.is_(None))
        job = (await db.execute(job_stmt)).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")

        existing_for_job_stmt = (
            select(Resume)
            .where(Resume.candidate_id == candidate.id, Resume.job_post_id == job_id)
            .options(selectinload(Resume.extracted_data))
        )
        resume = (await db.execute(existing_for_job_stmt)).scalar_one_or_none()
        if resume is not None:
            resume.original_filename = file.filename or "uploaded.pdf"
            resume.file_path = str(saved_path)
            resume.file_hash = final_hash
            resume.source_channel = "manual_upload"
            if resume.extracted_data is None:
                extracted = _build_extracted(resume.id)
                db.add(extracted)
            else:
                extracted = resume.extracted_data
                _sync_extracted(extracted)
        else:
            resume = Resume(
                candidate_id=candidate.id,
                job_post_id=job_id,
                original_filename=file.filename or "uploaded.pdf",
                file_path=str(saved_path),
                file_hash=final_hash,
                source_channel="manual_upload",
            )
            db.add(resume)
            await db.flush()
            extracted = _build_extracted(resume.id)
            db.add(extracted)

        await db.commit()

        response_status = "processing" if parse_status == "success" else parse_status
        return CandidateUploadResponse(
            version=settings.app_version,
            id=candidate.id,
            status=response_status,
            extracted_id=extracted.id if extracted is not None else uuid4(),
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
