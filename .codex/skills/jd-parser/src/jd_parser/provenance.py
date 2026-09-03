# Locate original JD excerpts for parsed skills and requirement cues.
from __future__ import annotations

import re
from typing import Any

_MAX_EXCERPT = 240
_BULLET_CHARS = " \t-*•·"
_SENTENCE_BREAK = re.compile(r"[.!?。；;]\s+")
# Boilerplate JD lines (headers/footers) that must never be quoted as an excerpt.
_NOISE_PREFIXES = (
    "job group:", "unit:", "department:", "faculty:", "school of",
    "reference number:", "ref no.", "ref no:", "post title:", "job title:",
    "posting date:", "closing date:", "application deadline:",
    "list type:", "list in external", "list in internal",
    "conditions of service", "consideration of applications",
    "for further information", "further information:", "please contact",
    "number of applications", "email notification", "display to external",
    "equal opportunity", "about us", "who we are",
    "enquiries:", "enquiry:", "contact dr", "contact person:",
)


def empty_skill_provenance(confidence: float = 0.75) -> dict[str, Any]:
    """Return an empty skill provenance object."""
    return {
        "source_sentence": "",
        "source_char_start": 0,
        "source_char_end": 0,
        "confidence": confidence,
    }


def find_source_excerpt(jd_text: str, needles: list[str]) -> dict[str, Any]:
    """Return the original JD line or sentence matching the first needle hit."""
    match = _first_needle_match(jd_text, needles)
    if match is None:
        return empty_skill_provenance()
    excerpt, start, end = _excerpt_around(jd_text, match[0], match[1])
    return {
        "source_sentence": excerpt,
        "source_char_start": start,
        "source_char_end": end,
        "confidence": 0.75,
    }


def find_cue_excerpt(jd_text: str, cues: list[str]) -> str:
    """Return the original JD line matching a requirement cue, or empty."""
    match = _first_needle_match(jd_text, cues)
    if match is None:
        return ""
    excerpt, _, _ = _excerpt_around(jd_text, match[0], match[1])
    return excerpt


def _match_in_noise_line(text: str, position: int) -> bool:
    """Return True when the line holding a match is JD header/footer boilerplate."""
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end < 0:
        line_end = len(text)
    stripped = text[line_start:line_end].lstrip(_BULLET_CHARS).casefold()
    return any(stripped.startswith(prefix) for prefix in _NOISE_PREFIXES)


def _first_needle_match(text: str, needles: list[str]) -> tuple[int, int] | None:
    """Find the earliest non-boilerplate case-insensitive needle span in text."""
    best: tuple[int, int] | None = None
    seen: set[str] = set()
    for needle in needles:
        cleaned = (needle or "").strip()
        if len(cleaned) < 2:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(cleaned) + r"(?![a-z0-9])",
            re.IGNORECASE,
        )
        for found in pattern.finditer(text):
            if _match_in_noise_line(text, found.start()):
                continue
            span = (found.start(), found.end())
            if best is None or span[0] < best[0] or (span[0] == best[0] and span[1] > best[1]):
                best = span
            break
    return best



def _excerpt_around(text: str, match_start: int, match_end: int) -> tuple[str, int, int]:
    """Expand a match to its original line, or a nearby sentence when the line is long."""
    line_start = text.rfind("\n", 0, match_start) + 1
    line_end = text.find("\n", match_end)
    if line_end < 0:
        line_end = len(text)
    raw_line = text[line_start:line_end]
    stripped = raw_line.strip(_BULLET_CHARS)
    if not stripped:
        return "", 0, 0
    inner = raw_line.find(stripped)
    abs_start = line_start + max(inner, 0)
    abs_end = abs_start + len(stripped)
    if len(stripped) <= _MAX_EXCERPT:
        return stripped, abs_start, abs_end
    return _sentence_window(text, line_start, line_end, match_start, match_end)


def _sentence_window(
    text: str,
    line_start: int,
    line_end: int,
    match_start: int,
    match_end: int,
) -> tuple[str, int, int]:
    """Cut a long line down to the sentence that contains the match."""
    line = text[line_start:line_end]
    rel_start = match_start - line_start
    rel_end = match_end - line_start
    sentence_start = 0
    for found in _SENTENCE_BREAK.finditer(line):
        if found.end() <= rel_start:
            sentence_start = found.end()
        elif found.start() >= rel_end:
            sentence_end = found.start() + 1
            snippet = line[sentence_start:sentence_end].strip(_BULLET_CHARS)
            abs_start = line_start + line.find(snippet, sentence_start)
            return snippet[:_MAX_EXCERPT], abs_start, abs_start + min(len(snippet), _MAX_EXCERPT)
    snippet = line[sentence_start:].strip(_BULLET_CHARS)
    if len(snippet) > _MAX_EXCERPT:
        local = max(rel_start - 80, sentence_start)
        snippet = line[local : local + _MAX_EXCERPT].strip(_BULLET_CHARS)
        abs_start = line_start + line.find(snippet, local)
        return snippet, abs_start, abs_start + len(snippet)
    abs_start = line_start + line.find(snippet, sentence_start)
    return snippet[:_MAX_EXCERPT], abs_start, abs_start + min(len(snippet), _MAX_EXCERPT)
