# Core collection logic: gather records.html + CVs for one refno via WebBridge or HTTP.
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jas_import import fetch as _jas_fetch
from jas_import.errors import JobNotFoundError
from jas_import.skill import job_payload_from_html
from screening_core.candidate_id import refno_from_url
from screening_core.hr_output import safe_pack_id
from screening_core.input_policy import validate_reference

from webridge_collect.client import WebBridgeClient

COLLECT_ROOT_NAME = "jes_webridge"
MANIFEST_NAME = "_webridge-manifest.json"

# JS run in the browser: drive a visible ghost cursor to type the refno into the filter and press the row's View link.
GHOST_CURSOR_JS = """(async () => {
  const refno = %r;
  const sleep = (ms) => new Promise(res => setTimeout(res, ms));
  let cursor = document.getElementById('jes-ghost-cursor');
  if (!cursor) {
    cursor = document.createElement('div');
    cursor.id = 'jes-ghost-cursor';
    cursor.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;width:34px;height:34px;transition:left .4s ease, top .4s ease;';
    cursor.innerHTML = '<svg width="34" height="34" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M4 2 L4 17 L8.5 12.5 L12 20 L15 18.5 L11.5 11 L16 11 Z" fill="white" stroke="#1f2937" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cursor);
  }
  const move = async (el) => {
    const rect = el.getBoundingClientRect();
    cursor.style.left = (rect.left + rect.width / 2 - 3) + 'px';
    cursor.style.top = (rect.top + rect.height / 2 - 3) + 'px';
    await sleep(450);
  };
  // Type the reference number into the first (Ref no.) column search box, like a human.
  const inputs = Array.from(document.querySelectorAll('thead input[aria-label="Search column"], thead input[placeholder*="Filter" i]'));
  let typed = false;
  if (inputs.length) {
    const filter = inputs[0];
    await move(filter);
    filter.focus();
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    for (let i = 0; i <= refno.length; i++) {
      setter.call(filter, refno.slice(0, i));
      filter.dispatchEvent(new Event('input', {bubbles: true}));
      filter.dispatchEvent(new Event('keyup', {bubbles: true}));
      await sleep(70);
    }
    await sleep(250);
    typed = true;
  }
  // Find the job row and press its View link (visual press only; the script opens the link itself).
  const row = Array.from(document.querySelectorAll('table tbody tr')).find(r => r.innerText.includes(refno));
  if (!row) return {typed: typed, clicked: false, reason: 'row-not-found'};
  const link = Array.from(row.querySelectorAll('a')).find(a => /view/i.test(a.innerText || '')) || row.querySelector('a');
  if (!link) return {typed: typed, clicked: false, reason: 'link-not-found'};
  await move(link);
  link.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
  await sleep(150);
  link.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
  await sleep(200);
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


# Bring the current browser tab to the foreground so HR watches the human flow.
def _focus_current_tab(browser: WebBridgeClient) -> None:
    try:
        if hasattr(browser, "cdp"):
            browser.cdp("Page.bringToFront")
    except Exception:
        pass


# Search the list page like a human: return the row's View link when found, None when no row matches (page stays open).
def navigate_like_human(browser: WebBridgeClient, *, refno: str, base_url: str, records_url: str) -> str | None:
    list_url = f"{base_url.rstrip('/')}/"
    browser.navigate(list_url, new_tab=True, group_title="JES demo screening")
    _focus_current_tab(browser)
    try:
        found = browser.evaluate(GHOST_CURSOR_JS % refno)
    except Exception:
        found = None
    if isinstance(found, dict) and found.get("clicked") and found.get("href"):
        return str(found["href"])
    # The refno was typed into the filter but no matching row appeared: report not found
    # without navigating away, so HR sees the empty search result and the tab stays open.
    if isinstance(found, dict) and found.get("typed") and not found.get("clicked"):
        return None
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
            if target is None:
                # The list-page search found no matching row; keep the page open and report not found.
                raise JobNotFoundError(f"no JAS job found for refno {refno} (no matching row in the records list)")
            browser.navigate(target, new_tab=False, group_title="JES demo screening")
            _focus_current_tab(browser)
        else:
            browser.navigate(records_url, new_tab=True, group_title="JES demo screening")
            _focus_current_tab(browser)
        html = browser.page_html()
    (folder / "records.html").write_text(html, encoding="utf-8")
    job = job_payload_from_html(html, base_url=effective_base)
    refno_label = refno or refno_from_url(records_url) or "the requested job"
    if not (job.get("refno") or "").strip():
        raise JobNotFoundError(f"no JAS job found for {refno_label} (page had no job reference)")
    if refno and str(job.get("refno") or "").strip() != refno:
        raise JobNotFoundError(
            f"no JAS job found for refno {refno} (records page returned job {job.get('refno')!r})"
        )
    if not (job.get("jd_text") or "").strip():
        raise JobNotFoundError(f"no JAS job found for {refno_label} (page had no job advertisement)")

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
