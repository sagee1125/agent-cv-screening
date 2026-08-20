# Verifies candidate matching database metadata, API contracts, and rank behavior.
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.main import app
from app.models.database import CandidateMatchScore, JobPost, MatchingRecalcJob
from app.models.matching_schemas import MatchingConfigUpdateRequest
from app.models.schemas import JobCandidateListResponse, JobCandidateSummaryItem
from app.services import matching_service
from app.services.matching_service import (
    _assign_dense_ranks,
    _expire_recalculation,
    _process_deferred_recalculation,
    _recalculation_is_stale,
    request_matching_recalculation,
)

JOB_POST_ID = UUID("00000000-0000-0000-0000-000000000099")


# Build one valid six-dimension configuration payload for contract tests.
def _config_payload() -> dict:
    return {
        "config": {
            "schema_version": "1.0.0",
            "algorithm_version": "candidate-matching-v1",
            "dimensions": {
                "core_skill_match": {"enabled": True, "weight": 0.30},
                "relevant_experience": {"enabled": True, "weight": 0.25},
                "role_seniority_fit": {"enabled": True, "weight": 0.15},
                "evidence_impact": {"enabled": True, "weight": 0.15},
                "education_certification": {"enabled": True, "weight": 0.05},
                "job_specific_match": {"enabled": True, "weight": 0.10},
            },
            "must_skills": [],
            "eligibility_rules": [],
            "job_specific_requirements": [],
            "fit_bands": {"high_min": 80, "medium_min": 60},
            "interview_question_policy": {"min_questions": 3, "max_questions": 6},
        }
    }


# Confirm the additive database metadata exposes every required matching field.
def test_matching_database_metadata_contains_required_tables_and_columns() -> None:
    assert {
        "matching_config_json",
        "matching_schema_version",
        "current_score_version",
        "matching_status",
        "last_scored_at",
        "last_matching_error_code",
    } <= set(JobPost.__table__.columns.keys())
    assert {
        "job_post_id",
        "target_score_version",
        "idempotency_key",
        "config_hash",
        "candidates_processed",
        "heartbeat_at",
    } <= set(MatchingRecalcJob.__table__.columns.keys())
    assert "idx_matching_recalc_jobs_status_heartbeat" in {
        index.name for index in MatchingRecalcJob.__table__.indexes
    }
    assert {
        "score_version",
        "dimension_results",
        "eligibility_results",
        "interview_questions",
        "config_snapshot",
        "input_snapshot",
        "is_published",
    } <= set(CandidateMatchScore.__table__.columns.keys())


# Confirm Pydantic accepts the fixed six-ID matching configuration contract.
def test_matching_config_request_accepts_fixed_contract() -> None:
    parsed = MatchingConfigUpdateRequest.model_validate(_config_payload())
    assert parsed.config.schema_version == "1.0.0"
    assert len(parsed.config.dimensions) == 6


# Confirm the public OpenAPI document includes every P0 matching endpoint.
def test_openapi_exposes_candidate_matching_endpoints() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/jobs/{job_id}/matching/config" in paths
    assert "/api/v1/jobs/{job_id}/matching/recalculate" in paths
    assert "/api/v1/jobs/{job_id}/matching/recalculations/{recalc_job_id}" in paths
    assert "/api/v1/jobs/{job_id}/matching/candidates/{candidate_id}" in paths
    assert "/api/v1/jobs/{job_id}/candidates" in paths


# Confirm dense ties ignore candidate ID while row order remains deterministic.
def test_dense_rank_uses_only_business_values() -> None:
    first_id = UUID("00000000-0000-0000-0000-000000000001")
    second_id = UUID("00000000-0000-0000-0000-000000000002")
    radar = [
        {"dimension_id": "core_skill_match", "score": 80.0},
        {"dimension_id": "relevant_experience", "score": 70.0},
    ]
    calculated = [
        (
            SimpleNamespace(candidate_id=second_id),
            {
                "eligibility": {"status": "passed"},
                "match_score": 75.0,
                "evidence_confidence": 90.0,
                "radar_dimensions": radar,
            },
        ),
        (
            SimpleNamespace(candidate_id=first_id),
            {
                "eligibility": {"status": "passed"},
                "match_score": 75.0,
                "evidence_confidence": 90.0,
                "radar_dimensions": radar,
            },
        ),
    ]
    _assign_dense_ranks(calculated)
    assert [item[0].candidate_id for item in calculated] == [first_id, second_id]
    assert [item[1]["recommendation_rank"] for item in calculated] == [1, 1]


# Confirm persistence ranking delegates ordering and ranks to the shared ranker.
def test_persistence_ranking_uses_shared_ranker(monkeypatch) -> None:
    first_id = UUID("00000000-0000-0000-0000-000000000001")
    second_id = UUID("00000000-0000-0000-0000-000000000002")
    calculated = [
        (SimpleNamespace(candidate_id=first_id), {"match_score": 90.0}),
        (SimpleNamespace(candidate_id=second_id), {"match_score": 80.0}),
    ]

    # Return a recognizable order to prove the persistence adapter delegates.
    def fake_rank_candidates(rows):
        return [
            {**rows[1], "recommendation_rank": 1},
            {**rows[0], "recommendation_rank": 2},
        ]

    monkeypatch.setattr(
        "app.services.matching_service.rank_candidates",
        fake_rank_candidates,
    )
    _assign_dense_ranks(calculated)

    assert [item[0].candidate_id for item in calculated] == [second_id, first_id]
    assert [item[1]["recommendation_rank"] for item in calculated] == [1, 2]


