# PolyU REST adapter: fetch uses the skill; parse-JD may apply backend hybrid/qwen.
from __future__ import annotations

from typing import Any

from polyu_import.skill import fetch_polyu_job_skill, list_polyu_catalog_skill
from app.skills.jd_parse import parse_jd_skill


# Fetch one PolyU job and parse JD via REST jd_parse (may use hybrid/qwen).
async def fetch_and_parse_polyu_job_skill(
    *,
    external_ref: str | None = None,
    detail_url: str | None = None,
    job_code: str | None = None,
    title: str = "",
    department: str = "",
    mode: str | None = None,
) -> dict[str, Any]:
    fetched = await fetch_polyu_job_skill(
        external_ref=external_ref,
        detail_url=detail_url,
        job_code=job_code,
        title=title,
        department=department,
    )
    parsed = await parse_jd_skill(fetched["jd_text"], mode=mode)
    structured = parsed.get("structured_data")
    if parsed.get("status") != "success" or not isinstance(structured, dict):
        detail = parsed.get("error_message") or parsed.get("status") or "invalid parse result"
        raise ValueError(f"JD parse failed: {detail}")
    return {
        "status": "success",
        "source": fetched.get("source"),
        "external_ref": fetched["external_ref"],
        "title": fetched["title"],
        "jd_text": fetched["jd_text"],
        "structured_data": structured,
        "jd_parse": parsed,
    }


__all__ = [
    "fetch_and_parse_polyu_job_skill",
    "fetch_polyu_job_skill",
    "list_polyu_catalog_skill",
]
