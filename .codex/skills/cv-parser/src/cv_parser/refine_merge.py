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
def merge_cv_refinement(base: dict[str, Any], refined: dict[str, Any]) -> dict[str, Any]:
    """Prefer refiner experience/skills when they add dates, splits, or coverage."""
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
    ref_skills = ref_norm.get("skills") if isinstance(ref_norm.get("skills"), list) else []
    if ref_skills:
        base_norm["skills"] = _merge_skills(base_skills, ref_skills)

    for key in ("languages", "education", "projects", "certifications", "publications", "location", "work_authorization"):
        ref_val = ref_norm.get(key)
        base_val = base_norm.get(key)
        if ref_val in (None, "", []):
            continue
        if base_val in (None, "", []):
            base_norm[key] = ref_val
        elif key == "education" and isinstance(ref_val, list) and isinstance(base_val, list):
            if len(ref_val) > len(base_val):
                base_norm[key] = ref_val

    ref_summary = str(ref_norm.get("summary") or "").strip()
    base_summary = str(base_norm.get("summary") or "").strip()
    if ref_summary and len(ref_summary) > len(base_summary):
        base_norm["summary"] = ref_norm.get("summary")

    return enrich_experience_from_declared_years(base_norm)
