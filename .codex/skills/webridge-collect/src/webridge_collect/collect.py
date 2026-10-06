# Core collection logic: gather records.html + CVs for one refno via WebBridge or HTTP.
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jas_import import fetch as _jas_fetch
from jas_import.errors import JobNotFoundError
from jas_import.skill import job_payload_from_html
from screening_core.candidate_id import records_url_for_refno, refno_from_url
from screening_core.hr_output import safe_pack_id
from screening_core.input_policy import validate_reference
from screening_core.posts import post_counts
from screening_core.site_mode import site_profile

from webridge_collect.client import WebBridgeClient
from webridge_collect.login import ensure_signed_in

COLLECT_ROOT_NAME = "jes_webridge"
MANIFEST_NAME = "_webridge-manifest.json"

# How many list pages the human flow will open looking for one refno.
# Past this, the search stops and reports the job as not found.
MAX_LIST_PAGES = 40

# JS run in the browser: type the refno into the filter, then turn list pages until the row's View link shows.
# Placeholders are filled by list_search_js. typeFilter is false after a page reload, which starts blank.
LIST_SEARCH_JS = r"""(async () => {
  const refno = __REFNO__;
  const typeFilter = __TYPE_FILTER__;
  const MAX_PAGES = 40;
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
    try { el.scrollIntoView({block: 'center', inline: 'nearest'}); } catch (e) {}
    const rect = el.getBoundingClientRect();
    cursor.style.left = (rect.left + rect.width / 2 - 3) + 'px';
    cursor.style.top = (rect.top + rect.height / 2 - 3) + 'px';
    await sleep(450);
  };
  const isShown = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };
  const isDisabled = (el) => {
    if (!el) return true;
    if (el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true' || el.classList.contains('disabled')) return true;
    const parent = el.parentElement;
    return !!(parent && (parent.classList.contains('disabled') || parent.getAttribute('aria-disabled') === 'true'));
  };
  const isActive = (el) => {
    if (!el) return false;
    if (el.classList.contains('active') || el.getAttribute('aria-current') === 'page' || el.getAttribute('aria-current') === 'true') return true;
    const parent = el.parentElement;
    return !!(parent && (parent.classList.contains('active') || parent.getAttribute('aria-current') === 'page'));
  };
  const pageNumber = (el) => {
    const raw = el.getAttribute('data-n');
    if (raw && /^\d+$/.test(raw)) return Number(raw);
    const text = (el.innerText || '').trim();
    return /^\d+$/.test(text) ? Number(text) : null;
  };
  const destination = (el) => {
    const raw = (el.getAttribute('href') || '').trim();
    if (!raw || raw === '#' || raw.charAt(0) === '#' || /^javascript:/i.test(raw)) return '';
    try { return new URL(raw, location.href).href; } catch (e) { return ''; }
  };
  const sameDocument = (url) => {
    try {
      const next = new URL(url);
      return next.origin === location.origin && next.pathname === location.pathname && next.search === location.search;
    } catch (e) { return false; }
  };
  const findRow = () => Array.from(document.querySelectorAll('table tbody tr')).find(
    (row) => isShown(row) && (row.innerText || '').indexOf(refno) !== -1
  );
  const pagerControls = () => {
    const scoped = Array.from(document.querySelectorAll(
      'tfoot a, tfoot button, .pag a, .pag button, .pagination a, .pagination button, .pager a, .pager button, a[rel="next"], button[rel="next"]'
    ));
    const named = Array.from(document.querySelectorAll('a, button')).filter((el) => {
      if (el.closest('thead') || el.closest('tbody')) return false;
      const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
      const aria = (el.getAttribute('aria-label') || '').toLowerCase();
      return el.getAttribute('rel') === 'next' || aria === 'next' || aria.indexOf('next page') !== -1
        || /^(next|›|»|>|下一頁|下頁|下一页)$/i.test(text);
    });
    const seen = new Set();
    const out = [];
    scoped.concat(named).forEach((el) => {
      if (seen.has(el)) return;
      seen.add(el);
      out.push(el);
    });
    return out;
  };
  const findNext = (step) => {
    const controls = pagerControls().filter((el) => isShown(el) && !isDisabled(el));
    const named = controls.find((el) => {
      const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
      const aria = (el.getAttribute('aria-label') || '').toLowerCase();
      return el.getAttribute('rel') === 'next' || aria === 'next' || aria.indexOf('next page') !== -1
        || /^(next|›|»|>|下一頁|下頁|下一页)$/i.test(text);
    });
    if (named) return named;
    const nums = controls.filter((el) => pageNumber(el) !== null);
    const active = nums.find(isActive);
    if (active) return nums.find((el) => pageNumber(el) === pageNumber(active) + 1) || null;
    if (step === 0) return nums.find((el) => pageNumber(el) === 2) || null;
    return null;
  };
  const pageMark = () => {
    const active = document.querySelector('tfoot .active, .pag .active, .pagination .active, .pager .active, [aria-current="page"]');
    const shown = Array.from(document.querySelectorAll('table tbody tr')).filter(isShown).slice(0, 3)
      .map((row) => (row.innerText || '').slice(0, 40)).join('|');
    return (active ? (active.getAttribute('data-n') || active.innerText || '') : '') + '|' + shown;
  };
  let typed = false;
  if (typeFilter) {
    const inputs = Array.from(document.querySelectorAll('thead input[aria-label="Search column"], thead input[placeholder*="Filter" i]'));
    if (inputs.length) {
      const filter = inputs[0];
      await move(filter);
      filter.focus();
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      for (let i = 0; i <= refno.length; i++) {
        setter.call(filter, refno.slice(0, i));
        filter.dispatchEvent(new Event('input', {bubbles: true}));
        filter.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
        if (window.jQuery) { try { window.jQuery(filter).trigger('keyup'); } catch (e) {} }
        await sleep(70);
      }
      await sleep(250);
      typed = true;
    }
  }
  let pagesTurned = 0;
  let guard = pageMark();
  for (let step = 0; step < MAX_PAGES; step++) {
    const row = findRow();
    if (row) {
      const link = Array.from(row.querySelectorAll('a')).find((a) => /view/i.test(a.innerText || '')) || row.querySelector('a');
      if (!link) return {typed: typed, clicked: false, reason: 'link-not-found', pages_turned: pagesTurned};
      await move(link);
      link.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
      await sleep(150);
      link.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
      await sleep(200);
      return {typed: typed, clicked: true, href: link.href || '', text: (link.innerText || '').trim(), pages_turned: pagesTurned};
    }
    const next = findNext(step);
    if (!next) return {typed: typed, clicked: false, reason: 'row-not-found', pages_turned: pagesTurned};
    const dest = destination(next);
    if (dest && !sameDocument(dest)) {
      await move(next);
      return {typed: typed, clicked: false, reason: 'next-page', href: dest, pages_turned: pagesTurned};
    }
    await move(next);
    next.click();
    await sleep(500);
    const mark = pageMark();
    if (mark === guard) return {typed: typed, clicked: false, reason: 'row-not-found', pages_turned: pagesTurned};
    guard = mark;
    pagesTurned += 1;
  }
  return {typed: typed, clicked: false, reason: 'row-not-found', pages_turned: pagesTurned};
})()"""


