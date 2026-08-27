# Skill entry: generate candidate PDF one-pagers and Excel comparisons.
from __future__ import annotations

from datetime import datetime
from typing import Any

from report_gen.reporter import ReporterService
from screening_core.candidate_id import format_candidate_label


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


# Generate a one-page PDF report from an extracted profile, its score, and optional matching detail.
def generate_candidate_report_skill(
    *,
    extracted_data: dict[str, Any],
    score_result: dict[str, Any] | None = None,
    position_name: str,
    candidate_name: str | None = None,
    refno: str | None = None,
    appno: str | None = None,
    rank: int = 0,
    output_path: str,
    version: str = "skill",
    detail_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail = detail_result or {}
    if not isinstance(detail, dict):
        raise ValueError("invalid detail input: expected a JSON object")
    if isinstance(extracted_data.get("structured_data"), dict):
        extracted_data = extracted_data["structured_data"]

    if score_result is not None:
        score_result = _unwrap_score_result(score_result)
        if not _is_valid_score_result(score_result):
            raise ValueError(
                "invalid score input: missing total_score or full_snapshot.dimension_scores"
            )
    else:
        score_result = {}
    if detail and "match_score" not in detail and "radar_dimensions" not in detail:
        raise ValueError(
            "invalid detail input: expected matching detail with match_score or radar_dimensions"
        )

    snapshot = score_result.get("full_snapshot") or {}
    skill_details = score_result.get("skill_match_details") or snapshot.get("skill_match_details") or {}
    dimension_scores = score_result.get("dimension_scores") or snapshot.get("dimension_scores") or {}
    suggestions = score_result.get("interview_suggestions") or snapshot.get("interview_suggestions") or []
    total_score = detail.get("match_score") if "match_score" in detail else score_result.get("total_score", 0)
    tier = detail.get("fit_band") if "fit_band" in detail else score_result.get("tier", "")
    _ = candidate_name  # names are never shown on reports
    label = format_candidate_label(refno, appno)
    service = ReporterService()
    service.generate_candidate_one_pager_pdf(
        output_path,
        display_label=label,
        position_name=position_name,
        report_date=datetime.utcnow(),
        total_score=float(total_score),
        tier=str(tier or ""),
        rank=rank,
        education=extracted_data.get("education", []),
        experience=extracted_data.get("experience", []),
        skill_hit=skill_details.get("hit", []),
        skill_miss=skill_details.get("miss", []),
        hit_rate=float(dimension_scores.get("skill_match", 0)),
        dimension_scores={k: float(v) for k, v in dimension_scores.items()},
        interview_suggestions=suggestions,
        version=version,
        radar_dimensions=detail.get("radar_dimensions"),
        interview_questions=detail.get("interview_questions"),
        eligibility=detail.get("eligibility"),
        evidence_confidence=detail.get("evidence_confidence"),
        fit_band=detail.get("fit_band"),
        top_strengths=detail.get("top_strengths"),
        key_gaps=detail.get("key_gaps"),
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


# Generate a local HTML board (ranking + radar) for HR to open in a browser.
def generate_screening_board_skill(
    *,
    position_name: str,
    rows: list[dict[str, Any]],
    output_path: str,
    refno: str | None = None,
) -> dict[str, Any]:
    service = ReporterService()
    service.generate_screening_board_html(
        output_path,
        position_name=position_name,
        rows=rows,
        report_date=datetime.utcnow(),
        refno=refno,
    )
    return {"status": "success", "format": "html", "output_path": output_path}


# Generate one candidate HTML match page (typically named <appno>.html).
def generate_candidate_match_html_skill(
    *,
    position_name: str,
    row: dict[str, Any],
    output_path: str,
) -> dict[str, Any]:
    service = ReporterService()
    service.generate_candidate_match_html(
        output_path,
        row=row,
        position_name=position_name,
        report_date=datetime.utcnow(),
    )
    return {"status": "success", "format": "html", "output_path": output_path}