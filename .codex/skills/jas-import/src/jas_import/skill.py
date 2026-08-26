# High-level JAS import skill functions that read local HTML files.
from __future__ import annotations

from pathlib import Path
from typing import Any

JAS_SCHEMA_VERSION = "1.0.0"


from jas_import.records import (
    JAS_SOURCE,
    JASCandidate,
    JASJobRow,
    build_jd_text,
    parse_job_html,
    parse_list_html,
)


# Read HTML text from a local file path.
def _read_html(html_file: str | Path) -> str:
    path = Path(html_file)
    if not path.is_file():
        raise FileNotFoundError(f"JAS HTML file not found: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


# Convert one JAS list row into a JSON-serializable catalog item.
def _row_to_item(row: JASJobRow) -> dict[str, Any]:
    return {
        "refno": row.refno,
        "job_group": row.job_group,
        "unit": row.unit,
        "post_title": row.post_title,
        "posting_date": row.posting_date,
        "closing_date": row.closing_date,
        "off_shelf_date": row.off_shelf_date,
        "list_type": row.list_type,
        "application_count": row.application_count,
        "records_url": row.records_url,
    }


# Parse a JAS records list HTML file into a catalog payload.
def parse_list_skill(html_file: str | Path, *, base_url: str | None = None) -> dict[str, Any]:
    html = _read_html(html_file)
    items = parse_list_html(html, base_url=base_url)
    return {
        "schema_version": JAS_SCHEMA_VERSION,
        "status": "success",
        "source": JAS_SOURCE,
        "total": len(items),
        "items": [_row_to_item(item) for item in items],
    }


# Convert one JAS candidate row into a minimal non-PII dict.
def _candidate_to_item(candidate: JASCandidate) -> dict[str, Any]:
    return {
        "appno": candidate.appno,
        "status": candidate.status,
        "cv_url": candidate.cv_url,
        "supp_url": candidate.supp_url,
        "record_detail_url": candidate.record_detail_url,
    }


# Builds the shared job payload (JD text + candidates) from JAS job-detail HTML.
def job_payload_from_html(html: str, *, base_url: str | None = None) -> dict[str, Any]:
    detail = parse_job_html(html, base_url=base_url)
    return {
        "schema_version": JAS_SCHEMA_VERSION,
        "status": "success",
        "source": JAS_SOURCE,
        "refno": detail.refno,
        "job": {
            "refno": detail.refno,
            "job_group": detail.job_group,
            "unit": detail.unit,
            "post_title": detail.post_title,
            "appointment_period": detail.appointment_period,
            "project_title": detail.project_title,
            "posting_date": detail.posting_date,
            "list_type": detail.list_type,
        },
        "jd_text": build_jd_text(detail),
        "candidates": [_candidate_to_item(candidate) for candidate in detail.candidates],
    }


# Parse a JAS job-detail HTML file into JD text plus candidate references.
def parse_job_skill(html_file: str | Path, *, base_url: str | None = None) -> dict[str, Any]:
    html = _read_html(html_file)
    return job_payload_from_html(html, base_url=base_url)


__all__ = ["JAS_SCHEMA_VERSION", "job_payload_from_html", "parse_job_skill", "parse_list_skill"]