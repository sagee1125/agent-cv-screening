"""Skill entry point for the Reporter service (PDF one-pager / Excel comparison generation)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.reporter import ReporterService


# Unwrap a ranked score envelope ({score: {...}, ranking: [...]}) or pass through a plain score result.
def _unwrap_score_result(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid score input: expected a JSON object")
    inner = raw.get("score")
    if isinstance(inner, dict):
        return inner
    if any(key in raw for key in ("total_score", "dimension_scores", "full_snapshot")):
        return raw
    raise ValueError(
        "invalid score input: expected scorer output with total_score/dimension_scores or a {score: {...}} envelope"
    )


# Check that an unwrapped score result carries the fields needed for a one-pager.
def _is_valid_score_result(score_result: dict[str, Any]) -> bool:
    if "total_score" in score_result:
        return True
    snapshot = score_result.get("full_snapshot")
    return isinstance(snapshot, dict) and "dimension_scores" in snapshot


# Generate a one-page PDF report from an extracted profile plus its score result.
def generate_candidate_report_skill(
    *,
    extracted_data: dict[str, Any],
    score_result: dict[str, Any],
    position_name: str,
    candidate_name: str | None = None,
    rank: int = 0,
    output_path: str,
    version: str = "skill",
) -> dict[str, Any]:
    score_result = _unwrap_score_result(score_result)
    if not _is_valid_score_result(score_result):
        raise ValueError("invalid score input: missing total_score or full_snapshot.dimension_scores")
    if isinstance(extracted_data.get("structured_data"), dict):
        extracted_data = extracted_data["structured_data"]
    snapshot = score_result.get("full_snapshot") or {}
    skill_details = score_result.get("skill_match_details") or snapshot.get("skill_match_details") or {}
    dimension_scores = score_result.get("dimension_scores") or snapshot.get("dimension_scores") or {}
    suggestions = score_result.get("interview_suggestions") or snapshot.get("interview_suggestions") or []
    name = candidate_name or extracted_data.get("name") or "Unknown"
    service = ReporterService()
    service.generate_candidate_one_pager_pdf(
        output_path,
        candidate_name=name,
        position_name=position_name,
        report_date=datetime.utcnow(),
        total_score=float(score_result.get("total_score", 0)),
        tier=score_result.get("tier", ""),
        rank=rank,
        education=extracted_data.get("education", []),
        experience=extracted_data.get("experience", []),
        skill_hit=skill_details.get("hit", []),
        skill_miss=skill_details.get("miss", []),
        hit_rate=float(dimension_scores.get("skill_match", 0)),
        dimension_scores={k: float(v) for k, v in dimension_scores.items()},
        interview_suggestions=suggestions,
        version=version,
    )
    return {"status": "success", "format": "pdf", "output_path": output_path}


# Generate an Excel comparison report from ranked candidate rows.
def generate_comparison_report_skill(
    *,
    position_name: str,
    rows: list[dict[str, Any]],
    output_path: str,
) -> dict[str, Any]:
    service = ReporterService()
    service.generate_comparison_excel(
        output_path,
        position_name=position_name,
        report_date=datetime.utcnow(),
        rows=rows,
    )
    return {"status": "success", "format": "excel", "output_path": output_path}
