# Fetch and parse PolyU general job listings and detail pages.
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse

POLYU_SOURCE = "polyu"
DEFAULT_BASE_URL = "https://jobs.polyu.edu.hk"
DEFAULT_LIST_URL = "https://jobs.polyu.edu.hk/general.php"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_ROW_RE = re.compile(
    r'<tr\s+class="ITS_clickableTableRow"\s+data-href="([^"]+)"[^>]*>\s*'
    r"<td>(.*?)</td>\s*"
    r"<td>(.*?)</td>\s*"
    r"<td>(.*?)</td>\s*"
    r"<td>(.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
_POSTING_DATE_RE = re.compile(r"Posting date:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", re.IGNORECASE)
_DATE_FORMATS = ("%d %B %Y", "%d %b %Y")


@dataclass(frozen=True)
class PolyUListing:
    """One row from the PolyU general jobs table."""

    job_code: str
    external_ref: str
    title: str
    department: str
    closing_date: datetime | None
    detail_url: str


# Strip HTML tags and decode entities into plain JD text.
def html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", "", raw_html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", "", text)
    text = re.sub(r"(?is)<form[^>]*>.*?</form>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|li|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Normalize a table cell into a single-line string.
def _cell_text(raw_html: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(raw_html)).strip()


# Parse PolyU date strings such as "24 August 2026".
def parse_polyu_date(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned or cleaned.lower() in {"until the position is filled", "n/a", "-"}:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


# Extract the job code from a listing row's data-href.
def _job_code_from_href(href: str) -> str:
    parsed = urlparse(href)
    job_values = parse_qs(parsed.query).get("job", [])
    if job_values:
        return job_values[0].strip()
    match = re.search(r"(\d{6,})", href)
    return match.group(1) if match else href.strip()


# Public alias so the polyu-import skill can avoid importing a private symbol.
job_code_from_href = _job_code_from_href


# Parse the general.php HTML table into listing rows.
def parse_listing_html(html: str, *, base_url: str | None = None) -> list[PolyUListing]:
    origin = base_url or DEFAULT_BASE_URL
    items: list[PolyUListing] = []
    seen: set[str] = set()
    for match in _ROW_RE.finditer(html):
        href, department_html, title_html, closing_html, ref_html = match.groups()
        external_ref = _cell_text(ref_html)
        title = _cell_text(title_html)
        if not external_ref or not title:
            continue
        if external_ref in seen:
            continue
        seen.add(external_ref)
        detail_url = urljoin(origin.rstrip("/") + "/", href.strip())
        items.append(
            PolyUListing(
                job_code=_job_code_from_href(href),
                external_ref=external_ref,
                title=title,
                department=_cell_text(department_html),
                closing_date=parse_polyu_date(_cell_text(closing_html)),
                detail_url=detail_url,
            )
        )
    return items


# Extract posting date and JD body text from a job_detail.php page.
def parse_detail_html(html: str) -> tuple[str, datetime | None]:
    main_match = re.search(r"(?is)<main[^>]*>(.*?)</main>", html)
    body_html = main_match.group(1) if main_match else html
    text = html_to_text(body_html)
    posting_date = None
    posting_match = _POSTING_DATE_RE.search(text)
    if posting_match:
        posting_date = parse_polyu_date(posting_match.group(1))
        text = _POSTING_DATE_RE.sub("", text, count=1).strip()
    text = re.sub(r"(?im)^Apply Now\s*$", "", text).strip()
    return text, posting_date


# Build the stored JD description from listing metadata plus detail text.
def build_job_description(listing: PolyUListing, detail_text: str) -> str:
    header = [
        f"Department / Unit: {listing.department}" if listing.department else None,
        f"Ref. No.: {listing.external_ref}",
        f"Source: {listing.detail_url}",
        "",
    ]
    prefix = "\n".join(part for part in header if part is not None)
    body = detail_text.strip() or listing.title
    return f"{prefix}\n{body}".strip()


# Download a PolyU HTML page with a browser-like user agent.
async def fetch_polyu_html(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


# Fetch and parse the configured PolyU general jobs listing.
async def fetch_polyu_listings() -> list[PolyUListing]:
    from screening_core.config import settings

    html = await fetch_polyu_html(settings.polyu_jobs_list_url or DEFAULT_LIST_URL)
    return parse_listing_html(html, base_url=settings.polyu_jobs_base_url or DEFAULT_BASE_URL)


# Fetch a job detail page and return plain JD text plus posting date.
async def fetch_polyu_detail(listing: PolyUListing) -> tuple[str, datetime | None]:
    html = await fetch_polyu_html(listing.detail_url)
    return parse_detail_html(html)