# Confirm heartbeat leases detect abandoned tasks and close their counters.
def test_recalculation_heartbeat_timeout_marks_remaining_candidates_failed(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    recalc = SimpleNamespace(
        status="running",
        candidates_total=10,
        candidates_processed=4,
        candidates_failed=0,
        heartbeat_at=now - timedelta(seconds=901),
        started_at=now - timedelta(seconds=902),
        created_at=now - timedelta(seconds=903),
        error_code=None,
        error_message=None,
        finished_at=None,
    )
    monkeypatch.setattr(
        "app.services.matching_service.settings.matching_recalc_timeout_seconds",
        900,
    )

    assert _recalculation_is_stale(recalc) is True
    _expire_recalculation(recalc)

    assert recalc.status == "failed"
    assert recalc.candidates_failed == 6
    assert recalc.error_code == "MATCHING_RECALC_TIMEOUT"
    assert recalc.heartbeat_at == recalc.finished_at


# Confirm an unscored candidate serializes a nullable score instead of false zero.
def test_candidate_list_contract_keeps_unscored_match_score_null() -> None:
    candidate_id = UUID("00000000-0000-0000-0000-000000000001")
    resume_id = UUID("00000000-0000-0000-0000-000000000002")
    response = JobCandidateListResponse(
        version="1.0.0",
        job_post_id=UUID("00000000-0000-0000-0000-000000000003"),
        score_version=0,
        scoring_status="unscored",
        stale=False,
        items=[
            JobCandidateSummaryItem(
                candidate_id=candidate_id,
                resume_id=resume_id,
                original_filename="cv.pdf",
                source_channel="manual_upload",
                cv_parse_status="success",
            )
        ],
        total=1,
        page=1,
        limit=20,
    )
    assert response.items[0].candidate_scoring_status == "unscored"
    assert response.items[0].match_score is None


# Reset debounce globals so upload-trigger tests do not leak asyncio tasks.
@pytest.fixture(autouse=True)
def reset_matching_debounce_state() -> None:
    matching_service._debounce_tasks.clear()
    matching_service._debounce_payload.clear()
    matching_service._deferred_recalc_jobs.clear()
    yield
    for task in list(matching_service._debounce_tasks.values()):
        if not task.done():
            task.cancel()
    matching_service._debounce_tasks.clear()
    matching_service._debounce_payload.clear()
    matching_service._deferred_recalc_jobs.clear()


# Confirm rapid upload requests coalesce into one debounced enqueue.
@pytest.mark.asyncio
async def test_request_matching_recalculation_coalesces_rapid_uploads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[tuple[UUID, str, str | None]] = []

    async def fake_enqueue(
        job_post_id: UUID,
        *,
        trigger: str,
        reason: str | None,
    ) -> None:
        enqueued.append((job_post_id, trigger, reason))

    async def instant_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        matching_service,
        "_enqueue_matching_recalculation",
        fake_enqueue,
    )
    monkeypatch.setattr(matching_service.asyncio, "sleep", instant_sleep)
    monkeypatch.setattr(matching_service.settings, "matching_enabled", True)
    monkeypatch.setattr(matching_service.settings, "matching_recalc_debounce_seconds", 5)

    request_matching_recalculation(
        JOB_POST_ID,
        trigger="cv_uploaded",
        reason="first.pdf",
    )
    request_matching_recalculation(
        JOB_POST_ID,
        trigger="cv_uploaded",
        reason="second.pdf",
    )
    request_matching_recalculation(
        JOB_POST_ID,
        trigger="cv_uploaded",
        reason="third.pdf",
    )

    await asyncio.gather(
        *matching_service._debounce_tasks.values(),
        return_exceptions=True,
    )

    assert len(enqueued) == 1
    assert enqueued[0][0] == JOB_POST_ID
    assert enqueued[0][1] == "cv_uploaded"
    assert enqueued[0][2] == "3 CV upload(s) parsed successfully"


# Confirm deferred upload work is rescheduled after an active recalculation finishes.
@pytest.mark.asyncio
async def test_process_deferred_recalculation_reschedules_upload_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[tuple[UUID, str, str | None]] = []

    def fake_request(
        job_post_id: UUID,
        *,
        trigger: str,
        reason: str | None = None,
    ) -> None:
        scheduled.append((job_post_id, trigger, reason))

    monkeypatch.setattr(
        matching_service,
        "request_matching_recalculation",
        fake_request,
    )
    matching_service._deferred_recalc_jobs.add(JOB_POST_ID)

    await _process_deferred_recalculation(JOB_POST_ID)

    assert scheduled == [
        (
            JOB_POST_ID,
            "cv_uploaded",
            "Deferred until the active recalculation completed",
        )
    ]
    assert JOB_POST_ID not in matching_service._deferred_recalc_jobs


# Confirm disabled matching skips backend upload scheduling.
def test_request_matching_recalculation_respects_feature_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(matching_service.settings, "matching_enabled", False)

    request_matching_recalculation(
        JOB_POST_ID,
        trigger="cv_uploaded",
        reason="ignored.pdf",
    )

    assert matching_service._debounce_tasks == {}
    assert matching_service._debounce_payload == {}
