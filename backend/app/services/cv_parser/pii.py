# Detects and masks candidate PII locally before any CV content leaves the server.
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.cv_parser.prompts import KNOWN_SKILLS


EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d \t().-]{6,}\d)")
DATE_RANGE_PATTERN = re.compile(
    r"^(?:(?:19|20)\d{2}(?:[./-]\d{1,2})?)"
    r"\s*(?:-|–|—|to)\s*"
    r"(?:(?:19|20)\d{2}(?:[./-]\d{1,2})?)$",
    flags=re.IGNORECASE,
)
NAME_LABEL_PATTERN = re.compile(
    r"(?im)^\s*(?:full\s+name|name)\s*[:：]\s*([^\n]{1,64})\s*$"
)
SECTION_HEADINGS = {
    "about",
    "career objective",
    "contact",
    "curriculum vitae",
    "education",
    "experience",
    "personal profile",
    "profile",
    "professional summary",
    "resume",
    "skills",
    "summary",
    "work experience",
}
NON_NAME_TOKENS = {
    "analyst",
    "architect",
    "company",
    "consultant",
    "corporation",
    "developer",
    "engineer",
    "manager",
    "scientist",
    "student",
    "university",
}
CONTACT_PLACEHOLDERS = {
    "name": "[NAME_REDACTED]",
    "email": "[EMAIL_REDACTED]",
    "phone": "[PHONE_REDACTED]",
}


@dataclass(frozen=True)
class PIIEntity:
    """Represents one locally detected PII span in extracted CV text."""

    kind: str
    value: str
    start: int
    end: int


# Returns whether a line conservatively resembles a candidate name.
def _looks_like_name(line: str) -> bool:
    normalized = " ".join(line.split()).strip(" ,;")
    if not normalized or normalized.casefold().rstrip(":") in SECTION_HEADINGS:
        return False
    if normalized.casefold() in KNOWN_SKILLS:
        return False
    if any(token.casefold().strip(".,") in NON_NAME_TOKENS for token in normalized.split()):
        return False
    if len(normalized) > 64 or any(char.isdigit() for char in normalized):
        return False
    if any(marker in normalized for marker in ("@", ":", "：", "/", "\\", "|")):
        return False

    if re.fullmatch(r"[\u3400-\u9fff·]{2,8}", normalized):
        return True
    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){0,5}", normalized):
        return False
    return 1 <= len(normalized.split()) <= 6


# Selects plausible name lines from the document header for conservative redaction.
def extract_name_candidates(raw_text: str) -> list[str]:
    candidates: list[str] = []
    labelled_match = NAME_LABEL_PATTERN.search(raw_text)
    if labelled_match:
        labelled_name = " ".join(labelled_match.group(1).split()).strip()
        if _looks_like_name(labelled_name):
            candidates.append(labelled_name)

    nonempty_lines = [" ".join(line.split()).strip() for line in raw_text.splitlines() if line.strip()]
    for line in nonempty_lines[:12]:
        if _looks_like_name(line) and line.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(line)
    return candidates


# Selects the primary local candidate name from conservative header candidates.
def extract_name_hint(raw_text: str) -> str | None:
    candidates = extract_name_candidates(raw_text)
    return candidates[0] if candidates else None


# Returns whether a numeric span is plausibly a phone rather than a CV date range.
def is_phone_candidate(candidate: str) -> bool:
    normalized = " ".join(candidate.split()).strip()
    if DATE_RANGE_PATTERN.fullmatch(normalized):
        return False
    digit_count = sum(char.isdigit() for char in normalized)
    return 8 <= digit_count <= 15


# Detects all structured contact spans and the locally inferred candidate-name span.
def detect_contact_entities(raw_text: str) -> list[PIIEntity]:
    entities: list[PIIEntity] = []
    for match in EMAIL_PATTERN.finditer(raw_text):
        entities.append(PIIEntity("email", match.group(0), match.start(), match.end()))

    for match in PHONE_PATTERN.finditer(raw_text):
        candidate = match.group(0).strip()
        if not is_phone_candidate(candidate):
            continue
        leading_space_count = len(match.group(0)) - len(match.group(0).lstrip())
        start = match.start() + leading_space_count
        entities.append(PIIEntity("phone", candidate, start, start + len(candidate)))

    for name in extract_name_candidates(raw_text):
        flexible_name_pattern = r"\s+".join(re.escape(part) for part in name.split())
        name_match = re.search(flexible_name_pattern, raw_text, flags=re.IGNORECASE)
        if name_match:
            entities.append(PIIEntity("name", name_match.group(0), name_match.start(), name_match.end()))

    entities.sort(key=lambda entity: (entity.start, -(entity.end - entity.start)))
    return entities


# Extracts the primary local identity fields while retaining all spans for masking.
def extract_contact_hints_local(raw_text: str) -> dict[str, str | None]:
    entities = detect_contact_entities(raw_text)

    def first_value(kind: str) -> str | None:
        # Returns the first detected value for a requested PII kind.
        return next((entity.value for entity in entities if entity.kind == kind), None)

    return {
        "name": first_value("name"),
        "email": first_value("email"),
        "phone": first_value("phone"),
    }


# Replaces every detected PII span with a semantic placeholder for text LLM input.
def mask_pii_text(raw_text: str) -> str:
    masked = raw_text
    for entity in reversed(detect_contact_entities(raw_text)):
        placeholder = CONTACT_PLACEHOLDERS[entity.kind]
        masked = f"{masked[:entity.start]}{placeholder}{masked[entity.end:]}"
    return masked


# Returns unique local PII values that must be removed from rendered PDF pages.
def contact_values_for_redaction(raw_text: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for entity in detect_contact_entities(raw_text):
        normalized = entity.value.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        values.append(entity.value)
    return values


# Removes identity keys from an untrusted LLM payload before normalization or persistence.
def strip_contact_fields(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key.casefold() not in {"name", "email", "phone", "telephone", "mobile"}
    }
