# Merges hybrid LLM CV refinement into a first-pass structured profile.
from __future__ import annotations

import re
from typing import Any

from cv_parser.helpers import (
    enrich_experience_from_declared_years,
    normalize_experience_items,
    normalize_schema,
    normalize_skill_items,
)


# Strip identity fields the refiner must never supply.
def normalize_refiner_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM JSON and drop any identity keys."""
    cleaned = {key: value for key, value in payload.items() if key not in ("name", "email", "phone")}
    return normalize_schema(cleaned)


# True when the first pass is missing jobs, dates, skills, or spoken languages.
def draft_needs_hybrid_pass(structured: dict[str, Any]) -> bool:
    experience = structured.get("experience") if isinstance(structured.get("experience"), list) else []
    if not experience:
        return True
    dated = sum(
        1
        for item in experience
        if isinstance(item, dict)
        and (str(item.get("start_date") or "").strip() or str(item.get("end_date") or "").strip())
    )
    # More than half the jobs have no dates.
    if dated * 2 < len(experience):
        return True
    skills = structured.get("skills") if isinstance(structured.get("skills"), list) else []
    if len(skills) < 2:
        return True
    languages = structured.get("languages") if isinstance(structured.get("languages"), list) else []
    return not languages


# Count experience rows that carry a parseable start_date.
def _dated_experience_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if isinstance(item, dict) and item.get("start_date"))


# Folds hyphens and underscores so "scikit-learn" matches the canonical "scikit_learn".
def _match_fold(text: str) -> str:
    folded = text.casefold().replace("_", " ").replace("-", " ")
    return " ".join(folded.split())


# True when a skill label is an explicit substring of the redacted CV text.
def _mentioned_in_cv(label: str, evidence_text: str) -> bool:
    needle = _match_fold(label)
    if not needle or not evidence_text.strip():
        return True
    return needle in _match_fold(evidence_text)


# Labels to try, preferring the original wording over the canonical id.
def _labels_for_mention(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return [str(item)]
    labels: list[str] = []
    for key in ("raw", "name", "display_name", "canonical_skill"):
        value = str(item.get(key) or "").strip()
        if value and value not in labels:
            labels.append(value)
    return labels


_SKILL_HEADERS = ("skills", "technical skills", "tech stack", "core competencies", "技能", "专业技能")
_EXPERIENCE_HEADERS = (
    "experience",
    "work experience",
    "professional experience",
    "employment",
    "工作经历",
    "工作經驗",
    "工作经验",
)
_PROJECT_HEADERS = ("projects", "selected projects", "项目", "项目经历", "项目经验")
_OTHER_HEADERS = ("education", "academic background", "学历", "教育背景", "publications", "certifications")


# Returns the lines under one heading, stopping at the next known heading.
def _section_block(raw_text: str, headers: tuple[str, ...], stop_headers: tuple[str, ...]) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]
    header_keys = {header.casefold() for header in headers}
    stop_keys = {header.casefold() for header in stop_headers}
    active = False
    collected: list[str] = []
    for line in lines:
        key = line.casefold().rstrip(":").strip()
        if key in header_keys:
            active = True
            continue
        if active and key in stop_keys:
            break
        if active:
            collected.append(line)
    return "\n".join(collected)


# Narrow skill evidence only after a skills heading is found. An Experience heading alone is not enough.
def skill_evidence_text(masked_text: str) -> str:
    skill_block = _section_block(
        masked_text,
        _SKILL_HEADERS,
        _EXPERIENCE_HEADERS + _PROJECT_HEADERS + _OTHER_HEADERS,
    )
    if not skill_block:
        return masked_text
    experience_block = _section_block(
        masked_text,
        _EXPERIENCE_HEADERS,
        _SKILL_HEADERS + _PROJECT_HEADERS + _OTHER_HEADERS,
    )
    project_block = _section_block(
        masked_text,
        _PROJECT_HEADERS,
        _SKILL_HEADERS + _EXPERIENCE_HEADERS + _OTHER_HEADERS,
    )
    return "\n".join(part for part in (skill_block, experience_block, project_block) if part)


# Drops skill labels that are outside the skills block and the job or project descriptions.
def retain_skill_mentions(structured: dict[str, Any], masked_text: str) -> dict[str, Any]:
    if not masked_text.strip():
        return structured
    updated = dict(structured)
    corpus = skill_evidence_text(masked_text)
    skills = updated.get("skills") if isinstance(updated.get("skills"), list) else []
    updated["skills"] = _filter_mentioned(skills, corpus)
    skill_block = _section_block(
        masked_text,
        _SKILL_HEADERS,
        _EXPERIENCE_HEADERS + _PROJECT_HEADERS + _OTHER_HEADERS,
    )
    for key in ("experience", "projects"):
        rows = updated.get(key) if isinstance(updated.get(key), list) else []
        for item in rows:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "").strip()
            job_evidence = "\n".join(part for part in (skill_block, description) if part).strip() or corpus
            item["skills_used"] = _filter_mentioned(item.get("skills_used") or [], job_evidence)
    return updated


# Drop refined skills the redacted CV text does not actually contain.
def _filter_mentioned(items: list[Any], evidence_text: str) -> list[Any]:
    if not evidence_text.strip():
        return items
    kept: list[Any] = []
    for item in items or []:
        labels = [label for label in _labels_for_mention(item) if label.strip()]
        if not labels or any(_mentioned_in_cv(label, evidence_text) for label in labels):
            kept.append(item)
    return kept


# Union language rows; a refined level replaces an empty first-pass level.
def _merge_languages(base: list[Any], refined: list[Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_name: dict[str, int] = {}
    for item in list(base or []) + list(refined or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("language") or "").strip()
        key = name.casefold()
        if not key:
            continue
        if key not in index_by_name:
            index_by_name[key] = len(merged)
            merged.append(dict(item))
            continue
        current = merged[index_by_name[key]]
        if item.get("level") and not current.get("level"):
            current["level"] = item.get("level")
    return merged


# Prefer the education list that carries more degree or field evidence.
def _education_richness(items: list[Any]) -> int:
    score = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        score += 1
        if any(str(item.get(key) or "").strip() for key in ("field", "major", "field_of_study", "degree")):
            score += 2
    return score


# Merge skill lists by canonical name, preferring structured objects from the refiner.
def _merge_skills(base: list[Any], refined: list[Any]) -> list[dict[str, Any]]:
    combined: list[Any] = []
    seen: set[str] = set()
    for bucket in (base, refined):
        for item in bucket or []:
            if isinstance(item, dict):
                canonical = str(item.get("canonical_skill") or item.get("name") or "").strip().casefold()
                label = str(item.get("name") or item.get("display_name") or canonical)
            else:
                label = str(item).strip()
                canonical = label.casefold().replace(" ", "_")
            if not label or canonical in seen:
                continue
            seen.add(canonical)
            combined.append(label if not isinstance(item, dict) else item)
    return normalize_skill_items(combined)


# Apply hybrid refinement onto the first-pass structured CV.
def merge_cv_refinement(
    base: dict[str, Any],
    refined: dict[str, Any],
    *,
    evidence_text: str = "",
) -> dict[str, Any]:
    """Prefer refiner experience, languages, and skills when they add coverage the CV states."""
    base_norm = dict(base)
    ref_norm = normalize_refiner_payload(refined)

    base_exp = base_norm.get("experience") if isinstance(base_norm.get("experience"), list) else []
    ref_exp = ref_norm.get("experience") if isinstance(ref_norm.get("experience"), list) else []
    ref_exp = normalize_experience_items(ref_exp)

    use_refined_experience = False
    if ref_exp:
        if len(ref_exp) > len(base_exp):
            use_refined_experience = True
        elif _dated_experience_count(ref_exp) > _dated_experience_count(base_exp):
            use_refined_experience = True
        elif base_exp and not _dated_experience_count(base_exp) and _dated_experience_count(ref_exp):
            use_refined_experience = True
        elif not base_exp:
            use_refined_experience = True

    if use_refined_experience:
        base_norm["experience"] = ref_exp

    base_skills = base_norm.get("skills") if isinstance(base_norm.get("skills"), list) else []
    skill_corpus = skill_evidence_text(evidence_text) if evidence_text.strip() else ""
    ref_skills = _filter_mentioned(
        ref_norm.get("skills") if isinstance(ref_norm.get("skills"), list) else [],
        skill_corpus or evidence_text,
    )
    if ref_skills:
        base_norm["skills"] = _merge_skills(base_skills, ref_skills)

    if use_refined_experience and evidence_text.strip():
        skill_block = _section_block(
            evidence_text,
            _SKILL_HEADERS,
            _EXPERIENCE_HEADERS + _PROJECT_HEADERS + _OTHER_HEADERS,
        )
        for item in base_norm.get("experience") or []:
            if isinstance(item, dict):
                description = str(item.get("description") or "").strip()
                job_evidence = "\n".join(part for part in (skill_block, description) if part).strip()
                item["skills_used"] = _filter_mentioned(
                    item.get("skills_used") or [],
                    job_evidence or skill_corpus or evidence_text,
                )

    base_languages = base_norm.get("languages") if isinstance(base_norm.get("languages"), list) else []
    ref_languages = ref_norm.get("languages") if isinstance(ref_norm.get("languages"), list) else []
    if ref_languages:
        base_norm["languages"] = _merge_languages(base_languages, ref_languages)

    ref_education = ref_norm.get("education") if isinstance(ref_norm.get("education"), list) else []
    base_education = base_norm.get("education") if isinstance(base_norm.get("education"), list) else []
    if ref_education and _education_richness(ref_education) >= _education_richness(base_education):
        base_norm["education"] = ref_education

    for key in ("projects", "certifications", "publications", "work_authorization"):
        ref_val = ref_norm.get(key)
        base_val = base_norm.get(key)
        if ref_val in (None, "", []):
            continue
        if base_val in (None, "", []):
            base_norm[key] = ref_val

    ref_summary = str(ref_norm.get("summary") or "").strip()
    base_summary = str(base_norm.get("summary") or "").strip()
    if ref_summary and len(ref_summary) > len(base_summary):
        base_norm["summary"] = ref_norm.get("summary")

    return enrich_experience_from_declared_years(base_norm)
