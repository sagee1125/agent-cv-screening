# Validate and normalize PolyU JAS CV download URLs (internal/file.php?t=cv&id=&refno=).
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

POLYU_JAS_HOST = "jobs.polyu.edu.hk"
POLYU_CV_FILE_PATH = "/internal/file.php"


# True when the URL targets the internal PolyU JAS host.
def is_polyu_jas_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    return host == POLYU_JAS_HOST


# Rewrite PolyU CV links to the canonical /internal/file.php path when the query is already t=cv.
def normalize_polyu_cv_download_url(url: str) -> str:
    """Fix host-relative paths that landed on /file.php instead of /internal/file.php."""
    stripped = url.strip()
    if not stripped:
        return stripped
    parsed = urlparse(stripped)
    if (parsed.hostname or "").casefold() != POLYU_JAS_HOST:
        return stripped
    path = parsed.path or ""
    if not path.endswith("file.php"):
        return stripped
    if path != POLYU_CV_FILE_PATH:
        path = POLYU_CV_FILE_PATH
    flat = _flatten_query(parse_qs(parsed.query, keep_blank_values=False))
    query = urlencode(flat, doseq=False)
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", query, ""))


# Flatten parse_qs lists to single string values for stable URL encoding.
def _flatten_query(query: dict[str, list[str]]) -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, values in query.items():
        if values:
            flat[key] = values[0]
    return flat


# Enforce the PolyU CV download shape before HTTP fetch (matches browser navigate to file.php).
def validate_polyu_cv_download_url(url: str, *, job_refno: str | None = None) -> str:
    """Return a canonical URL or raise ValueError with a short reason."""
    normalized = normalize_polyu_cv_download_url(url)
    parsed = urlparse(normalized)
    if (parsed.hostname or "").casefold() != POLYU_JAS_HOST:
        raise ValueError(f"CV link host must be {POLYU_JAS_HOST!r}")
    if parsed.path != POLYU_CV_FILE_PATH:
        raise ValueError(
            f"CV link must be {POLYU_JAS_HOST}{POLYU_CV_FILE_PATH}?t=cv&id=<id>&refno=<refno>, "
            f"path was {parsed.path!r}"
        )
    query = _flatten_query(parse_qs(parsed.query, keep_blank_values=False))
    if query.get("t") != "cv":
        raise ValueError("CV link must include query t=cv")
    file_id = str(query.get("id") or "").strip()
    refno = str(query.get("refno") or "").strip()
    if not file_id.isdigit():
        raise ValueError("CV link must include numeric id=<file id>")
    if not refno.isdigit():
        raise ValueError("CV link must include numeric refno=<job refno>")
    expected_refno = str(job_refno or "").strip()
    if expected_refno and refno != expected_refno:
        raise ValueError(f"CV link refno={refno} does not match job refno={expected_refno}")
    canonical = urlencode({"t": "cv", "id": file_id, "refno": refno}, doseq=False)
    return urlunparse((parsed.scheme or "https", parsed.netloc, POLYU_CV_FILE_PATH, "", canonical, ""))


# Validate CV download URLs for PolyU; pass other hosts through unchanged.
def prepare_cv_download_url(url: str, *, job_refno: str | None = None) -> str:
    """Run PolyU shape checks when the link targets jobs.polyu.edu.hk."""
    stripped = url.strip()
    if not stripped:
        raise ValueError("empty CV URL")
    if is_polyu_jas_host(stripped):
        return validate_polyu_cv_download_url(stripped, job_refno=job_refno)
    return stripped
