# Builds, validates, canonicalizes, and hashes candidate matching configurations.
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from .contracts import (
    ALGORITHM_VERSION,
    DEFAULT_WEIGHTS,
    DIMENSION_IDS,
    EffectiveConfig,
    MatchingConfigError,
    SCHEMA_VERSION,
)

_PROTECTED_TERMS = {
    "age",
    "gender",
    "sex",
    "ethnicity",
    "race",
    "religion",
    "disability",
    "marital_status",
    "family_status",
    "nationality",
    "date_of_birth",
}


# Converts parser values into a stable lowercase skill identifier.
def normalize_token(value: Any) -> str:
    return "_".join(str(value or "").strip().casefold().replace("-", " ").split())


# Returns a copied list containing only mapping records.
def _records(value: Any) -> list[dict[str, Any]]:
    return [copy.deepcopy(item) for item in value or [] if isinstance(item, dict)]


# Merges canonical requirement records while preserving stable source identity.
def _merge_must_skills(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sources, start=1):
        canonical = normalize_token(
            item.get("canonical_skill") or item.get("skill") or item.get("name") or item.get("display_name")
        )
        if not canonical:
            continue
        weight = float(item.get("weight", 1.0))
        current = merged.get(canonical)
        if current:
            current["weight"] = round(current["weight"] + weight, 8)
            continue
        merged[canonical] = {
            "skill_id": str(item.get("skill_id") or f"{canonical}_{index}"),
            "canonical_skill": canonical,
            "display_name": str(item.get("display_name") or canonical.replace("_", " ").title()),
            "weight": weight,
            "minimum_match_strength": float(item.get("minimum_match_strength", 0.7)),
            "provenance": copy.deepcopy(item.get("provenance")),
        }
    return [merged[key] for key in sorted(merged)]


