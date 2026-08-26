# Enforces the PII-safe input contract: accept only file paths or allowlisted URLs.
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_URL_HOSTS = ("jobs.polyu.edu.hk",)
MAX_REFERENCE_LENGTH = 8192
CONTRACT_MESSAGE = (
    "This skill only accepts file paths or http(s) URLs. "
    "Do not parse file content and pass it in; inline content (base64/text) is refused."
)

_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


# Raised when an input reference violates the path/URL-only contract.
class InputPolicyError(ValueError):
    def __init__(self, message: str, *, reason: str = "policy") -> None:
        """Record the policy reason alongside the human-readable message."""
        self.reason = reason
        super().__init__(message)


# Returns True when the value is an http(s) URL.
def is_http_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


# Returns True when the value is a data: URI (inline content).
def is_data_uri(value: str) -> bool:
    return value.lower().startswith("data:") or ";base64," in value.lower()


# Returns True when the value looks like a base64 blob rather than a path.
def looks_like_base64(value: str) -> bool:
    if len(value) < 64:
        return False
    if "\\" in value or "/" in value:
        return False
    return bool(_BASE64_RE.fullmatch(value))


# Validates and normalizes a file path reference.
def validate_path(value: str, *, flag: str = "input") -> str:
    path = Path(value)
    if not path.is_file():
        raise InputPolicyError(
            f"{flag} is not an existing file path. {CONTRACT_MESSAGE}",
            reason="not-a-file",
        )
    return str(path.resolve())


# Validates and normalizes an http(s) URL reference against the host allowlist.
def validate_url(value: str, *, flag: str = "input", allowed_hosts: tuple[str, ...] = ALLOWED_URL_HOSTS) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise InputPolicyError(f"{flag} is not an http(s) URL. {CONTRACT_MESSAGE}", reason="bad-url")
    if allowed_hosts and host not in allowed_hosts:
        raise InputPolicyError(
            f"{flag} host '{host}' is not allowlisted (allowed: {', '.join(allowed_hosts)}). {CONTRACT_MESSAGE}",
            reason="host-not-allowlisted",
        )
    return value


# Validates one reference: an existing file path or an allowlisted http(s) URL.
def validate_reference(
    value: str | None,
    *,
    flag: str = "input",
    allowed_hosts: tuple[str, ...] = ALLOWED_URL_HOSTS,
) -> str:
    if not value:
        raise InputPolicyError(f"{flag} is empty. {CONTRACT_MESSAGE}", reason="empty")
    text = str(value).strip()
    if not text:
        raise InputPolicyError(f"{flag} is empty. {CONTRACT_MESSAGE}", reason="empty")
    if len(text) > MAX_REFERENCE_LENGTH:
        raise InputPolicyError(f"{flag} is too long to be a path or URL; inline content is refused.", reason="too-long")
    if "\n" in text or "\r" in text:
        raise InputPolicyError(f"{flag} contains newlines; inline text is refused. {CONTRACT_MESSAGE}", reason="inline-text")
    lowered = text.lower()
    if lowered.startswith("data:") or ";base64," in lowered:
        raise InputPolicyError(f"{flag} is a data URI; inline content is refused. {CONTRACT_MESSAGE}", reason="data-uri")
    if is_http_url(text):
        return validate_url(text, flag=flag, allowed_hosts=allowed_hosts)
    if looks_like_base64(text):
        raise InputPolicyError(f"{flag} looks like a base64 blob; inline content is refused. {CONTRACT_MESSAGE}", reason="base64")
    return validate_path(text, flag=flag)


# Validates an extracted-profile reference: existing file, optionally inside out_dir.
def validate_extracted_reference(
    value: str | None,
    *,
    out_dir: str | Path,
    trusted: bool = False,
    flag: str = "--extracted",
    allowed_hosts: tuple[str, ...] = ALLOWED_URL_HOSTS,
) -> str:
    if value and is_http_url(str(value).strip()):
        raise InputPolicyError(
            f"{flag} must be an existing local file, not a URL.",
            reason="extracted-not-local",
        )
    path = Path(validate_reference(value, flag=flag, allowed_hosts=allowed_hosts))
    if not trusted:
        try:
            path.resolve().relative_to(Path(out_dir).resolve())
        except ValueError:
            raise InputPolicyError(
                f"{flag} outside --output-dir requires --trust-extracted (trusted, pre-masked profiles only).",
                reason="extracted-outside-scratch",
            )
    return str(path)


# Validates a list of references and returns their normalized values.
def validate_references(
    values: list[str] | tuple[str, ...],
    *,
    flag: str = "input",
    allowed_hosts: tuple[str, ...] = ALLOWED_URL_HOSTS,
) -> list[str]:
    return [validate_reference(value, flag=flag, allowed_hosts=allowed_hosts) for value in values]


__all__ = [
    "ALLOWED_URL_HOSTS",
    "CONTRACT_MESSAGE",
    "InputPolicyError",
    "is_data_uri",
    "is_http_url",
    "looks_like_base64",
    "validate_extracted_reference",
    "validate_path",
    "validate_reference",
    "validate_references",
    "validate_url",
]