# Fill the list-search script for one page. The filter is typed only on the first page.
def list_search_js(refno: str, *, type_filter: bool) -> str:
    return (
        LIST_SEARCH_JS
        .replace("__REFNO__", json.dumps(refno))
        .replace("__TYPE_FILTER__", "true" if type_filter else "false")
    )


# Read a page-turn count from the browser, treating anything unreadable as zero.
def _page_turns(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


# Build the records URL for a refno: an explicit base URL wins (a non-standard deployment),
# otherwise the active site profile supplies it, so no caller has to know which host is live.
def build_records_url(refno: str, base_url: str | None) -> str:
    if base_url:
        return f"{base_url.rstrip('/')}/records.html?refno={refno.strip()}"
    return records_url_for_refno(refno)


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


# Search the list page like a human: return (target URL, flow label) or (None, not_found).
# The list URL and the tab-group label come from the active site profile, not from a
# hard-coded demo shape, so the same flow drives the internal system unchanged.
# When the matching row is on a later page, follow the pager — an in-page control is
# clicked inside the script, and a link that loads a new page is opened here and searched again.
def navigate_like_human(
    browser: WebBridgeClient, *, refno: str, list_url: str, records_url: str, tab_group_title: str
) -> tuple[str | None, str]:
    browser.navigate(list_url, new_tab=True, group_title=tab_group_title)
    _focus_current_tab(browser)
    type_filter = True
    pages_turned = 0
    seen_hrefs: set[str] = set()
    searched = False
    while True:
        try:
            found = browser.evaluate(list_search_js(refno, type_filter=type_filter))
        except Exception:
            found = None
        if not isinstance(found, dict):
            break
        turned = pages_turned + _page_turns(found.get("pages_turned"))
        searched = searched or bool(found.get("typed")) or turned > 0
        if found.get("clicked") and found.get("href"):
            return str(found["href"]), "view_link_paged" if turned else "view_link"
        next_href = str(found.get("href") or "") if found.get("reason") == "next-page" else ""
        if next_href and next_href not in seen_hrefs and turned < MAX_LIST_PAGES:
            seen_hrefs.add(next_href)
            pages_turned = turned + 1
            type_filter = False
            browser.navigate(next_href, new_tab=False, group_title=tab_group_title)
            _focus_current_tab(browser)
            continue
        break
    # The list was actually searched and the row was not on any page reached.
    if searched:
        return None, "not_found"
    # Could not drive the list (DOM changed); fall back to the direct records URL.
    return records_url, "fallback_direct_url"


# Collect one job: write records.html + cvs/<appno>.pdf + a PII-free manifest.
def collect_job(
    *,
    records_url: str,
    folder: Path,
    profile: dict[str, Any] | None = None,
    driver: str = "webbridge",
    base_url: str | None = None,
    refno: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
    cookie_file: str | None = None,
    client: WebBridgeClient | None = None,
) -> dict[str, Any]:
    profile = profile or site_profile()
    folder = Path(folder)
    # Start from an empty cvs/ so a CV left behind by an earlier run — possibly a run on the
    # other site — can never be scored as one of this run's applicants.
    cvs_dir = folder / "cvs"
    if cvs_dir.is_dir():
        shutil.rmtree(cvs_dir)
    cvs_dir.mkdir(parents=True, exist_ok=True)
    effective_base = base_url or str(profile.get("base_url") or "") or origin_of(records_url)
    tab_group_title = str(profile.get("tab_group_title") or "")
    if not refno:
        refno = refno_from_url(records_url)
    if driver == "http":
        html = asyncio.run(_jas_fetch.fetch_html(records_url, cookie_file=cookie_file, allowed_hosts=allowed_hosts))
    else:
        browser = client or WebBridgeClient()
        human_flow: str | None = None
        # The visible human flow is a property of the site profile, not of whether a
        # demo-shaped base URL happened to be passed in — prod needs it too.
        if profile.get("human_flow_available") and refno:
            # Human-like flow: find the job on the list page, then open its View link.
            target, human_flow = navigate_like_human(
                browser,
                refno=refno,
                list_url=str(profile.get("list_url") or ""),
                records_url=records_url,
                tab_group_title=tab_group_title,
            )
            if target is None:
                # The list-page search found no matching row; keep the page open and report not found.
                raise JobNotFoundError(f"no JAS job found for refno {refno} (no matching row in the records list)")
            browser.navigate(target, new_tab=False, group_title=tab_group_title)
            _focus_current_tab(browser)
        else:
            browser.navigate(records_url, new_tab=True, group_title=tab_group_title)
            _focus_current_tab(browser)
        # A site that requires a login must actually be signed in before we read the page.
        # Without this gate a logged-out run reads the identity provider's page, which parses as
        # "no job" and reports a missing job for what is really a missing session — the one
        # failure HR would chase in the wrong direction. Sites that expect no login are unaffected.
        ensure_signed_in(browser, profile)
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
        dest = cvs_dir / f"{safe_pack_id(appno, fallback='unknown')}.pdf"
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
        # Which site these CVs came from: the pack carries it so a later run can tell that
        # its cached artifacts belong to the other site.
        "site": profile["mode"],
        "refno": job.get("refno", ""),
        "post_title": (job.get("job") or {}).get("post_title", ""),
        # The post applied for travels with each candidate (PRD Section 6); it is None on a
        # single-post page, so the collector's own folder stays one folder per refno.
        "candidates": [
            {"appno": c.get("appno"), "status": c.get("status"), "post": c.get("post")}
            for c in job.get("candidates", [])
        ],
        "cv_downloaded": sorted(cvs),
        "candidates_without_cv": sorted(known - set(cvs)),
        "download_failures": failures,
    }
    # The post list with per-post applicant counts, only when the page states a post (Section 6).
    posts = post_counts(job.get("candidates"))
    if posts:
        manifest["multi_post"] = bool((job.get("job") or {}).get("multi_post"))
        manifest["posts"] = posts
    if driver == "webbridge" and human_flow is not None:
        manifest["human_flow"] = human_flow
    (folder / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


__all__ = [
    "COLLECT_ROOT_NAME",
    "MANIFEST_NAME",
    "MAX_LIST_PAGES",
    "build_records_url",
    "collect_job",
    "list_search_js",
    "navigate_like_human",
    "origin_of",
]