# Builds merged must skills from JD data or the legacy migration fallback.
def _build_must_skills(jd_data: dict[str, Any], legacy_weight_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    sources = _records(jd_data.get("must_skills"))
    if not sources and legacy_weight_config:
        sources = _records(legacy_weight_config.get("skills"))
    return _merge_must_skills(sources)


# Converts parsed JD fields into supported job-specific evaluators.
def _build_job_specific(jd_data: dict[str, Any]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for item in _records(jd_data.get("preferred_skills")):
        skill = normalize_token(item.get("canonical_skill") or item.get("display_name"))
        if skill:
            requirements.append(
                {
                    "requirement_id": str(item.get("skill_id") or f"preferred_{skill}"),
                    "evaluator_type": "preferred_skill",
                    "weight": float(item.get("weight", 1.0)),
                    "mandatory": False,
                    "parameters": {"canonical_skill": skill},
                    "provenance": copy.deepcopy(item.get("provenance")),
                }
            )
    for index, item in enumerate(_records(jd_data.get("language_requirements")), start=1):
        language = str(item.get("language") or "").strip()
        if language:
            requirements.append(
                {
                    "requirement_id": f"language_{normalize_token(language)}_{index}",
                    "evaluator_type": "language",
                    "weight": 1.0,
                    "mandatory": bool(item.get("is_mandatory")),
                    "parameters": {"language": language, "level": item.get("level")},
                    "provenance": copy.deepcopy(item.get("provenance")),
                }
            )
    return requirements


# Builds mandatory eligibility rules from explicit parsed JD requirements.
def _build_eligibility_rules(jd_data: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    experience = jd_data.get("experience_requirement") or {}
    if isinstance(experience, dict) and experience.get("minimum_years") is not None:
        rules.append(
            {
                "rule_id": "minimum_relevant_experience",
                "mandatory": True,
                "parameters": {"minimum_years": float(experience["minimum_years"])},
            }
        )
    for index, item in enumerate(_records(jd_data.get("language_requirements")), start=1):
        if item.get("is_mandatory"):
            rules.append(
                {
                    "rule_id": f"mandatory_language_{index}",
                    "mandatory": True,
                    "parameters": {"language": item.get("language"), "level": item.get("level")},
                }
            )
    education = jd_data.get("education_requirement") or {}
    if isinstance(education, dict) and education.get("is_mandatory"):
        minimum_degree = education.get("minimum_degree")
        if minimum_degree and normalize_token(minimum_degree) not in {"", "none"}:
            rules.append(
                {
                    "rule_id": "mandatory_degree",
                    "mandatory": True,
                    "parameters": {"minimum_degree": minimum_degree},
                }
            )
        field_of_study = education.get("field_of_study")
        if isinstance(field_of_study, str) and field_of_study.strip() and field_of_study.casefold() not in {"none", "any"}:
            rules.append(
                {
                    "rule_id": "mandatory_field_of_study",
                    "mandatory": True,
                    "parameters": {"field_of_study": field_of_study},
                }
            )
        for certification in education.get("certifications") or []:
            rules.append(
                {
                    "rule_id": "mandatory_certification",
                    "mandatory": True,
                    "parameters": {"certification": certification},
                }
            )
    visa = jd_data.get("visa_requirement") or {}
    if isinstance(visa, dict) and visa.get("requirement_type") == "required":
        rules.append(
            {
                "rule_id": "work_authorization",
                "mandatory": True,
                "parameters": {"target_region": visa.get("target_region")},
            }
        )
    return rules


# Resolves a target seniority from explicit JD overview fields.
def _target_seniority(jd_data: dict[str, Any]) -> str | None:
    overview = jd_data.get("jd_overview") or {}
    values: list[Any] = []
    if isinstance(overview, dict):
        values.extend([overview.get("seniority"), overview.get("job_title"), overview.get("title")])
        values.extend(overview.get("job_titles") or [])
    values.extend([jd_data.get("seniority"), jd_data.get("job_title"), jd_data.get("title")])
    levels = ("executive", "director", "manager", "lead", "senior", "junior", "intern", "mid")
    text = " ".join(str(value or "").casefold() for value in values)
    return next((level for level in levels if level in text), None)


# Detects whether explicit education or professional requirements exist.
def _has_education_requirement(jd_data: dict[str, Any], specific: list[dict[str, Any]]) -> bool:
    education = jd_data.get("education_requirement") or {}
    explicit_education = isinstance(education, dict) and (
        normalize_token(education.get("minimum_degree")) not in {"", "none"}
        or bool(education.get("field_of_study"))
        or bool(education.get("certifications"))
    )
    return explicit_education or any(item.get("evaluator_type") == "license" for item in specific)


# Calculates applicability independently from candidate evidence.
def _activation_map(config: dict[str, Any], jd_data: dict[str, Any]) -> dict[str, bool]:
    must = config["must_skills"]
    specific = config["job_specific_requirements"]
    experience = jd_data.get("experience_requirement") or {}
    overview = jd_data.get("jd_overview") or {}
    has_role = bool(config.get("target_seniority")) or bool(
        isinstance(overview, dict) and (overview.get("job_title") or overview.get("job_titles"))
    )
    return {
        "core_skill_match": bool(must),
        "relevant_experience": bool(must or specific or has_role or experience),
        "role_seniority_fit": bool(config.get("target_seniority")),
        "education_certification": _has_education_requirement(
            {"education_requirement": config.get("education_requirement")}, specific
        ),
        "job_specific_match": bool(specific),
    }


# Validates dimensions and writes normalized active weights.
def _validate_and_normalize(config: dict[str, Any], jd_data: dict[str, Any]) -> None:
    dimensions = config.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSION_IDS):
        raise MatchingConfigError("dimensions must contain exactly the six fixed dimension IDs")
    activation = _activation_map(config, jd_data)
    active_weight = 0.0
    for dimension_id in DIMENSION_IDS:
        settings = dimensions[dimension_id]
        if not isinstance(settings, dict):
            raise MatchingConfigError(f"invalid settings for {dimension_id}")
        weight = float(settings.get("weight", DEFAULT_WEIGHTS[dimension_id]))
        if weight < 0 or not math.isfinite(weight):
            raise MatchingConfigError(f"invalid weight for {dimension_id}")
        settings["weight"] = weight
        settings["enabled"] = bool(settings.get("enabled", True))
        settings["active"] = settings["enabled"] and activation[dimension_id]
        if settings["active"]:
            active_weight += weight
    for collection_name in ("must_skills", "job_specific_requirements"):
        for item in _records(config.get(collection_name)):
            weight = float(item.get("weight", 1.0))
            if weight <= 0 or not math.isfinite(weight):
                raise MatchingConfigError(f"invalid internal weight in {collection_name}")
            if collection_name == "must_skills":
                strength = float(item.get("minimum_match_strength", 0.7))
                if strength < 0 or strength > 1 or not math.isfinite(strength):
                    raise MatchingConfigError("minimum_match_strength must be between 0 and 1")
    for item in _records(config.get("job_specific_requirements")):
        protected_values = {
            normalize_token(value)
            for value in (item.get("parameters") or {}).values()
            if isinstance(value, str)
        }
        if protected_values & _PROTECTED_TERMS:
            raise MatchingConfigError("protected attributes cannot be matching requirements")
    protected_skills = {
        normalize_token(item.get("canonical_skill"))
        for item in _records(config.get("must_skills"))
    }
    education = config.get("education_requirement") or {}
    protected_education = {
        normalize_token(education.get("field_of_study")),
        normalize_token(education.get("minimum_degree")),
    } if isinstance(education, dict) else set()
    if (protected_skills | protected_education) & _PROTECTED_TERMS:
        raise MatchingConfigError("protected attributes cannot be matching requirements")
    bands = config.get("fit_bands") or {}
    medium_min = float(bands.get("medium_min", 60.0))
    high_min = float(bands.get("high_min", 80.0))
    if not (0 <= medium_min <= high_min <= 100):
        raise MatchingConfigError("fit band thresholds must satisfy 0 <= medium <= high <= 100")
    policy = config.get("interview_question_policy") or {}
    minimum = int(policy.get("min_questions", 3))
    maximum = int(policy.get("max_questions", 6))
    if not (0 <= minimum <= maximum <= 6):
        raise MatchingConfigError("question policy must satisfy 0 <= min <= max <= 6")
    if active_weight <= 0:
        raise MatchingConfigError("at least one scoring dimension is required", "MATCHING_NO_ACTIVE_DIMENSIONS")
    for dimension_id in DIMENSION_IDS:
        settings = dimensions[dimension_id]
        settings["normalized_weight"] = (
            round(settings["weight"] / active_weight, 12) if settings["active"] else 0.0
        )


# Creates a validated effective configuration using the documented precedence.
def build_matching_config(
    jd_structured_data: dict[str, Any],
    explicit_config: dict[str, Any] | None = None,
    legacy_weight_config: dict[str, Any] | None = None,
) -> EffectiveConfig:
    if not isinstance(jd_structured_data, dict):
        raise MatchingConfigError("JD structured data is required", "MATCHING_JD_NOT_READY")
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "taxonomy_version": "none",
        "reference_date_policy": "injected",
        "dimensions": {
            dimension_id: {"enabled": True, "weight": weight}
            for dimension_id, weight in DEFAULT_WEIGHTS.items()
        },
        "must_skills": _build_must_skills(jd_structured_data, legacy_weight_config),
        "eligibility_rules": _build_eligibility_rules(jd_structured_data),
        "job_specific_requirements": _build_job_specific(jd_structured_data),
        "education_requirement": copy.deepcopy(jd_structured_data.get("education_requirement") or {}),
        "target_seniority": _target_seniority(jd_structured_data),
        "fit_bands": {"high_min": 80.0, "medium_min": 60.0},
        "interview_question_policy": {"min_questions": 3, "max_questions": 6},
    }
    if explicit_config:
        for key, value in explicit_config.items():
            base[key] = copy.deepcopy(value)
    base["schema_version"] = SCHEMA_VERSION
    base["algorithm_version"] = ALGORITHM_VERSION
    base.setdefault("must_skills", [])
    base.setdefault("eligibility_rules", [])
    base.setdefault("job_specific_requirements", [])
    base["must_skills"] = _merge_must_skills(_records(base["must_skills"]))
    _validate_and_normalize(base, jd_structured_data)
    canonical_json = json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return EffectiveConfig(
        config=base,
        canonical_json=canonical_json,
        config_hash=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )
