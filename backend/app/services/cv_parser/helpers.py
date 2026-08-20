# Normalizes CV parser output and provides deterministic local fallbacks.
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.core.taxonomy import SkillTaxonomyLoader
from app.services.cv_parser.pii import extract_contact_hints_local
from app.services.cv_parser.prompts import KNOWN_SKILLS

# Path to the curated all-industry skill taxonomy used to canonicalize CV skills.
_TAXONOMY_PATH = "data/taxonomy/skill_taxonomy.yaml"
# Taxonomy category whose nodes are spoken/written languages, not job skills.
_LANGUAGE_CATEGORY = "languages"


# Lazily load and cache the default taxonomy loader (one per process).
@lru_cache(maxsize=1)
def _default_taxonomy() -> SkillTaxonomyLoader:
    loader = SkillTaxonomyLoader(_TAXONOMY_PATH)
    loader.load()
    return loader


# Map a raw degree label (from extract_degree_from_text or free text) to a
# normalized level enum aligned with JD education_requirement.minimum_degree.
_DEGREE_LEVEL_MAP = {
    "PhD": "phd",
    "MPhil": "master",
    "MBA": "mba",
    "Master": "master",
    "Bachelor": "bachelor",
    "Associate": "associate",
}
# Already-normalized level strings and common Chinese degree terms.
_DEGREE_LEVEL_ALIASES = {
    "phd": "phd", "doctorate": "phd", "博士": "phd",
    "master": "master", "masters": "master", "硕士": "master", "碩士": "master",
    "mba": "mba",
    "bachelor": "bachelor", "bachelors": "bachelor", "学士": "bachelor", "學士": "bachelor",
    "associate": "associate",
    "other": "other",
}


# Normalize a degree label or level string into a stable level enum, or None.
def degree_to_level(degree: str | None) -> str | None:
    if not degree:
        return None
    text = str(degree).strip()
    if not text:
        return None
    mapped = _DEGREE_LEVEL_MAP.get(text)
    if mapped:
        return mapped
    return _DEGREE_LEVEL_ALIASES.get(text.casefold())


# Classify a raw skill token as ("skill", canonical_lower) or ("language", display_name).
def classify_skill_token(raw: str, taxonomy: SkillTaxonomyLoader) -> tuple[str, str | None]:
    text = (raw or "").strip()
    if not text:
        return "skill", None
    canonical_preserved = taxonomy.normalize_skill(text)
    if canonical_preserved:
        node = taxonomy.nodes.get(canonical_preserved)
        if node and node.category.strip().casefold() == _LANGUAGE_CATEGORY:
            return "language", canonical_preserved
        return "skill", canonical_preserved.casefold().replace(" ", "_")
    cleaned = re.sub(r"[^a-z0-9+.#\-\s]", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return "skill", cleaned.replace(" ", "_") if cleaned else None


# Canonicalize a raw skill token to a lowercase-underscore canonical skill id.
def canonicalize_skill(raw: str, taxonomy: SkillTaxonomyLoader) -> str | None:
    kind, value = classify_skill_token(raw, taxonomy)
    if kind == "language":
        return None
    return value


# Month-name to number map for parsing dates like "Jan 2021" / "January 2021".
_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_NAME_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES) + r")\s+(\d{4})\b",
    re.IGNORECASE,
)


