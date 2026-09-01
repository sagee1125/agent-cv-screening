# Resolves the composite HR candidate key: job ref no. + application no.
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Display identity is always (refno, appno). Names are never shown.
# First-letter masking (e.g. "C***") is not used: it is still identifying in a
# small applicant pool and is not de-identification under PIPL/GDPR.


# Strip a job-ref prefix from a CV filename stem and return the application no.
def appno_from_filename(stem: str, refno: str | None = None) -> str:
    name = Path(stem).stem.strip()
    if refno:
        prefix = f"{refno}_"
        if name.startswith(prefix):
            name = name[len(prefix) :]
    for artifact_prefix in ("extracted-", "score-", "detail-", "report-"):
        if name.startswith(artifact_prefix):
            name = name[len(artifact_prefix) :]
    return name or "unknown"


# Build the stable on-screen id; never a personal name.
def format_candidate_label(refno: str | None, appno: str | None) -> str:
    job = (refno or "").strip() or "-"
    application = (appno or "").strip() or "unknown"
    if job == "-":
        return application
    return f"{job}/{application}"


# True when the value is a bare JAS job reference number (digits only).
# TODO: Check with HR
# is it only 6-12 digits? or can it contain letters?
# and the length is fixed? or can it be variable?
def is_jas_refno(value: str | None) -> bool:
    text = (value or "").strip()
    return bool(text.isdigit() and 6 <= len(text) <= 12)


# Read refno from a JAS records URL query string when present.
def refno_from_url(url: str | None) -> str | None:
    if not url:
        return None
    values = parse_qs(urlparse(url).query).get("refno") or []
    text = (values[0] if values else "").strip()
    return text or None


# Builds the allowlisted JAS records URL for a job reference number.
def records_url_for_refno(refno: str) -> str:
    return f"https://jobs.polyu.edu.hk/internal/records.php?refno={refno.strip()}"


__all__ = [
    "appno_from_filename",
    "format_candidate_label",
    "is_jas_refno",
    "records_url_for_refno",
    "refno_from_url",
]
