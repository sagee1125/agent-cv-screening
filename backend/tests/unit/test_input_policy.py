# Unit tests for the PII-safe input policy validator.
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# backend/tests/unit/test_input_policy.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_SRC = REPO_ROOT / ".codex" / "skills" / "_shared" / "src"
sys.path.insert(0, str(SHARED_SRC))

from screening_core.input_policy import (  # noqa: E402
    InputPolicyError,
    extra_allowed_hosts_from_env,
    is_data_uri,
    is_http_url,
    looks_like_base64,
    merge_allowed_hosts,
    validate_path,
    validate_extracted_reference,
    validate_reference,
    validate_references,
    validate_url,
)

BASE64_BLOB = (
    "SGVsbG8gV29ybGQhISAgIFRoaXMgaXMgYSBiYXNlNjQgYmxvYiB0aGF0IG11c3QgYmUgcmVqZWN0ZWQg"
    "YnkgdGhlIHBvbGljeSBndWFyZCAgICAg"
)


# Existing file paths pass the path check.
def test_validate_reference_accepts_existing_file(tmp_path) -> None:
    target = tmp_path / "cv.pdf"
    target.write_bytes(b"%PDF")
    result = validate_reference(str(target), flag="--cv")
    assert Path(result) == target.resolve()


# Missing paths are rejected as not-a-file.
def test_validate_reference_rejects_missing_path(tmp_path) -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_reference(str(tmp_path / "nope.pdf"), flag="--cv")
    assert exc.value.reason == "not-a-file"


# Base64 blobs are rejected with a clear inline-content message.
def test_validate_reference_rejects_base64() -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_reference(BASE64_BLOB, flag="--cv")
    assert exc.value.reason == "base64"
    assert "inline content" in str(exc.value)


# data: URIs are rejected as inline content.
def test_validate_reference_rejects_data_uri() -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_reference("data:text/plain;base64,SGVsbG8=", flag="--jd-file")
    assert exc.value.reason == "data-uri"


# Multi-line inline text is rejected.
def test_validate_reference_rejects_multiline_text() -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_reference("line1\nline2\nline3", flag="--cv")
    assert exc.value.reason == "inline-text"


# Over-length values are rejected as inline content.
def test_validate_reference_rejects_too_long() -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_reference("x" * 10000, flag="--cv")
    assert exc.value.reason == "too-long"


# Empty references are rejected.
def test_validate_reference_rejects_empty() -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_reference("   ", flag="--cv")
    assert exc.value.reason == "empty"


# Allowlisted http(s) URLs pass.
def test_validate_url_accepts_allowlisted_host() -> None:
    url = "https://jobs.polyu.edu.hk/internal/records.php?refno=190001010"
    assert validate_url(url, flag="--polyu-detail-url") == url
    assert validate_reference(url, flag="--polyu-detail-url") == url


# Non-allowlisted hosts are rejected.
def test_validate_url_rejects_disallowed_host() -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_reference("https://evil.example.com/x", flag="--polyu-detail-url")
    assert exc.value.reason == "host-not-allowlisted"


# Non-http schemes (file://) are rejected as bad URLs.
def test_validate_url_rejects_file_scheme() -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_url("file:///C:/temp/cv.pdf", flag="--polyu-detail-url")
    assert exc.value.reason == "bad-url"


# Lists are validated element by element.
def test_validate_references_accepts_existing_files(tmp_path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"%PDF")
    b.write_bytes(b"%PDF")
    results = validate_references([str(a), str(b)], flag="--cv")
    assert len(results) == 2


# Extracted profiles must live in the output dir unless explicitly trusted.
def test_validate_extracted_reference_requires_scratch_or_trust(tmp_path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    inside = out_dir / "extracted-alice.json"
    inside.write_text("{}", encoding="utf-8")
    outside = tmp_path / "alice.json"
    outside.write_text("{}", encoding="utf-8")

    assert validate_extracted_reference(str(inside), out_dir=out_dir) == str(inside.resolve())

    with pytest.raises(InputPolicyError) as exc:
        validate_extracted_reference(str(outside), out_dir=out_dir)
    assert exc.value.reason == "extracted-outside-scratch"
    assert "--trust-extracted" in str(exc.value)

    assert validate_extracted_reference(str(outside), out_dir=out_dir, trusted=True) == str(outside.resolve())


# Extracted profiles remain local files even when trusted mode is enabled.
def test_validate_extracted_reference_rejects_url_when_trusted(tmp_path) -> None:
    with pytest.raises(InputPolicyError) as exc:
        validate_extracted_reference(
            "https://jobs.polyu.edu.hk/internal/profile.json",
            out_dir=tmp_path,
            trusted=True,
        )
    assert exc.value.reason == "extracted-not-local"


# Detector helpers behave as expected.
def test_detector_helpers() -> None:
    assert is_http_url("https://jobs.polyu.edu.hk/")
    assert not is_http_url("C:\\temp\\cv.pdf")
    assert is_data_uri("data:text/plain;base64,SGVsbG8=")
    assert looks_like_base64(BASE64_BLOB)
    assert not looks_like_base64(str(Path("data/cv.pdf")))

# JAS_ALLOWED_HOSTS env var adds extra allowlisted hosts.
def test_extra_allowed_hosts_from_env(monkeypatch) -> None:
    monkeypatch.setenv("JAS_ALLOWED_HOSTS", "jes-web-demo.vercel.app, example.com")
    assert extra_allowed_hosts_from_env() == ("jes-web-demo.vercel.app", "example.com")
    monkeypatch.delenv("JAS_ALLOWED_HOSTS")
    assert extra_allowed_hosts_from_env() == ()


# merge_allowed_hosts de-duplicates and lower-cases host groups.
def test_merge_allowed_hosts() -> None:
    merged = merge_allowed_hosts(("Jobs.Polyu.Edu.Hk",), None, ["jes-web-demo.vercel.app", "JOBS.POLYU.EDU.HK"])
    assert merged == ("jobs.polyu.edu.hk", "jes-web-demo.vercel.app")


# Custom allowed_hosts lets a public demo host pass URL validation.
def test_validate_url_custom_allowed_hosts() -> None:
    url = "https://jes-web-demo.vercel.app/records.html?refno=2600827001"
    assert validate_url(url, flag="--records-url", allowed_hosts=("jes-web-demo.vercel.app",)) == url