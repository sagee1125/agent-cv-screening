# Skill entry: fetch PolyU job listings and optional rule-only JD parse.
from __future__ import annotations

from typing import Any

from polyu_import.jobs import (
    POLYU_SOURCE,
    PolyUListing,
    build_job_description,
    fetch_polyu_detail,
    fetch_polyu_listings,
    job_code_from_href,
)


# Convert a PolyU listing into a JSON-serializable catalog item dict.
def _listing_to_item(listing: PolyUListing) -> dict[str, Any]:
    return {
        "job_code": listing.job_code,
        "external_ref": listing.external_ref,
        "title": listing.title,
        "department": listing.department,
        "closing_date": listing.closing_date.isoformat() if listing.closing_date else None,
        "detail_url": listing.detail_url,
    }


# Fetch PolyU job listings and return a JSON-serializable catalog.
async def list_polyu_catalog_skill() -> dict[str, Any]:
    listings = await fetch_polyu_listings()
    return {
        "status": "success",
        "source": POLYU_SOURCE,
        "total": len(listings),
        "items": [_listing_to_item(item) for item in listings],
    }


# Locate a listing by external_ref, or synthesize a minimal one from detail_url/job_code.
def _resolve_listing(
    listings: list[PolyUListing],
    *,
    external_ref: str | None,
    detail_url: str | None,
    job_code: str | None,
    title: str,
    department: str,
) -> PolyUListing:
    if external_ref:
        for item in listings:
            if item.external_ref == external_ref.strip():
                return item
        if not detail_url:
            raise ValueError("external_ref not found in catalog; provide --detail-url as fallback")
    if detail_url:
        return PolyUListing(
            job_code=job_code or job_code_from_href(detail_url),
            external_ref=(external_ref or "").strip(),
            title=title.strip(),
            department=department.strip(),
            closing_date=None,
            detail_url=detail_url.strip(),
        )
    raise ValueError("missing input: provide external_ref or detail_url")


# Fetch one PolyU job detail page and return JD text plus metadata.
async def fetch_polyu_job_skill(
    *,
    external_ref: str | None = None,
    detail_url: str | None = None,
    job_code: str | None = None,
    title: str = "",
    department: str = "",
) -> dict[str, Any]:
    listings = await fetch_polyu_listings() if external_ref else []
    listing = _resolve_listing(
        listings,
        external_ref=external_ref,
        detail_url=detail_url,
        job_code=job_code,
        title=title,
        department=department,
    )
    detail_text, posting_date = await fetch_polyu_detail(listing)
    return {
        "status": "success",
        "source": POLYU_SOURCE,
        "external_ref": listing.external_ref,
        "title": listing.title,
        "department": listing.department,
        "detail_url": listing.detail_url,
        "posting_date": posting_date.isoformat() if posting_date else None,
        "jd_text": build_job_description(listing, detail_text),
    }


# Fetch one PolyU job, parse its JD, and fail fast when parsing fails.
async def fetch_and_parse_polyu_job_skill(
    *,
    external_ref: str | None = None,
    detail_url: str | None = None,
    job_code: str | None = None,
    title: str = "",
    department: str = "",
    mode: str | None = None,
) -> dict[str, Any]:
    from jd_parser.skill import parse_jd

    _ = mode  # Skill path is rule-only; REST hybrid/qwen stay in backend.

    fetched = await fetch_polyu_job_skill(
        external_ref=external_ref,
        detail_url=detail_url,
        job_code=job_code,
        title=title,
        department=department,
    )
    parsed = await parse_jd(fetched["jd_text"], mode="rule")
    structured = parsed.get("structured_data")
    if parsed.get("status") != "success" or not isinstance(structured, dict):
        detail = parsed.get("error_message") or parsed.get("status") or "invalid parse result"
        raise ValueError(f"JD parse failed: {detail}")
    return {
        "status": "success",
        "source": POLYU_SOURCE,
        "external_ref": fetched["external_ref"],
        "title": fetched["title"],
        "jd_text": fetched["jd_text"],
        "structured_data": structured,
        "jd_parse": parsed,
    }
