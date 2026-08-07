from __future__ import annotations

import re
from typing import Any

from app.services.parser.prompts import KNOWN_SKILLS


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
    # Heuristic: capture phrase after "in/of", e.g. "Master in Computer Science".
    match = re.search(r"\b(?:in|of)\s+([A-Za-z][A-Za-z\s&/-]{2,60})", normalized, flags=re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip(" .,-;:")
    if len(candidate) < 3:
        return None
    return candidate


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
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    # Accept common CV date ranges: 2021-01 - 2023-06, 2020 to Present, 2019–2021.
    match = re.search(
        r"((?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?)\s*(?:-|–|—|to)\s*((?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?|present|current|now)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    start_raw = match.group(1)
    end_raw = match.group(2)
    end_value = "Present" if end_raw.lower() in {"present", "current", "now"} else end_raw
    return start_raw, end_value


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
        r"\bat\s+([A-Z][A-Za-z0-9&.,'()/-]{1,80}?)(?=\s+(?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?\b|$)",
        r"\bwith\s+([A-Z][A-Za-z0-9&.,'()/-]{1,80}?)(?=\s+(?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2]))?\b|$)",
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


def normalize_skill_items(value: Any) -> list[str]:
    normalized: list[str] = []
    for item in as_list(value):
        if isinstance(item, dict):
            # Accept common key variants from different model outputs.
            raw = item.get("name") or item.get("skill") or item.get("technology") or item.get("value")
        else:
            raw = item
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        normalized.append(text)
    return unique_keep_order(normalized)


def normalize_education_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in as_list(value):
        if isinstance(item, dict):
            school = item.get("school") or item.get("institution") or item.get("university") or item.get("college")
            degree = item.get("degree") or item.get("qualification") or item.get("education_level")
            major = item.get("major") or item.get("field") or item.get("field_of_study")
            period = item.get("period") or item.get("year") or item.get("graduation_year")
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
            rows.append(
                {
                    "school": school,
                    "degree": degree,
                    "major": major,
                    "period": period,
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
                rows.append(
                    {
                        "school": school,
                        "degree": degree,
                        "major": major,
                        "period": extract_year_from_text(text),
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
            if not period:
                period = combine_period(start_date, end_date)
            rows.append(
                {
                    "company": company,
                    "job_title": job_title,
                    "period": period,
                    "description": description,
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
                        "description": text,
                    }
                )
    rows = [row for row in rows if any(entry_value not in (None, "") for entry_value in row.values())]
    return merge_fragmented_experience_rows(rows)


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


def normalize_schema(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    def pick_first(*keys: str) -> Any:
        # Models can rename keys across runs; we accept the first non-empty alias.
        for key in keys:
            if key in payload and payload.get(key) not in (None, ""):
                return payload.get(key)
        return None

    return {
        "name": payload.get("name"),
        "email": payload.get("email"),
        "phone": payload.get("phone"),
        "education": normalize_education_items(
            pick_first("education", "educations", "academic_background", "academics")
        ),
        "experience": normalize_experience_items(
            pick_first("experience", "experiences", "work_experience", "employment_history")
        ),
        "skills": normalize_skill_items(
            pick_first("skills", "technical_skills", "tech_skills", "skill_set")
        ),
        "publications": normalize_publication_items(
            pick_first("publications", "publication", "papers", "research_publications")
        ),
    }


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
            "description": to_clean_text(raw_item.get("description")),
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
            continue

        if current and has_period and not current.get("period"):
            current["period"] = item["period"]
            if has_job_title and not current.get("job_title"):
                current["job_title"] = item["job_title"]
            continue

        if current:
            current["description"] = concat_text(current.get("description"), item.get("description"))
            if not current.get("job_title") and has_job_title:
                current["job_title"] = item["job_title"]
            if not current.get("period") and has_period:
                current["period"] = item["period"]
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

    merged_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    pass_through: list[dict[str, Any]] = []

    for raw_item in rows:
        item = {
            "school": to_clean_text(raw_item.get("school")),
            "degree": to_clean_text(raw_item.get("degree")),
            "major": to_clean_text(raw_item.get("major")),
            "period": to_clean_text(raw_item.get("period")),
        }
        key = (
            (item.get("school") or "").casefold(),
            (item.get("degree") or "").casefold(),
        )
        if not key[0] and not key[1]:
            pass_through.append(item)
            continue
        if key in merged_by_key:
            existing = merged_by_key[key]
            for field in ("major", "period", "school", "degree"):
                if item.get(field) and not existing.get(field):
                    existing[field] = item[field]
        else:
            merged_by_key[key] = dict(item)

    return [*merged_by_key.values(), *pass_through]


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


def extract_contact_hints(raw_text: str) -> dict[str, str | None]:
    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", raw_text)
    phone_matches = re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", raw_text)
    phone = None
    for candidate in phone_matches:
        digit_count = sum(ch.isdigit() for ch in candidate)
        if digit_count >= 8:
            phone = candidate.strip()
            break

    name = None
    for raw_line in raw_text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        lower_line = line.lower()
        if "email" in lower_line or "phone" in lower_line or "resume" in lower_line or "curriculum vitae" in lower_line:
            continue
        if "@" in line or ":" in line:
            continue
        if len(line) > 64:
            continue
        token_count = len(line.split())
        if token_count > 8:
            continue
        name = line
        break

    return {
        "name": name,
        "email": email_match.group(0) if email_match else None,
        "phone": phone,
    }


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
        output.append(
            {
                "school": line,
                "degree": extract_degree_from_text(line),
                "major": extract_major_from_text(line),
                "period": extract_year_from_text(line),
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
        output.append(
            {
                "company": None,
                "job_title": None,
                "period": None,
                "description": line,
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


def apply_content_fallback(raw_text: str, structured: dict[str, Any]) -> dict[str, Any]:
    # Fill empty arrays from deterministic text heuristics only when LLM left them blank.
    enriched = dict(structured)
    if not enriched.get("skills"):
        enriched["skills"] = extract_skills_fallback(raw_text)
    if not enriched.get("education"):
        enriched["education"] = extract_education_fallback(raw_text)
    if not enriched.get("experience"):
        enriched["experience"] = extract_experience_fallback(raw_text)
    if not enriched.get("publications"):
        enriched["publications"] = extract_publications_fallback(raw_text)
    return enriched
