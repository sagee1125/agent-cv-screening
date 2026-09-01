# Core collection logic: gather records.html + CVs for one refno via WebBridge or HTTP.
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jas_import import fetch as _jas_fetch
from jas_import.skill import job_payload_from_html
from screening_core.candidate_id import refno_from_url
from screening_core.hr_output import safe_pack_id
from screening_core.input_policy import validate_reference

from webridge_collect.client import WebBridgeClient

COLLECT_ROOT_NAME = "jes_webridge"
MANIFEST_NAME = "_webridge-manifest.json"

# JS run in the browser: type the refno into the Ref no. column filter, then locate and read the job row's View link.
HUMAN_LIST_JS = """(() => {
  const refno = %r;
  // Type the reference number into the first (Ref no.) column search box, like a human.
  const inputs = Array.from(document.querySelectorAll('thead input[aria-label="Search column"], thead input[placeholder*="Filter" i]'));
  let typed = false;
  if (inputs.length) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(inputs[0], refno);
    for (const evt of ['input', 'keyup', 'change']) inputs[0].dispatchEvent(new Event(evt, {bubbles: true}));
    typed = true;
  }
  // Find the row that carries this reference number and return its View link.
  const row = Array.from(document.querySelectorAll('table tbody tr')).find(r => r.innerText.includes(refno));
  if (!row) return {typed: typed, clicked: false, reason: 'row-not-found'};
  const link = Array.from(row.querySelectorAll('a')).find(a => /view/i.test(a.innerText || '')) || row.querySelector('a');
  if (!link) return {typed: typed, clicked: false, reason: 'link-not-found'};
  return {typed: typed, clicked: true, href: link.href || '', text: (link.innerText || '').trim()};
})()"""


# Build the records URL for a refno from a base URL or the default JAS host.
def build_records_url(refno: str, base_url: str | None) -> str:
    if base_url:
        return f"{base_url.rstrip('/')}/records.html?refno={refno.strip()}"
    return f"https://jobs.polyu.edu.hk/internal/records.php?refno={refno.strip()}"


# Return the scheme://host origin of a URL, used as the CV-link base.
def origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# Open the records page like a human: land on the job list page, type the refno into the filter, then return the row's View link.
def navigate_like_human(browser: WebBridgeClient, *, refno: str, base_url: str, records_url: str) -> str:
    list_url = f"{base_url.rstrip('/')}/"
    browser.navigate(list_url, new_tab=True, group_title="JES demo screening")
    try:
        found = browser.evaluate(HUMAN_LIST_JS % refno)
    except Exception:
        found = None
    if isinstance(found, dict) and found.get("clicked") and found.get("href"):
        return str(found["href"])
    return records_url


# Collect one job: write records.html + cvs/<appno>.pdf + a PII-free manifest.
def collect_job(
    *,
    records_url: str,
    folder: Path,
    driver: str = "http",
    base_url: str | None = None,
    refno: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
    cookie_file: str | None = None,
    client: WebBridgeClient | None = None,
) -> dict[str, Any]:
    folder = Path(folder)
    (folder / "cvs").mkdir(parents=True, exist_ok=True)
    effective_base = base_url or origin_of(records_url)
    if not refno:
        refno = refno_from_url(records_url)
    if driver == "http":
        html = asyncio.run(_jas_fetch.fetch_html(records_url, cookie_file=cookie_file, allowed_hosts=allowed_hosts))
    else:
        browser = client or WebBridgeClient()
        if base_url and refno:
            # Human-like flow: find the job on the list page, then open its View link.
            target = navigate_like_human(browser, refno=refno, base_url=base_url, records_url=records_url)
            browser.navigate(target, new_tab=False, group_title="JES demo screening")
        else:
            browser.navigate(records_url, new_tab=True, group_title="JES demo screening")
        html = browser.page_html()
    (folder / "records.html").write_text(html, encoding="utf-8")
    job = job_payload_from_html(html, base_url=effective_base)
    if not (job.get("refno") or "").strip():
        raise ValueError(f"URL did not look like a JAS records page: {records_url}")
    if refno and str(job.get("refno") or "").strip() != refno:
        raise ValueError(f"records page returned job {job.get('refno')!r}, expected {refno!r}; refusing to collect the wrong job")
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
    "navigate_like_human",
    "origin_of",
]
