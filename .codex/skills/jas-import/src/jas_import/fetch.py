# Fetches JAS pages and CV files over HTTP with an optional local cookie jar.
from __future__ import annotations

import re
from typing import Any
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from jas_import.errors import JobNotFoundError
from jas_import.records import build_jd_text, parse_job_html
from jas_import.skill import job_payload_from_html
from screening_core.candidate_id import refno_from_url
from screening_core.input_policy import validate_url
from screening_core.ssl_verify import resolve_ssl_verify

DEFAULT_TIMEOUT = 30.0
DOWNLOAD_TIMEOUT = 60.0
MAX_REDIRECTS = 5
_SAFE_EXTENSIONS = {".pdf", ".doc", ".docx"}


# Load cookies from a Netscape cookies.txt file into an httpx.Cookies object.
def load_cookie_file(path: str | Path) -> httpx.Cookies:
    cookies = httpx.Cookies()
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("#HttpOnly_"):
                line = line.removeprefix("#HttpOnly_")
            elif not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain, _subdomains, path_value, _secure, _expiry, name, value = parts[:7]
                cookies.set(name, value, domain=domain, path=path_value or "/")
    return cookies


# Performs one authenticated GET while validating every redirect target.
async def _request(
    url: str,
    cookie_file: str | Path | None,
    timeout: float,
    allowed_hosts: tuple[str, ...] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    cookies = load_cookie_file(cookie_file) if cookie_file else None
    current_url = validate_url(url, flag="request URL", allowed_hosts=allowed_hosts)
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, cookies=cookies, verify=resolve_ssl_verify()
    ) as client:
        for _redirect in range(MAX_REDIRECTS + 1):
            response = await client.get(current_url, headers=headers)
            if response.status_code == 304:
                return response
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError(f"redirect response from {current_url} had no location")
                current_url = validate_url(urljoin(str(response.url), location), flag="redirect URL", allowed_hosts=allowed_hosts)
                continue
            response.raise_for_status()
            validate_url(str(response.url), flag="final response URL", allowed_hosts=allowed_hosts)
            return response
    raise ValueError(f"too many redirects while fetching {url}")


# Fetches an HTML page, optionally authenticated with a local cookie jar.
async def fetch_html(
    url: str,
    *,
    cookie_file: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    allowed_hosts: tuple[str, ...] | None = None,
) -> str:
    response = await _request(url, cookie_file, timeout, allowed_hosts=allowed_hosts)
    return response.text


# Downloads a file (e.g. a CV) to the given destination path.
async def download_to(
    url: str,
    dest: str | Path,
    *,
    cookie_file: str | Path | None = None,
    timeout: float = DOWNLOAD_TIMEOUT,
    allowed_hosts: tuple[str, ...] | None = None,
) -> Path:
    response = await _request(url, cookie_file, timeout, allowed_hosts=allowed_hosts)
    if not response.content:
        raise ValueError(f"empty download from {url}")
    path = Path(dest)
    path.write_bytes(response.content)
    return path


# Downloads a file only when its server ETag / Last-Modified changed (304 reuse).
async def download_to_if_changed(
    url: str,
    dest: str | Path,
    *,
    cookie_file: str | Path | None = None,
    timeout: float = DOWNLOAD_TIMEOUT,
    allowed_hosts: tuple[str, ...] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> tuple[bool, dict[str, str]]:
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    response = await _request(url, cookie_file, timeout, allowed_hosts=allowed_hosts, headers=headers or None)
    meta = {
        "etag": response.headers.get("etag") or "",
        "last_modified": response.headers.get("last-modified") or "",
    }
    if response.status_code == 304:
        return False, meta
    if not response.content:
        raise ValueError(f"empty download from {url}")
    Path(dest).write_bytes(response.content)
    return True, meta


# Strips HTML tags into plain text (fallback for non-JAS pages).
def html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", "", raw_html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", "", text)
    text = re.sub(r"(?is)<form[^>]*>.*?</form>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|li|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Fetches a JAS records page and returns only its structured JD text.
async def fetch_jd_text(
    url: str,
    *,
    cookie_file: str | Path | None = None,
    base_url: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
) -> str:
    html = await fetch_html(url, cookie_file=cookie_file, allowed_hosts=allowed_hosts)
    detail = parse_job_html(html, base_url=base_url)
    if detail.fields:
        return build_jd_text(detail)
    raise ValueError("JAS page did not contain a recognizable job advertisement table")


# Fetches a JAS records page and returns the full job payload (JD + candidates).
async def fetch_job_payload(
    url: str,
    *,
    cookie_file: str | Path | None = None,
    base_url: str | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    html = await fetch_html(url, cookie_file=cookie_file, allowed_hosts=allowed_hosts)
    payload = job_payload_from_html(html, base_url=base_url)
    refno = refno_from_url(url) or payload.get("refno") or "the requested job"
    if not payload.get("refno"):
        raise JobNotFoundError(f"no JAS job found for {refno} (page had no job reference)")
    if not (payload.get("jd_text") or "").strip():
        raise JobNotFoundError(f"no JAS job found for {refno} (page had no job advertisement)")
    return payload


# Derives a safe local filename for a downloaded CV from its URL.
def cv_filename_for_url(url: str, *, fallback_ext: str = ".pdf") -> str:
    parsed = urlparse(url)
    appno = parse_qs(parsed.query).get("id", [None])[0]
    stem = (appno or Path(parsed.path).stem or "cv").strip()
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem) or "cv"
    ext = Path(parsed.path).suffix.lower()
    if ext not in _SAFE_EXTENSIONS:
        ext = fallback_ext
    return f"{stem}{ext}"


__all__ = [
    "cv_filename_for_url",
    "download_to",
    "download_to_if_changed",
    "fetch_html",
    "fetch_jd_text",
    "fetch_job_payload",
    "html_to_text",
    "load_cookie_file",
]
