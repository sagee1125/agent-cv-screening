# Core collection logic: gather records.html + CVs for one refno via WebBridge or HTTP.
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jas_import import fetch as _jas_fetch
from jas_import.skill import job_payload_from_html
from screening_core.hr_output import safe_pack_id
from screening_core.input_policy import validate_reference

from webridge_collect.client import WebBridgeClient

COLLECT_ROOT_NAME = "jes_webridge"
MANIFEST_NAME = "_webridge-manifest.json"


# Build the records URL for a refno from a base URL or the default JAS host.
def build_records_url(refno: str, base_url: str | None) -> str:
    if base_url:
        return f"{base_url.rstrip('/')}/records.html?refno={refno.strip()}"
    return f"https://jobs.polyu.edu.hk/internal/records.php?refno={refno.strip()}"


# Return the scheme://host origin of a URL, used as the CV-link base.
def origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# Collect one job: write records.html + cvs/<appno>.pdf + a PII-free manifest.
def collect_job(
    *,
    records_url: str,
    folder: Path,
    driver: str = "http",
    base_url: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
    cookie_file: str | None = None,
    client: WebBridgeClient | None = None,
) -> dict[str, Any]:
    folder = Path(folder)
    (folder / "cvs").mkdir(parents=True, exist_ok=True)
    effective_base = base_url or origin_of(records_url)
    if driver == "http":
        html = asyncio.run(_jas_fetch.fetch_html(records_url, cookie_file=cookie_file, allowed_hosts=allowed_hosts))
    else:
        browser = client or WebBridgeClient()
        browser.navigate(records_url, new_tab=True, group_title="JES demo screening")
        html = browser.page_html()
    (folder / "records.html").write_text(html, encoding="utf-8")
    job = job_payload_from_html(html, base_url=effective_base)
    if not (job.get("refno") or "").strip():
        raise ValueError(f"URL did not look like a JAS records page: {records_url}")
    if not (job.get("jd_text") or "").strip():
        raise ValueError("JAS page did not contain a recognizable job advertisement table")

    failures: list[dict[str, Any]] = []
    cvs: dict[str, Path] = {}
    for candidate in job.get("candidates", []):
        appno = str(candidate.get("appno") or "").strip()
        cv_url = str(candidate.get("cv_url") or "").strip()
        if not appno or not cv_url:
            continue
        dest = folder / "cvs" / f"{safe_pack_id(appno, fallback='unknown')}.pdf"
        try:
            if driver == "http":
                validate_reference(cv_url, flag="candidate cv_url", allowed_hosts=allowed_hosts)
                asyncio.run(_jas_fetch.download_to(cv_url, dest, cookie_file=cookie_file, allowed_hosts=allowed_hosts))
            else:
                dest.write_bytes(browser.fetch_bytes(cv_url))
            cvs[appno] = dest
        except Exception as exc:  # one bad CV must not abort the whole job
            failures.append({"appno": appno, "error_message": str(exc)})

    known = {str(c.get("appno")) for c in job.get("candidates", [])}
    manifest = {
        "source": "webridge-collect",
        "driver": driver,
        "refno": job.get("refno", ""),
        "post_title": (job.get("job") or {}).get("post_title", ""),
        "candidates": [{"appno": c.get("appno"), "status": c.get("status")} for c in job.get("candidates", [])],
        "cv_downloaded": sorted(cvs),
        "candidates_without_cv": sorted(known - set(cvs)),
        "download_failures": failures,
    }
    (folder / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


__all__ = [
    "COLLECT_ROOT_NAME",
    "MANIFEST_NAME",
    "build_records_url",
    "collect_job",
    "origin_of",
]
