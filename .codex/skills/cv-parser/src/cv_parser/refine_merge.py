# Merges hybrid LLM CV refinement into a first-pass structured profile.
from __future__ import annotations

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


# Count experience rows that carry a parseable start_date.
def _dated_experience_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if isinstance(item, dict) and item.get("start_date"))


# True when a skill label is an explicit substring of the redacted CV text.
def _mentioned_in_cv(label: str, evidence_text: str) -> bool:
    needle = " ".join(label.split()).strip()
    if not needle or not evidence_text.strip():
        return True
    return needle.casefold() in evidence_text.casefold()


# Drop refined skills the redacted CV text does not actually contain.
def _filter_mentioned(items: list[Any], evidence_text: str) -> list[Any]:
    if not evidence_text.strip():
        return items
    kept: list[Any] = []
    for item in items or []:
        if isinstance(item, dict):
            label = str(item.get("name") or item.get("display_name") or item.get("canonical_skill") or "")
        else:
            label = str(item)
        if _mentioned_in_cv(label.replace("_", " "), evidence_text):
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
    ref_skills = _filter_mentioned(
        ref_norm.get("skills") if isinstance(ref_norm.get("skills"), list) else [],
        evidence_text,
    )
    if ref_skills:
        base_norm["skills"] = _merge_skills(base_skills, ref_skills)

    if use_refined_experience and evidence_text.strip():
        for item in base_norm.get("experience") or []:
            if isinstance(item, dict):
                item["skills_used"] = _filter_mentioned(item.get("skills_used") or [], evidence_text)

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
