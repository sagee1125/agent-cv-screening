# Unit tests for PolyU JAS CV download URL validation.
from __future__ import annotations

import pytest

from jas_import.cv_links import (
    normalize_polyu_cv_download_url,
    prepare_cv_download_url,
    validate_polyu_cv_download_url,
)

CANONICAL = "https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=300880&refno=260625010"


# Relative hrefs on the records page must normalize to the internal file.php shape.
def test_normalize_relative_cv_link_to_internal_file_php() -> None:
    raw = "https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=300880&refno=260625010"
    assert normalize_polyu_cv_download_url(raw) == CANONICAL


# Root-level /file.php links are rewritten to /internal/file.php with the same query.
def test_normalize_root_file_php_to_internal() -> None:
    raw = "https://jobs.polyu.edu.hk/file.php?t=cv&id=300880&refno=260625010"
    assert normalize_polyu_cv_download_url(raw) == CANONICAL


# Validation rejects wrong t= and refno mismatches before any HTTP download.
def test_validate_rejects_wrong_type_and_refno() -> None:
    with pytest.raises(ValueError, match="t=cv"):
        validate_polyu_cv_download_url(
            "https://jobs.polyu.edu.hk/internal/file.php?t=supp&id=1&refno=260625010"
        )
    with pytest.raises(ValueError, match="refno"):
        validate_polyu_cv_download_url(CANONICAL, job_refno="999999")


# prepare_cv_download_url enforces PolyU rules but leaves demo hosts untouched.
def test_prepare_passes_demo_upload_urls() -> None:
    demo = "https://jes-web-demo.vercel.app/uploads/CV.pdf"
    assert prepare_cv_download_url(demo, job_refno="123") == demo


# Collector-style check accepts the curl-shaped URL the browser uses.
def test_prepare_accepts_browser_cv_url() -> None:
    assert prepare_cv_download_url(CANONICAL, job_refno="260625010") == CANONICAL
