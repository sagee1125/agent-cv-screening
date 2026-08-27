# Redacts emails and filesystem paths from strings that may reach the host LLM.
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s]+")
_POSIX_PATH_RE = re.compile(r"(?:/Users/|/home/|/tmp/)[^\s]+")
_BLOCKED_RE = re.compile(r"(?i)(<html|set-cookie|;base64,)")
_SECRET_ASK_RE = re.compile(r"(?i)\b(cookie|cookies|token|password|secret)\b")


# Returns True when an HR ask-string still talks about secrets or cookies.
def looks_like_secret_ask(value: str) -> bool:
    return bool(_SECRET_ASK_RE.search(str(value or "")))


# Returns True when a host-visible string still looks like a forbidden payload.
def looks_like_forbidden_payload(value: str) -> bool:
    text = str(value or "")
    if _BLOCKED_RE.search(text):
        return True
    if "\n" in text or "\r" in text:
        return True
    return False


# Collapses whitespace, redacts emails/paths, and truncates for host-visible fields.
def sanitize_text(value: object, limit: int = 160) -> str:
    text = _EMAIL_RE.sub("[redacted]", str(value or ""))
    text = _WIN_PATH_RE.sub("[path]", text)
    text = _POSIX_PATH_RE.sub("[path]", text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


__all__ = ["looks_like_forbidden_payload", "looks_like_secret_ask", "sanitize_text"]