# Replace "Jan 2021" style tokens with "2021-01" so the numeric range regex can match.
def _replace_month_names(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{match.group(2)}-{_MONTH_NAMES[match.group(1).lower()]:02d}"

    return _MONTH_NAME_RE.sub(repl, text)


# Parse a single CV date token into ISO YYYY-MM (or YYYY), or None.
def parse_cv_date(token: str | None) -> str | None:
    if not token:
        return None
    raw = str(token).strip()
    if not raw or raw.lower() in {"present", "current", "now"}:
        return None
    normalized = _replace_month_names(raw)
    # YYYY-MM or YYYY/MM or YYYY.MM
    match = re.search(r"((?:19|20)\d{2})[./-](0?[1-9]|1[0-2])", normalized)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    # MM/YYYY
    match = re.search(r"\b(0?[1-9]|1[0-2])[/.-]((?:19|20)\d{2})\b", normalized)
    if match:
        return f"{match.group(2)}-{int(match.group(1)):02d}"
    # bare YYYY
    match = re.search(r"\b((?:19|20)\d{2})\b", normalized)
    if match:
        return match.group(1)
    return None


def as_list(value: Any) -> list[Any]:
    # Normalize arbitrary LLM outputs into list form.
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        items = [item.strip(" -\t") for item in re.split(r"[,\n;|/]+", value) if item.strip()]
        return items
    return [value]


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def to_clean_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(text.split())


def concat_text(left: Any, right: Any) -> str | None:
    left_text = to_clean_text(left)
    right_text = to_clean_text(right)
    if left_text and right_text:
        return f"{left_text} {right_text}".strip()
    return left_text or right_text


def extract_degree_from_text(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    # Ordered from most specific to broad to avoid early generic matches.
    patterns: list[tuple[str, str]] = [
        (r"\b(ph\.?\s?d|doctor\s+of\s+philosophy|doctoral?)\b", "PhD"),
        (r"\b(m\.?\s?phil|master\s+of\s+philosophy)\b", "MPhil"),
        (r"\b(mba)\b", "MBA"),
        (r"\b(m\.?\s?sc|m\.?\s?a|m\.?\s?eng|master(?:'s)?(?:\s+degree)?)\b", "Master"),
        (r"\b(b\.?\s?sc|b\.?\s?a|b\.?\s?eng|bachelor(?:'s)?(?:\s+degree)?)\b", "Bachelor"),
        (r"\b(associate(?:'s)?(?:\s+degree)?)\b", "Associate"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return label
    return None


def extract_major_from_text(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    # Prefer a major introduced by "in" (e.g. "BSc in Computer Science").
    # Fall back to the last "of" phrase so degree-name "of" matches such as
    # "Master of Engineering" do not shadow the real major.
    match = re.search(r"\bin\s+([A-Za-z][A-Za-z\s&/-]{2,60})", normalized, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip(" .,-;:")
        return candidate if len(candidate) >= 3 else None
    of_matches = list(re.finditer(r"\bof\s+([A-Za-z][A-Za-z\s&/-]{2,60})", normalized, flags=re.IGNORECASE))
    if of_matches:
        candidate = of_matches[-1].group(1).strip(" .,-;:")
        return candidate if len(candidate) >= 3 else None
    return None


def extract_institution_from_text(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    pattern = (
        r"\b([A-Z][A-Za-z&'., -]{2,}"
        r"(?:University|College|Institute|School|Polytechnic|Academy)"
        r"(?:[A-Za-z&'., -]{0,40})?)\b"
    )
    match = re.search(pattern, normalized)
    if match:
        return match.group(1).strip(" .,-;:")
    return None


def looks_like_date_location_line(text: str | None) -> bool:
    if not text:
        return False
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    date_range = re.search(
        r"^\d{1,2}[/-](?:19|20)\d{2}\s*(?:-|–|—|to)\s*\d{1,2}[/-](?:19|20)\d{2}(?:\s+[A-Za-z][A-Za-z .'-]{1,40})?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if date_range:
        return True
    year_range = re.search(
        r"^(?:19|20)\d{2}\s*(?:-|–|—|to)\s*(?:19|20)\d{2}(?:\s+[A-Za-z][A-Za-z .'-]{1,40})?$",
        normalized,
        flags=re.IGNORECASE,
    )
    return bool(year_range)


def normalize_education_school(text: str | None, degree: str | None, major: str | None) -> str | None:
    if not text:
        return major
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    institution = extract_institution_from_text(normalized)
    if institution:
        return institution
    # If the row is degree-centric, keep the major as the primary school-like value.
    if degree and major:
        return major
    if major and not looks_like_date_location_line(normalized):
        return major
    return normalized


def is_valid_education_row(row: dict[str, Any]) -> bool:
    school = str(row.get("school") or "").strip()
    degree = str(row.get("degree") or "").strip()
    major = str(row.get("major") or "").strip()
    if not school and not degree and not major:
        return False
    if school and looks_like_date_location_line(school) and not degree and not major:
        return False
    return True


def extract_year_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", str(text))
    return match.group(0) if match else None


def extract_date_range_from_text(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    normalized = _replace_month_names(re.sub(r"\s+", " ", str(text)).strip())
    # Accept common CV date ranges: 2021-01 - 2023-06, 2020 to Present, 2019–2021,
    # 01/2021 - 03/2024, Jan 2021 - Jan 2024 (month names normalized above).
    match = re.search(
        r"((?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?|(?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2})"
        r"\s*(?:-|–|—|to)\s*"
        r"((?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?|(?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}|present|current|now)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    start_raw = match.group(1)
    end_raw = match.group(2)
    start_iso = parse_cv_date(start_raw)
    if end_raw.lower() in {"present", "current", "now"}:
        return start_iso, "Present"
    return start_iso, parse_cv_date(end_raw)


def combine_period(start_date: str | None, end_date: str | None) -> str | None:
    if start_date and end_date:
        return f"{start_date} - {end_date}"
    if start_date:
        return start_date
    if end_date:
        return end_date
    return None


def extract_company_from_text(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    patterns = [
        # Allow spaces so multi-word company names ("ACME Corp") are captured;
        # the lookahead still stops the match right before the year range.
        r"\bat\s+([A-Z][A-Za-z0-9&.,'()/\s-]{1,80}?)(?=\s+(?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?\b|$)",
        r"\bwith\s+([A-Z][A-Za-z0-9&.,'()/\s-]{1,80}?)(?=\s+(?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?\b|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1).strip(" .,-;:")
    return None


def extract_title_from_text(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    title_patterns = [
        r"\b(senior|lead|principal|staff)?\s*(software|backend|frontend|full[- ]stack|data|machine learning|research|devops|product)?\s*(engineer|developer|scientist|manager|analyst|consultant|intern)\b",
        r"\b(research assistant|teaching assistant|project manager|product manager)\b",
    ]
    for pattern in title_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None


def normalize_skill_items(
    value: Any,
    *,
    source: str = "skills_section",
    taxonomy: SkillTaxonomyLoader | None = None,
) -> list[dict[str, Any]]:
    # Build structured skill objects with canonical ids; language tokens are dropped here
    # and routed to normalize_language_items by the caller.
    loader = taxonomy or _default_taxonomy()
    normalized: list[dict[str, Any]] = []
    seen_canonical: set[str] = set()
    for item in as_list(value):
        if isinstance(item, dict):
            # Accept common key variants from different model outputs.
            raw = item.get("name") or item.get("skill") or item.get("technology") or item.get("value")
            item_source = item.get("source") or source
        else:
            raw = item
            item_source = source
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        kind, canonical = classify_skill_token(text, loader)
        if kind == "language" or not canonical:
            continue
        if canonical in seen_canonical:
            continue
        seen_canonical.add(canonical)
        normalized.append(
            {
                "raw": text,
                "canonical_skill": canonical,
                "skill_id": f"{canonical}_{len(normalized) + 1}",
                "source": item_source,
            }
        )
    return normalized


# Normalize an explicit languages field from the LLM payload into language objects.
def normalize_language_items(
    value: Any,
    *,
    taxonomy: SkillTaxonomyLoader | None = None,
) -> list[dict[str, Any]]:
    loader = taxonomy or _default_taxonomy()
    languages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in as_list(value):
        if isinstance(item, dict):
            name = item.get("language") or item.get("name") or item.get("value")
            level = item.get("level") or item.get("proficiency")
        else:
            name = item
            level = None
        if not name:
            continue
        display = _resolve_language_display(str(name), loader)
        if not display or display.casefold() in seen:
            continue
        seen.add(display.casefold())
        languages.append({"language": display, "level": _normalize_language_level(level)})
    return languages


# Map a raw language token to the taxonomy display name, or keep it when unknown.
def _resolve_language_display(token: str, taxonomy: SkillTaxonomyLoader) -> str | None:
    text = token.strip()
    if not text:
        return None
    canonical_preserved = taxonomy.normalize_skill(text)
    if canonical_preserved:
        node = taxonomy.nodes.get(canonical_preserved)
        if node and node.category.strip().casefold() == _LANGUAGE_CATEGORY:
            return canonical_preserved
    return text


# Coerce a free-form language level into the JD enum (basic|business|fluent|native).
def _normalize_language_level(level: Any) -> str | None:
    if level is None:
        return None
    text = str(level).strip().casefold()
    if not text:
        return None
    if text in {"native", "mother tongue", "母语", "母語"}:
        return "native"
    if text in {"fluent", "fluency", "proficient", "精通", "流利"}:
        return "fluent"
    if text in {"business", "working", "商务", "商務"}:
        return "business"
    if text in {"basic", "beginner", "elementary", "基本"}:
        return "basic"
    return None


# Detect language tokens embedded in a raw skills list (e.g. ["English", "Python"]).
def extract_languages_from_skills(
    value: Any,
    *,
    taxonomy: SkillTaxonomyLoader | None = None,
) -> list[dict[str, Any]]:
    loader = taxonomy or _default_taxonomy()
    languages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in as_list(value):
        raw = item.get("name") if isinstance(item, dict) else item
        if not raw:
            continue
        kind, display = classify_skill_token(str(raw), loader)
        if kind != "language" or not display:
            continue
        key = display.casefold()
        if key in seen:
            continue
        seen.add(key)
        languages.append({"language": display, "level": None})
    return languages


def normalize_education_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(value):
        if isinstance(item, dict):
            school = item.get("school") or item.get("institution") or item.get("university") or item.get("college")
            degree = item.get("degree") or item.get("qualification") or item.get("education_level")
            major = item.get("major") or item.get("field") or item.get("field_of_study")
            period = item.get("period") or item.get("year") or item.get("graduation_year")
            start_date = item.get("start_date") or item.get("start")
            end_date = item.get("end_date") or item.get("end")
            graduation_date = item.get("graduation_date")
            if not degree:
                # Only infer from local context when the explicit degree field is missing.
                context = " ".join(
                    str(part).strip()
                    for part in (school, major, item.get("description"), item.get("summary"))
                    if part not in (None, "")
                )
                degree = extract_degree_from_text(context)
            if not period:
                context = " ".join(
                    str(part).strip()
                    for part in (school, major, item.get("description"), item.get("summary"))
                    if part not in (None, "")
                )
                period = extract_year_from_text(context)
            school = normalize_education_school(str(school).strip() if school else None, degree, major)
            # Normalize any period text into ISO start/end so the scorer can compute durations.
            if period and not (start_date or end_date):
                start_date, end_date = extract_date_range_from_text(period)
            if not graduation_date:
                graduation_date = end_date or (period if period and "-" not in str(period) else None)
            rows.append(
                {
                    "school": school,
                    "degree": degree,
                    "degree_level": degree_to_level(degree),
                    "major": major,
                    "period": period,
                    "start_date": start_date,
                    "end_date": end_date,
                    "graduation_date": graduation_date,
                }
            )
        else:
            text = str(item).strip()
            if text:
                # String items usually come from compressed list outputs; split semantics here.
                if looks_like_date_location_line(text):
                    # Skip timeline-only rows like "01/2008 - 01/2012 London".
                    continue
                degree = extract_degree_from_text(text)
                major = extract_major_from_text(text)
                school = normalize_education_school(text, degree, major)
                period = extract_year_from_text(text)
                start_date, end_date = extract_date_range_from_text(text)
                rows.append(
                    {
                        "school": school,
                        "degree": degree,
                        "degree_level": degree_to_level(degree),
                        "major": major,
                        "period": period,
                        "start_date": start_date,
                        "end_date": end_date,
                        "graduation_date": end_date or period,
                    }
                )
    rows = [
        row
        for row in rows
        if any(entry_value not in (None, "") for entry_value in row.values()) and is_valid_education_row(row)
    ]
    return merge_fragmented_education_rows(rows)


def normalize_experience_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(value):
        if isinstance(item, dict):
            company = item.get("company") or item.get("employer") or item.get("organization")
            job_title = item.get("job_title") or item.get("title") or item.get("role") or item.get("position")
            start_date = item.get("start_date") or item.get("start") or item.get("from")
            end_date = item.get("end_date") or item.get("end") or item.get("to") or item.get("until")
            period = item.get("period")
            description = item.get("description") or item.get("summary") or item.get("responsibilities")
            skills_used = item.get("skills_used") or item.get("skills") or []
            context = " ".join(
                str(part).strip()
                for part in (description, item.get("company"), item.get("role"), item.get("position"), item.get("duration"))
                if part not in (None, "")
            )
            if not company:
                company = extract_company_from_text(context)
            if not job_title:
                job_title = extract_title_from_text(context)
            if not period and not start_date and not end_date:
                start_date, end_date = extract_date_range_from_text(context)
            if period and not start_date and not end_date:
                start_date, end_date = extract_date_range_from_text(period)
            if not period:
                period = combine_period(start_date, end_date)
            is_current = _is_current_marker(end_date)
            rows.append(
                {
                    "company": company,
                    "job_title": job_title,
                    "period": period,
                    "start_date": start_date,
                    "end_date": end_date,
                    "is_current": is_current,
                    "description": description,
                    "skills_used": _canonicalize_skills_used(skills_used),
                }
            )
        else:
            text = str(item).strip()
            if text:
                # Keep raw line in description so we do not lose information.
                start_date, end_date = extract_date_range_from_text(text)
                rows.append(
                    {
                        "company": extract_company_from_text(text),
                        "job_title": extract_title_from_text(text),
                        "period": combine_period(start_date, end_date),
                        "start_date": start_date,
                        "end_date": end_date,
                        "is_current": _is_current_marker(end_date),
                        "description": text,
                        "skills_used": [],
                    }
                )
    rows = [row for row in rows if any(entry_value not in (None, "", []) for entry_value in row.values())]
    return merge_fragmented_experience_rows(rows)


# Return True when an end-date marker indicates the job is still ongoing.
def _is_current_marker(end_date: Any) -> bool:
    if end_date is None:
        return False
    return str(end_date).strip().lower() in {"present", "current", "now"}


# Canonicalize a list (or free-text description) of skills used in one job.
def _canonicalize_skills_used(value: Any) -> list[str]:
    taxonomy = _default_taxonomy()
    tokens: list[str] = []
    if isinstance(value, list):
        tokens = [str(v) for v in value if v]
    elif isinstance(value, str):
        tokens = [piece.strip() for piece in re.split(r"[,\u3001;/|]+", value) if piece.strip()]
    canonicals: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        canonical = canonicalize_skill(token, taxonomy)
        if canonical and canonical not in seen:
            seen.add(canonical)
            canonicals.append(canonical)
    return canonicals


def normalize_publication_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(value):
        if isinstance(item, dict):
            rows.append(
                {
                    "title": item.get("title") or item.get("name"),
                    "journal": item.get("journal") or item.get("venue") or item.get("publisher"),
                    "year": item.get("year") or item.get("published_year"),
                }
            )
        else:
            text = str(item).strip()
            if text:
                rows.append({"title": text, "journal": None, "year": None})
    return [row for row in rows if any(entry_value not in (None, "") for entry_value in row.values())]


# Normalize a location payload (string or object) into a stable location object.
def normalize_location(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        raw = value.get("raw") or value.get("full") or value.get("address")
        country = value.get("country")
        city = value.get("city")
        region = value.get("region") or value.get("state")
    else:
        raw = str(value).strip()
        country = None
        city = None
        region = None
    if not raw and not country and not city:
        return None
    return {
        "raw": to_clean_text(raw),
        "country": to_clean_text(country),
        "city": to_clean_text(city),
        "region": to_clean_text(region),
    }


# Normalize a work authorization payload into a stable status enum + raw text.
def normalize_work_authorization(value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "unknown", "raw": None}
    if isinstance(value, dict):
        status = value.get("status") or value.get("type")
        raw = value.get("raw") or value.get("note") or value.get("detail")
    else:
        raw = str(value).strip()
        status = None
    return {
        "status": _normalize_work_auth_status(status, raw),
        "raw": to_clean_text(raw),
    }


# Coerce a free-form work authorization status into a stable enum.
def _normalize_work_auth_status(status: Any, raw: str | None) -> str:
    if status:
        text = str(status).strip().casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "citizen": "citizen",
            "permanent_resident": "permanent_resident",
            "pr": "permanent_resident",
            "green_card": "permanent_resident",
            "has_work_permit": "has_work_permit",
            "work_permit": "has_work_permit",
            "requires_sponsorship": "requires_sponsorship",
            "need_sponsorship": "requires_sponsorship",
            "needs_sponsorship": "requires_sponsorship",
            "requires_visa_sponsorship": "requires_sponsorship",
            "unknown": "unknown",
        }
        if text in aliases:
            return aliases[text]
    # Fall back to scanning the raw text for sponsorship cues.
    lowered = (raw or "").lower()
    if "require" in lowered and "sponsorship" in lowered:
        return "requires_sponsorship"
    if "need" in lowered and "visa" in lowered:
        return "requires_sponsorship"
    if "authorized to work" in lowered or "work permit" in lowered or "eligible to work" in lowered:
        return "has_work_permit"
    if "permanent resident" in lowered or "green card" in lowered:
        return "permanent_resident"
    if "citizen" in lowered:
        return "citizen"
    return "unknown"


# Normalize a certifications payload into a list of certification objects.
def normalize_certification_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(value):
        if isinstance(item, dict):
            name = item.get("name") or item.get("certification") or item.get("title")
            issuer = item.get("issuer") or item.get("provider") or item.get("organization")
            year = item.get("year") or item.get("date")
        else:
            name = item
            issuer = None
            year = None
        if name is None:
            continue
        text = str(name).strip()
        if not text:
            continue
        rows.append(
            {
                "name": text,
                "issuer": to_clean_text(issuer),
                "year": to_clean_text(year),
            }
        )
    return [row for row in rows if any(entry_value not in (None, "") for entry_value in row.values())]


# Normalize a projects payload into a list of project objects with skills_used.
def normalize_project_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(value):
        if isinstance(item, dict):
            name = item.get("name") or item.get("title")
            description = item.get("description") or item.get("summary")
            period = item.get("period")
            skills_used = item.get("skills_used") or item.get("skills") or []
        else:
            name = None
            description = str(item).strip()
            period = None
            skills_used = []
        if not name and not description:
            continue
        rows.append(
            {
                "name": to_clean_text(name),
                "description": to_clean_text(description),
                "period": to_clean_text(period),
                "skills_used": _canonicalize_skills_used(skills_used),
            }
        )
    return [row for row in rows if any(entry_value not in (None, "") for entry_value in row.values())]


# Normalize a summary/profile payload into a single short string.
def normalize_summary(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Collapse to a single line and cap length to keep it a short profile blurb.
    collapsed = " ".join(text.split())
    return collapsed[:600]


def normalize_schema(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    def pick_first(*keys: str) -> Any:
        # Models can rename keys across runs; we accept the first non-empty alias.
        for key in keys:
            if key in payload and payload.get(key) not in (None, ""):
                return payload.get(key)
        return None

    taxonomy = _default_taxonomy()
    raw_skills = pick_first("skills", "technical_skills", "tech_skills", "skill_set")
    raw_languages = pick_first("languages", "language", "language_skills", "spoken_languages")

    # Skills are structured objects; language tokens mixed into skills are routed out.
    skills = normalize_skill_items(raw_skills, source="skills_section", taxonomy=taxonomy)
    # Languages come from an explicit languages field plus any tokens detected in skills.
    languages = normalize_language_items(raw_languages, taxonomy=taxonomy)
    languages = _merge_languages(
        languages, extract_languages_from_skills(raw_skills, taxonomy=taxonomy)
    )

    return {
        "name": payload.get("name"),
        "email": payload.get("email"),
        "phone": payload.get("phone"),
        "location": normalize_location(pick_first("location", "address", "based_in", "residence")),
        "work_authorization": normalize_work_authorization(
            pick_first("work_authorization", "visa_status", "work_eligibility", "authorization")
        ),
        "summary": normalize_summary(
            pick_first("summary", "profile", "objective", "about", "professional_summary")
        ),
        "education": normalize_education_items(
            pick_first("education", "educations", "academic_background", "academics")
        ),
        "experience": normalize_experience_items(
            pick_first("experience", "experiences", "work_experience", "employment_history")
        ),
        "skills": skills,
        "languages": languages,
        "certifications": normalize_certification_items(
            pick_first("certifications", "certification", "certs", "licenses")
        ),
        "projects": normalize_project_items(
            pick_first("projects", "project", "personal_projects", "side_projects")
        ),
        "publications": normalize_publication_items(
            pick_first("publications", "publication", "papers", "research_publications")
        ),
    }


# Merge two language lists, keeping the first level seen per language.
def _merge_languages(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in left + right:
        key = str(item.get("language") or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


# Merge two skills_used canonical lists preserving order and uniqueness.
def _merge_skills_used(left: list[str] | None, right: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in (left or []) + (right or []):
        if value and value not in seen:
            seen.add(value)
            merged.append(value)
    return merged


def merge_fragmented_experience_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_item in rows:
        item = {
            "company": to_clean_text(raw_item.get("company")),
            "job_title": to_clean_text(raw_item.get("job_title")),
            "period": to_clean_text(raw_item.get("period")),
            "start_date": to_clean_text(raw_item.get("start_date")),
            "end_date": to_clean_text(raw_item.get("end_date")),
            "is_current": raw_item.get("is_current"),
            "description": to_clean_text(raw_item.get("description")),
            "skills_used": list(raw_item.get("skills_used") or []),
        }
        has_company = bool(item.get("company"))
        has_description = bool(item.get("description"))
        has_period = bool(item.get("period"))
        has_job_title = bool(item.get("job_title"))

        if has_company:
            if current:
                merged.append(current)
            current = dict(item)
            continue

        if current and has_description:
            current["description"] = concat_text(current.get("description"), item["description"])
            if has_job_title and not current.get("job_title"):
                current["job_title"] = item["job_title"]
            if has_period and not current.get("period"):
                current["period"] = item["period"]
                current["start_date"] = current["start_date"] or item.get("start_date")
                current["end_date"] = current["end_date"] or item.get("end_date")
            if item.get("skills_used"):
                current["skills_used"] = _merge_skills_used(current.get("skills_used"), item["skills_used"])
            continue

        if current and has_period and not current.get("period"):
            current["period"] = item["period"]
            current["start_date"] = current["start_date"] or item.get("start_date")
            current["end_date"] = current["end_date"] or item.get("end_date")
            if has_job_title and not current.get("job_title"):
                current["job_title"] = item["job_title"]
            continue

        if current:
            current["description"] = concat_text(current.get("description"), item.get("description"))
            if not current.get("job_title") and has_job_title:
                current["job_title"] = item["job_title"]
            if not current.get("period") and has_period:
                current["period"] = item["period"]
                current["start_date"] = current["start_date"] or item.get("start_date")
                current["end_date"] = current["end_date"] or item.get("end_date")
            if item.get("skills_used"):
                current["skills_used"] = _merge_skills_used(current.get("skills_used"), item["skills_used"])
        else:
            merged.append(item)

    if current:
        merged.append(current)

    return [
        item
        for item in merged
        if item.get("company") or item.get("job_title") or item.get("description")
    ]


def merge_fragmented_education_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    merged: list[dict[str, Any]] = []
    for raw_item in rows:
        item = {
            "school": to_clean_text(raw_item.get("school")),
            "degree": to_clean_text(raw_item.get("degree")),
            "degree_level": to_clean_text(raw_item.get("degree_level")),
            "major": to_clean_text(raw_item.get("major")),
            "period": to_clean_text(raw_item.get("period")),
            "start_date": to_clean_text(raw_item.get("start_date")),
            "end_date": to_clean_text(raw_item.get("end_date")),
            "graduation_date": to_clean_text(raw_item.get("graduation_date")),
        }
        # A school-only fragment (no degree/major) that is not a standalone
        # institution belongs to the previous degree row: use it as the school
        # (e.g. "MSc in Computer Science, MIT 2020" -> school "MIT 2020").
        is_school_fragment = bool(item.get("school")) and not item.get("degree") and not item.get("major")
        if is_school_fragment and merged:
            previous = merged[-1]
            if previous.get("degree") and not extract_institution_from_text(item["school"]):
                previous["school"] = item["school"]
                if item.get("period") and not previous.get("period"):
                    previous["period"] = item["period"]
                continue
        # Otherwise merge rows sharing the same (school, degree) key.
        key = (
            (item.get("school") or "").casefold(),
            (item.get("degree") or "").casefold(),
        )
        if not key[0] and not key[1]:
            merged.append(item)
            continue
        existing = next(
            (
                row
                for row in merged
                if (row.get("school") or "").casefold() == key[0]
                and (row.get("degree") or "").casefold() == key[1]
            ),
            None,
        )
        if existing is not None:
            for field in (
                "major", "period", "school", "degree", "degree_level",
                "start_date", "end_date", "graduation_date",
            ):
                if item.get(field) and not existing.get(field):
                    existing[field] = item[field]
            continue
        merged.append(item)
    return merged


def compress_cv_text(*, raw_text: str, max_chars: int) -> str:
    lines = [" ".join(line.split()) for line in raw_text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    selected: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(line)

    joined = "\n".join(selected)
    if len(joined) <= max_chars:
        return joined

    priority_pattern = re.compile(
        r"(experience|employment|work history|education|university|college|skills|projects|publications|email|phone|@|\b\d{4}\b)",
        re.IGNORECASE,
    )
    priority_lines = [line for line in selected if priority_pattern.search(line)]
    fallback_lines = [line for line in selected if line not in priority_lines]
    ordered = priority_lines + fallback_lines

    result: list[str] = []
    current_len = 0
    for line in ordered:
        candidate_len = len(line) + (1 if result else 0)
        if current_len + candidate_len > max_chars:
            continue
        result.append(line)
        current_len += candidate_len
        if current_len >= max_chars:
            break
    return "\n".join(result)


def build_compressed_prompt(*, raw_text: str, jd_text: str | None, max_chars: int = 12000) -> str:
    compressed_cv_text = compress_cv_text(raw_text=raw_text, max_chars=max_chars)
    segments = [
        "Task: Parse the CV text below into the target JSON schema from system prompt.",
        "Rules: Use explicit facts only. Merge one job into one experience object. Merge one degree into one education object.",
        f"CV Text (compressed):\n{compressed_cv_text}",
    ]
    if jd_text:
        compressed_jd_text = compress_cv_text(raw_text=jd_text, max_chars=3000)
        segments.append(f"JD Context (compressed):\n{compressed_jd_text}")
    segments.append("Return valid JSON only.")
    return "\n\n".join(segments)

# Extracts identity fields with the shared local PII detector.
def extract_contact_hints(
    raw_text: str,
    extra_names: list[str] | None = None,
    extra_sensitive_values: list[str] | None = None,
) -> dict[str, str | None]:
    return extract_contact_hints_local(raw_text, extra_names, extra_sensitive_values)


def digits_only(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value if ch.isdigit())


def prefer_phone_format(existing: str, hinted: str) -> str:
    existing_digits = digits_only(existing)
    hinted_digits = digits_only(hinted)
    if existing_digits and existing_digits == hinted_digits:
        # Prefer the version that preserves brackets from original CV text.
        if "(" in hinted or ")" in hinted:
            return hinted
        return existing
    return existing


def merge_contact_hints(structured: dict[str, Any], hints: dict[str, str | None]) -> dict[str, Any]:
    merged = dict(structured)
    if not merged.get("email") and hints.get("email"):
        merged["email"] = hints["email"]
    if hints.get("phone"):
        if not merged.get("phone"):
            merged["phone"] = hints["phone"]
        else:
            merged["phone"] = prefer_phone_format(str(merged["phone"]), hints["phone"])
    if not merged.get("name") and hints.get("name"):
        merged["name"] = hints["name"]
    return merged


def extract_section_lines(raw_text: str, headers: tuple[str, ...], stop_headers: tuple[str, ...]) -> list[str]:
    # Lightweight section slicer: collect lines after target header until next section.
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    header_pattern = re.compile(r"^[A-Za-z][A-Za-z\s]{1,40}:?$")
    active = False
    result: list[str] = []
    for line in lines:
        line_lower = line.casefold().rstrip(":")
        if any(line_lower == header.casefold() for header in headers):
            active = True
            continue

        if active:
            # Stop when next all-caps/simple title-like section begins.
            if any(line_lower == header.casefold() for header in stop_headers):
                break
            if header_pattern.match(line) and len(result) >= 2:
                break
            result.append(line)
            if len(result) >= 10:
                break

    return result


def extract_skills_fallback(raw_text: str) -> list[str]:
    # Strategy: union of known-token scan + explicit Skills section parsing.
    matches = [token for token in re.findall(r"[A-Za-z0-9.+#-]{2,}", raw_text) if token.casefold() in KNOWN_SKILLS]
    section_lines = extract_section_lines(
        raw_text,
        ("skills", "technical skills", "tech stack"),
        ("education", "experience", "projects", "publications", "languages", "certifications"),
    )
    section_tokens: list[str] = []
    for line in section_lines:
        section_tokens.extend(
            piece.strip()
            for piece in re.split(r"[,\u3001;/|]+", line)
            if piece.strip()
        )
    return unique_keep_order(matches + section_tokens)


def extract_education_fallback(raw_text: str) -> list[dict[str, Any]]:
    # Keep education lines intact and extract degree/period conservatively.
    lines = extract_section_lines(
        raw_text,
        ("education", "academic background", "academics"),
        ("experience", "skills", "projects", "publications", "certifications"),
    )
    output: list[dict[str, Any]] = []
    for line in lines:
        degree = extract_degree_from_text(line)
        period = extract_year_from_text(line)
        start_date, end_date = extract_date_range_from_text(line)
        output.append(
            {
                "school": line,
                "degree": degree,
                "degree_level": degree_to_level(degree),
                "major": extract_major_from_text(line),
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "graduation_date": end_date or period,
            }
        )
    return output


def extract_experience_fallback(raw_text: str) -> list[dict[str, Any]]:
    # Preserve chronology text even if company/job_title cannot be reliably split.
    lines = extract_section_lines(
        raw_text,
        ("experience", "work experience", "employment history"),
        ("education", "skills", "projects", "publications", "certifications"),
    )
    output: list[dict[str, Any]] = []
    for line in lines:
        start_date, end_date = extract_date_range_from_text(line)
        output.append(
            {
                "company": None,
                "job_title": None,
                "period": combine_period(start_date, end_date),
                "start_date": start_date,
                "end_date": end_date,
                "is_current": _is_current_marker(end_date),
                "description": line,
                "skills_used": [],
            }
        )
    return output


def extract_publications_fallback(raw_text: str) -> list[dict[str, Any]]:
    # Publication details vary widely; keep title text first, then optional year.
    lines = extract_section_lines(
        raw_text,
        ("publications", "publication", "research", "papers"),
        ("education", "experience", "skills", "projects", "certifications"),
    )
    output: list[dict[str, Any]] = []
    for line in lines:
        year_match = re.search(r"(19|20)\d{2}", line)
        output.append(
            {
                "title": line,
                "journal": None,
                "year": year_match.group(0) if year_match else None,
            }
        )
    return output


# Extract a location from a "Location" header line when the LLM omitted it.
def extract_location_fallback(raw_text: str) -> dict[str, Any] | None:
    lines = extract_section_lines(
        raw_text,
        ("location", "address", "based in", "residence"),
        ("experience", "education", "skills", "projects", "publications", "certifications"),
    )
    for line in lines[:1]:
        return normalize_location(line)
    return None


# Infer work authorization status from sponsorship/visa cues in the CV text.
def extract_work_authorization_fallback(raw_text: str) -> dict[str, Any]:
    lowered = raw_text.lower()
    status = _normalize_work_auth_status(None, lowered)
    return {"status": status, "raw": None}


# Extract certification entries from a Certifications/Licenses section.
def extract_certifications_fallback(raw_text: str) -> list[dict[str, Any]]:
    lines = extract_section_lines(
        raw_text,
        ("certifications", "certification", "licenses", "licences", "credentials"),
        ("education", "experience", "skills", "projects", "publications"),
    )
    output: list[dict[str, Any]] = []
    for line in lines:
        year_match = re.search(r"(19|20)\d{2}", line)
        output.append(
            {
                "name": line,
                "issuer": None,
                "year": year_match.group(0) if year_match else None,
            }
        )
    return output


# Extract project entries from a Projects section.
def extract_projects_fallback(raw_text: str) -> list[dict[str, Any]]:
    lines = extract_section_lines(
        raw_text,
        ("projects", "project", "personal projects", "side projects", "selected projects"),
        ("education", "experience", "skills", "publications", "certifications"),
    )
    output: list[dict[str, Any]] = []
    for line in lines:
        start_date, end_date = extract_date_range_from_text(line)
        output.append(
            {
                "name": None,
                "description": line,
                "period": combine_period(start_date, end_date),
                "skills_used": [],
            }
        )
    return output


# Extract a short summary from a Summary/Profile/Objective section.
def extract_summary_fallback(raw_text: str) -> str | None:
    lines = extract_section_lines(
        raw_text,
        ("summary", "profile", "professional summary", "objective", "about", "career objective"),
        ("experience", "education", "skills", "projects", "publications", "certifications"),
    )
    if not lines:
        return None
    return normalize_summary(" ".join(lines))


def apply_content_fallback(raw_text: str, structured: dict[str, Any]) -> dict[str, Any]:
    # Fill empty arrays from deterministic text heuristics only when LLM left them blank.
    enriched = dict(structured)
    if not enriched.get("skills") and not enriched.get("languages"):
        # Skills fallback returns structured objects; languages detected from the same tokens.
        fallback_skills = extract_skills_fallback(raw_text)
        enriched["skills"] = normalize_skill_items(fallback_skills, source="fallback")
        enriched["languages"] = extract_languages_from_skills(fallback_skills)
    elif not enriched.get("skills"):
        enriched["skills"] = normalize_skill_items(extract_skills_fallback(raw_text), source="fallback")
    elif not enriched.get("languages"):
        enriched["languages"] = extract_languages_from_skills(extract_skills_fallback(raw_text))
    if not enriched.get("education"):
        enriched["education"] = extract_education_fallback(raw_text)
    if not enriched.get("experience"):
        enriched["experience"] = extract_experience_fallback(raw_text)
    if not enriched.get("publications"):
        enriched["publications"] = extract_publications_fallback(raw_text)
    if not enriched.get("certifications"):
        enriched["certifications"] = extract_certifications_fallback(raw_text)
    if not enriched.get("projects"):
        enriched["projects"] = extract_projects_fallback(raw_text)
    if not enriched.get("summary"):
        enriched["summary"] = extract_summary_fallback(raw_text)
    if not enriched.get("location"):
        enriched["location"] = extract_location_fallback(raw_text)
    if not enriched.get("work_authorization"):
        enriched["work_authorization"] = extract_work_authorization_fallback(raw_text)
    return enriched
