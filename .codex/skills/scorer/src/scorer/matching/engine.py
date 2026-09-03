# Implements the pure deterministic six-dimension candidate matching engine.
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .config_builder import normalize_token
from .contracts import DIMENSION_IDS, DIMENSION_LABELS, EffectiveConfig, SkillRelationResolver

_TAXONOMY_LOADER = None
_TAXONOMY_UNAVAILABLE = False


_SENIORITY = ("intern", "junior", "mid", "senior", "lead", "manager", "director", "executive")
_DEGREES = {"none": 0, "high_school": 1, "associate": 2, "bachelor": 3, "master": 4, "doctorate": 5, "phd": 5}
# Ordered patterns for classifying free-text degree labels (MPHIL, "BSc (Hons)", "Master of Science in ...").
_DEGREE_PATTERNS = (
    (re.compile(r"\b(ph\.?\s?d|d\.?\s?phil|ed\.?\s?d|d\.?b\.?a|doctor(ate|al)?)\b"), "doctorate"),
    (re.compile(r"\b(m\.?\s?phil|m\.?\s?sc|m\.?\s?res|m\.?\s?ph\b|m\.?\s?a\b|m\.?\s?s\b|m\.?b\.?a|m\.?fin|m\.?eng|m\.?ed|master'?s?)\b"), "master"),
    (re.compile(r"\b(b\.?\s?sc|b\.?\s?a\b|b\.?b\.?a|b\.?eng|b\.?com|b\.?bus|b\.?ed|bachelor'?s?|undergraduate)\b"), "bachelor"),
    (re.compile(r"\b(associate'?s?)\b"), "associate"),
    (re.compile(r"\b(high\s?school|secondary\s?school)\b"), "high_school"),
)
_LANGUAGES = {"basic": 0.5, "business": 1.0, "fluent": 2.0, "native": 3.0}
_OWNERSHIP_SIGNALS = (
    "owned",
    "led",
    "managed",
    "directed",
    "designed",
    "architected",
    "authored",
    "co-authored",
    "coauthored",
    "conducted",
    "supervised",
    "analysed",
    "analyzed",
    "investigated",
    "published",
    "负责",
    "負責",
    "主导",
    "主導",
    "管理",
)
# Quantified impact units. The third alternative covers academic and research output
# (papers, grants, sample sizes) so research CVs are not systematically scored zero here.
_METRIC_PATTERN = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|x|ms|s|hours?|days?|users?|customers?|requests?|million|billion)\b|"
    r"(?:increased|reduced|improved|grew|saved|decreased)\s+\w*\s*\d+|"
    r"\b\d+(?:\.\d+)?\s*(?:papers?|publications?|articles?|citations?|grants?|projects?|"
    r"participants?|subjects?|respondents?|samples?|surveys?|interviews?|datasets?|records?|"
    r"cohorts?|trials?)\b|"
    r"[£€¥$]\s?\d+(?:\.\d+)?(?:\s?(?:k|m|bn|million|billion))?)",
    re.IGNORECASE,
)
_PROTECTED_TEXT_PATTERN = re.compile(
    r"\b(?:age|gender|sex|ethnicity|race|religion|disability|marital|family status|nationality|date of birth)\b",
    re.IGNORECASE,
)

# v2 blending weights for the folded evidence sub-scores (presence vs linkage, time vs quality).
CORE_PRESENCE_WEIGHT = 0.8
CORE_LINKAGE_WEIGHT = 0.2
EXPERIENCE_TIME_WEIGHT = 0.7
EXPERIENCE_QUALITY_WEIGHT = 0.3

# Major keywords that satisfy a JD "business-related or related quantitative" clause.
_QUANT_BUSINESS_TERMS = (
    "business", "finance", "economics", "accounting", "actuarial", "analytics",
    "management", "marketing", "computer", "computing", "software", "data",
    "statistic", "mathematical", "quantitative", "engineering", "information",
)


# Rounds a numeric value with the PRD half-up rule.
def _round(value: float, places: int = 2) -> float:
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# Converts a parser date into the first day of its month.
def _parse_month(value: Any, reference_date: date) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.casefold() in {"present", "current", "now"}:
        return reference_date.replace(day=1)
    for pattern in ("%Y-%m", "%Y/%m", "%Y.%m", "%Y"):
        try:
            return datetime.strptime(text, pattern).date().replace(day=1)
        except ValueError:
            continue
    return None


# Loads the on-disk taxonomy once for longest-token evidence expansion.
def _taxonomy_loader() -> Any:
    global _TAXONOMY_LOADER, _TAXONOMY_UNAVAILABLE
    if _TAXONOMY_UNAVAILABLE:
        return None
    if _TAXONOMY_LOADER is not None:
        return _TAXONOMY_LOADER
    try:
        from screening_core.paths import taxonomy_yaml_path
        from screening_core.taxonomy import SkillTaxonomyLoader

        path = taxonomy_yaml_path()
        if not path.is_file():
            _TAXONOMY_UNAVAILABLE = True
            return None
        loader = SkillTaxonomyLoader(str(path))
        loader.load()
        _TAXONOMY_LOADER = loader
        return loader
    except (OSError, ImportError):
        _TAXONOMY_UNAVAILABLE = True
        return None


# Returns taxonomy skill tokens found in free text (underscores treated as spaces).
def _taxonomy_tokens(text: Any) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    loader = _taxonomy_loader()
    if loader is None:
        return []
    return [normalize_token(name) for name in loader.skills_in_text(raw.replace("_", " "))]


# Splits education field_of_study into comparable canonical tokens.
def _field_token_set(value: Any) -> set[str]:
    parts: list[str] = []
    if isinstance(value, list):
        parts = [str(item) for item in value if item]
    elif isinstance(value, str) and value.strip():
        parts = [part.strip() for part in re.split(r"[,;/]", value) if part.strip()]
    tokens: set[str] = set()
    for part in parts:
        token = normalize_token(part)
        if token:
            tokens.add(token)
        tokens.update(_taxonomy_tokens(part))
    tokens.discard("")
    return tokens


# True when any CV major overlaps any acceptable JD field of study.
# True when a CV major reads as business-related or quantitative for the JD fallback clause.
def _major_matches_quantitative_fallback(major: str) -> bool:
    text = str(major or "").casefold()
    return any(term in text for term in _QUANT_BUSINESS_TERMS)


# True when any CV major overlaps an acceptable JD field or its quantitative fallback.
def _fields_satisfied(required: Any, candidate_majors: list[str]) -> bool:
    need = _field_token_set(required)
    if not need:
        return True
    have: set[str] = set()
    for major in candidate_majors:
        token = normalize_token(major)
        if token:
            have.add(token)
        have.update(_taxonomy_tokens(major))
    if need & have:
        return True
    if "related_quantitative" in need:
        return any(_major_matches_quantitative_fallback(major) for major in candidate_majors)
    return False



def _certification_skill_tokens(item: dict[str, Any]) -> list[str]:
    tokens = _taxonomy_tokens(item.get("name"))
    try:
        from cv_parser.certifications import certifications_to_skills
    except ImportError:
        return tokens
    derived = [normalize_token(skill) for skill in certifications_to_skills([item])]
    return list(dict.fromkeys([token for token in tokens + derived if token]))


# Records one skill evidence token against its CV source.
def _add_skill_source(
    sources: dict[str, list[dict[str, Any]]],
    token: str,
    record: dict[str, Any],
) -> None:
    if token:
        sources.setdefault(token, []).append(record)


# Returns all explicit technical skill tokens without reading protected fields.
def _skill_sources(cv: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    sources: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(cv.get("skills") or []):
        value = item.get("canonical_skill") if isinstance(item, dict) else item
        text = str(value or "")
        record = {"section": "skills", "index": index, "text": text, "structured": False}
        _add_skill_source(sources, normalize_token(value), record)
        for token in _taxonomy_tokens(text):
            _add_skill_source(sources, token, record)
    for section in ("experience", "projects"):
        for index, item in enumerate(cv.get(section) or []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("description") or item.get("name") or "")
            title = str(item.get("job_title") or "")
            for skill in item.get("skills_used") or []:
                record = {
                    "section": section,
                    "index": index,
                    "text": text or str(skill),
                    "structured": True,
                }
                _add_skill_source(sources, normalize_token(skill), record)
                for token in _taxonomy_tokens(skill):
                    _add_skill_source(sources, token, record)
            title_record = {
                "section": section,
                "index": index,
                "text": title or text,
                "structured": True,
            }
            for token in _taxonomy_tokens(title):
                _add_skill_source(sources, token, title_record)
    for index, item in enumerate(cv.get("education") or []):
        if not isinstance(item, dict):
            continue
        major = str(item.get("major") or "")
        if not major:
            continue
        record = {"section": "education", "index": index, "text": major, "structured": True}
        for token in _taxonomy_tokens(major):
            _add_skill_source(sources, token, record)
    for index, item in enumerate(cv.get("certifications") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        record = {"section": "certifications", "index": index, "text": name, "structured": True}
        _add_skill_source(sources, normalize_token(name), record)
        for token in _certification_skill_tokens(item):
            _add_skill_source(sources, token, record)
    return sources


# Finds an exact or approved related skill match.
def _match_skill(
    required: str,
    sources: dict[str, list[dict[str, Any]]],
    relation_resolver: SkillRelationResolver | None,
) -> tuple[float, str | None, dict[str, Any] | None]:
    if required in sources:
        return 1.0, required, sources[required][0]
    if relation_resolver:
        for candidate in sorted(sources):
            if relation_resolver(candidate, required):
                return 0.7, candidate, sources[candidate][0]
    return 0.0, None, None


# Converts parser provenance into the public requirement source shape.
# Returns strength, best source, and structured linkage for one required skill.
def _skill_evidence(
    required: str,
    sources: dict[str, list[dict[str, Any]]],
    relation_resolver: SkillRelationResolver | None,
) -> tuple[float, dict[str, Any] | None, bool]:
    def linked_best(records: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        best = records[0]
        structured = any(record.get("structured") for record in records)
        if structured:
            best = next(record for record in records if record.get("structured"))
        return best, structured

    if required in sources:
        best, structured = linked_best(sources[required])
        return 1.0, best, structured
    if relation_resolver:
        for candidate in sorted(sources):
            if relation_resolver(candidate, required):
                best, structured = linked_best(sources[candidate])
                return 0.7, best, structured
    return 0.0, None, False



def _requirement_record(item: dict[str, Any], requirement_id: str, text: str) -> dict[str, Any]:
    provenance = item.get("provenance")
    if isinstance(provenance, dict):
        source = {
            "document": "jd",
            "section": "must_skills",
            "source_sentence": provenance.get("source_sentence"),
            "char_start": provenance.get("source_char_start"),
            "char_end": provenance.get("source_char_end"),
        }
    else:
        source = {"document": "jd", "section": "matching_config", "source_sentence": provenance}
    return {"requirement_id": requirement_id, "text": text, "source": source}


# Converts a matched source into a traceable CV evidence record.
def _evidence_record(
    source: dict[str, Any],
    requirement_ids: list[str],
    match_type: str = "exact",
) -> dict[str, Any]:
    confidence = 0.92 if source.get("structured") and match_type == "exact" else 0.72
    return {
        "evidence_id": f"{source['section']}:{source['index']}",
        "document": "cv",
        "section": source["section"],
        "text": source["text"],
        "matched_requirement_ids": requirement_ids,
        "match_type": match_type,
        "confidence": confidence,
    }


# Creates the complete inactive radar object required by the contract.
def _inactive_dimension(dimension_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    label = DIMENSION_LABELS[dimension_id]
    return {
        "dimension_id": dimension_id,
        "label": label,
        "active": False,
        "score": None,
        "configured_weight": settings["weight"],
        "normalized_weight": 0.0,
        "weighted_points": 0.0,
        "status": "not_applicable",
        "requirements": [],
        "evidence": [],
        "gaps": [],
        "reasoning": {
            "template_id": "DR-NA-001",
            "summary": f"This Job Post has no explicit {label} requirement.",
            "facts": {},
        },
        "confidence": 100.0,
    }


# Finalizes a complete active radar dimension record.
def _dimension(
    dimension_id: str,
    settings: dict[str, Any],
    score: float,
    status: str,
    requirements: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    template_id: str,
    summary: str,
    facts: dict[str, Any],
    confidence: float,
) -> dict[str, Any]:
    score = _round(max(0.0, min(score, 100.0)))
    return {
        "dimension_id": dimension_id,
        "label": DIMENSION_LABELS[dimension_id],
        "active": True,
        "score": score,
        "configured_weight": settings["weight"],
        "normalized_weight": settings["normalized_weight"],
        "weighted_points": _round(score * settings["normalized_weight"]),
        "status": status,
        "requirements": requirements,
        "evidence": evidence,
        "gaps": gaps,
        "reasoning": {"template_id": template_id, "summary": summary, "facts": facts},
        "confidence": _round(max(0.0, min(confidence, 100.0))),
    }


# Scores weighted must-skill coverage and records exact evidence or gaps.
# Scores weighted must-skill presence plus evidence linkage (any structured source counts).
def _score_core(
    config: dict[str, Any],
    cv: dict[str, Any],
    relation_resolver: SkillRelationResolver | None,
) -> tuple[dict[str, Any], dict[str, tuple[float, dict[str, Any] | None]]]:
    settings = config["dimensions"]["core_skill_match"]
    if not settings["active"]:
        return _inactive_dimension("core_skill_match", settings), {}
    sources = _skill_sources(cv)
    requirements: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    matches: dict[str, tuple[float, dict[str, Any] | None]] = {}
    earned = total = confidence_points = 0.0
    matched_count = linked_count = 0
    for item in config["must_skills"]:
        requirement_id = str(item["skill_id"])
        skill = normalize_token(item["canonical_skill"])
        display = str(item.get("display_name") or skill.replace("_", " ").title())
        weight = float(item.get("weight", 1.0))
        strength, source, linked = _skill_evidence(skill, sources, relation_resolver)
        requirements.append(_requirement_record(item, requirement_id, display))
        matches[requirement_id] = (strength, source)
        total += weight
        earned += weight * strength
        if strength > 0:
            matched_count += 1
            if linked:
                linked_count += 1
        if source:
            match_type = "exact" if strength == 1.0 else "related"
            evidence.append(_evidence_record(source, [requirement_id], match_type))
            confidence_points += weight * (92.0 if source["structured"] and strength == 1.0 else 72.0)
        else:
            gaps.append(
                {
                    "requirement_id": requirement_id,
                    "reason_code": "NO_EXPLICIT_CV_EVIDENCE",
                    "text": f"No explicit {display} evidence was found.",
                }
            )
            confidence_points += weight * 55.0
    presence = 100.0 * earned / total
    linkage = 100.0 * (linked_count / matched_count) if matched_count else 0.0
    score = _round(CORE_PRESENCE_WEIGHT * presence + CORE_LINKAGE_WEIGHT * linkage)
    met_count = sum(1 for strength, _ in matches.values() if strength > 0)
    gap_list = ", ".join(gap["text"] for gap in gaps) or "none"
    summary = (
        f"Core Skill Match: {_round(score)}/100 (presence {_round(presence)}%, "
        f"linkage {_round(linkage)}%). The CV supports {met_count} of {len(requirements)} "
        f"weighted must skills. Key gaps: {gap_list}."
    )
    status = "met" if score >= 80 else "partial" if evidence else "not_met"
    return (
        _dimension(
            "core_skill_match",
            settings,
            score,
            status,
            requirements,
            evidence,
            gaps,
            "DR-CORE-001",
            summary,
            {
                "presence_pct": _round(presence),
                "linkage_pct": _round(linkage),
                "weighted_requirements_met": _round(earned),
                "weighted_requirements_total": _round(total),
            },
            confidence_points / total,
        ),
        matches,
    )
def _relevant_experiences(config: dict[str, Any], cv: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    tokens = {item["canonical_skill"] for item in config["must_skills"]}
    for item in config["job_specific_requirements"]:
        parameters = item.get("parameters") or {}
        tokens.add(normalize_token(parameters.get("canonical_skill") or parameters.get("domain")))
    target = normalize_token(config.get("target_seniority"))
    relevant: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(cv.get("experience") or []):
        if not isinstance(item, dict):
            continue
        item_skills = {normalize_token(skill) for skill in item.get("skills_used") or []}
        text = normalize_token(f"{item.get('job_title', '')} {item.get('description', '')}")
        if item_skills & tokens or any(token and token in text for token in tokens) or (target and target in text):
            relevant.append((index, item))
    return relevant


# Unions overlapping month intervals and returns duration plus latest end date.
def _union_experience_months(
    experiences: list[tuple[int, dict[str, Any]]],
    reference_date: date,
) -> tuple[int, date | None, list[tuple[int, dict[str, Any]]]]:
    intervals: list[tuple[date, date, int, dict[str, Any]]] = []
    for index, item in experiences:
        start = _parse_month(item.get("start_date"), reference_date)
        end = _parse_month(item.get("end_date"), reference_date)
        if start and end and end >= start:
            intervals.append((start, end, index, item))
    if not intervals:
        return 0, None, []
    intervals.sort(key=lambda row: (row[0], row[1]))
    total = 0
    current_start, current_end = intervals[0][0], intervals[0][1]
    for start, end, _, _ in intervals[1:]:
        if (start.year * 12 + start.month) <= (current_end.year * 12 + current_end.month + 1):
            current_end = max(current_end, end)
        else:
            total += (current_end.year - current_start.year) * 12 + current_end.month - current_start.month + 1
            current_start, current_end = start, end
    total += (current_end.year - current_start.year) * 12 + current_end.month - current_start.month + 1
    return total, max(row[1] for row in intervals), [(row[2], row[3]) for row in intervals]


# Scores relevant duration and recency using unioned dated intervals.
# Scores dated time/recency plus ownership/impact quality over all relevant experience.
def _score_experience(
    config: dict[str, Any],
    cv: dict[str, Any],
    reference_date: date,
) -> tuple[dict[str, Any], float]:
    settings = config["dimensions"]["relevant_experience"]
    if not settings["active"]:
        return _inactive_dimension("relevant_experience", settings), 0.0
    relevant = _relevant_experiences(config, cv)
    months, latest, dated = _union_experience_months(relevant, reference_date)
    relevant_years = _round(months / 12.0)
    minimum = next(
        (
            float(rule.get("parameters", {}).get("minimum_years"))
            for rule in config["eligibility_rules"]
            if rule.get("rule_id") == "minimum_relevant_experience"
        ),
        None,
    )
    age_months = (
        (reference_date.year - latest.year) * 12 + reference_date.month - latest.month if latest else None
    )
    recency = 100.0 if age_months is not None and age_months <= 24 else 70.0 if age_months is not None and age_months <= 48 else 40.0
    if not dated:
        recency = 0.0
        time_score = 0.0
    elif minimum is not None:
        time_score = 0.8 * min(relevant_years / minimum, 1.0) * 100.0 + 0.2 * recency
    else:
        all_dated = sum(
            1
            for item in cv.get("experience") or []
            if isinstance(item, dict) and _parse_month(item.get("start_date"), reference_date)
        )
        time_score = 0.7 * (len(dated) / all_dated if all_dated else 0.0) * 100.0 + 0.3 * recency
    texts = [str(item.get("description") or "") for _, item in relevant]
    ownership = sum(any(signal in text.casefold() for signal in _OWNERSHIP_SIGNALS) for text in texts) / len(texts) if texts else 0.0
    impact = sum(bool(_METRIC_PATTERN.search(text)) for text in texts) / len(texts) if texts else 0.0
    quality = 0.5 * ownership + 0.5 * impact
    score = _round(EXPERIENCE_TIME_WEIGHT * time_score + EXPERIENCE_QUALITY_WEIGHT * quality * 100.0)
    requirements = [
        {
            "requirement_id": "relevant_experience",
            "text": f"{minimum:g} years relevant experience" if minimum is not None else "Relevant dated experience",
            "source": {"document": "jd", "section": "experience_requirement"},
        }
    ]
    evidence = [
        _evidence_record(
            {
                "section": "experience",
                "index": index,
                "text": str(item.get("description") or item.get("job_title") or ""),
                "structured": True,
            },
            ["relevant_experience"],
        )
        for index, item in relevant
    ]
    gaps: list[dict[str, Any]] = []
    if not dated:
        gaps.append({"requirement_id": "relevant_experience", "reason_code": "CV_DATED_EVIDENCE_MISSING", "text": "No dated relevant experience evidence was found."})
    if not impact:
        gaps.append({"requirement_id": "quantified_impact", "reason_code": "QUANTIFIED_IMPACT_MISSING", "text": "No quantified impact was found in relevant experience."})
    required_text = f"{minimum:g}" if minimum is not None else "no minimum"
    summary = (
        f"Relevant Experience: {_round(score)}/100 (time {_round(time_score)}, "
        f"quality {_round(quality * 100)}). The JD requests {required_text} years; the CV "
        f"provides {relevant_years} years of dated relevant evidence. Ownership {_round(ownership * 100)}%; "
        f"quantified impact {_round(impact * 100)}%."
    )
    status = "met" if score >= 80 else "partial" if evidence else "not_met"
    confidence = 90.0 if evidence else 20.0
    return (
        _dimension(
            "relevant_experience",
            settings,
            score,
            status,
            requirements,
            evidence,
            gaps,
            "DR-EXP-001",
            summary,
            {
                "required_years": minimum,
                "relevant_years": relevant_years,
                "latest_age_months": age_months,
                "time_pct": _round(time_score),
                "quality_pct": _round(quality * 100),
                "ownership_pct": _round(ownership * 100),
                "impact_pct": _round(impact * 100),
            },
            confidence,
        ),
        relevant_years,
    )
def _candidate_seniority(relevant: list[tuple[int, dict[str, Any]]]) -> tuple[str | None, int | None]:
    found: list[tuple[int, int]] = []
    for index, item in relevant:
        text = str(item.get("job_title") or "").casefold()
        for level_index, level in enumerate(_SENIORITY):
            if re.search(rf"\b{re.escape(level)}\b", text):
                found.append((level_index, index))
    if not found:
        return None, None
    level_index, experience_index = max(found)
    return _SENIORITY[level_index], experience_index


# Scores explicit role seniority relative to the target level.
def _score_role(config: dict[str, Any], cv: dict[str, Any]) -> dict[str, Any]:
    settings = config["dimensions"]["role_seniority_fit"]
    if not settings["active"]:
        return _inactive_dimension("role_seniority_fit", settings)
    target = str(config["target_seniority"])
    candidate, index = _candidate_seniority(_relevant_experiences(config, cv))
    if candidate is None:
        score, status, confidence = 0.0, "unknown", 0.0
    else:
        difference = _SENIORITY.index(target) - _SENIORITY.index(candidate)
        score = 100.0 if difference <= 0 else 70.0 if difference == 1 else 40.0 if difference == 2 else 10.0
        status, confidence = ("met" if difference <= 0 else "partial"), 90.0
    evidence = []
    if index is not None:
        item = cv["experience"][index]
        evidence.append(
            _evidence_record(
                {"section": "experience", "index": index, "text": str(item.get("job_title")), "structured": True},
                ["target_seniority"],
            )
        )
    gaps = [] if candidate else [{"requirement_id": "target_seniority", "reason_code": "CV_ROLE_LEVEL_UNKNOWN", "text": "No relevant CV role level could be resolved."}]
    summary = f"Role and Seniority Fit: {_round(score)}/100. Target level: {target}. Highest relevant CV level: {candidate or 'unknown'}."
    return _dimension(
        "role_seniority_fit",
        settings,
        score,
        status,
        [{"requirement_id": "target_seniority", "text": target, "source": {"document": "jd", "section": "job_title"}}],
        evidence,
        gaps,
        "DR-ROLE-001",
        summary,
        {"target_level": target, "candidate_level": candidate},
        confidence,
    )
def _degree_level(value: Any) -> int | None:
    token = normalize_token(value)
    aliases = {"bs": "bachelor", "bsc": "bachelor", "ba": "bachelor", "msc": "master", "ma": "master", "mba": "master", "doctor": "doctorate"}
    token = aliases.get(token, token)
    level = _DEGREES.get(token)
    if level is not None:
        return level
    # Real CVs write "MPHIL" / "BSc (Hons)" / "Master of Science in Data Science", so fall
    # back to keyword matching on the raw label instead of requiring an exact token.
    text = str(value or "").casefold()
    if not text:
        return None
    for pattern, canonical in _DEGREE_PATTERNS:
        if pattern.search(text):
            return _DEGREES[canonical]
    return None


# Scores explicit degree, field, and certification requirements.
def _score_education(config: dict[str, Any], cv: dict[str, Any]) -> dict[str, Any]:
    settings = config["dimensions"]["education_certification"]
    if not settings["active"]:
        return _inactive_dimension("education_certification", settings)
    requirement = config.get("education_requirement") or {}
    requested_degree = requirement.get("minimum_degree")
    requested_field = requirement.get("field_of_study")
    requested_certs = [normalize_token(value) for value in requirement.get("certifications") or []]
    candidate_degrees = [
        _degree_level(item.get("degree_level") or item.get("degree"))
        for item in cv.get("education") or []
        if isinstance(item, dict)
    ]
    candidate_majors = [
        str(item.get("major"))
        for item in cv.get("education") or []
        if isinstance(item, dict) and item.get("major")
    ]
    candidate_certs = {
        normalize_token(item.get("name"))
        for item in cv.get("certifications") or []
        if isinstance(item, dict)
    }
    parts: list[tuple[float, float, str]] = []
    required_level = _degree_level(requested_degree)
    if required_level is not None and required_level > 0:
        candidate_level = max((level for level in candidate_degrees if level is not None), default=None)
        degree_score = 100.0 if candidate_level is not None and candidate_level >= required_level else 50.0 if not requirement.get("is_mandatory") and candidate_level == required_level - 1 else 0.0
        parts.append((0.7, degree_score, "degree"))
    if requested_field:
        parts.append((0.2, 100.0 if _fields_satisfied(requested_field, candidate_majors) else 0.0, "field"))
    if requested_certs:
        parts.append((0.1, 100.0 * sum(cert in candidate_certs for cert in requested_certs) / len(requested_certs), "certification"))
    for item in config["job_specific_requirements"]:
        if item.get("evaluator_type") == "license":
            license_name = normalize_token(item.get("parameters", {}).get("canonical_skill") or item.get("parameters", {}).get("license"))
            parts.append((0.1, 100.0 if license_name in candidate_certs else 0.0, "license"))
    total_weight = sum(weight for weight, _, _ in parts)
    score = sum(weight * value for weight, value, _ in parts) / total_weight
    missing = [name for _, value, name in parts if value < 100]
    evidence = [
        {"evidence_id": f"education:{index}", "document": "cv", "section": "education", "text": str(item.get("degree") or item.get("major") or ""), "matched_requirement_ids": ["education"], "match_type": "exact", "confidence": 0.9}
        for index, item in enumerate(cv.get("education") or [])
        if isinstance(item, dict)
    ]
    evidence.extend(
        {"evidence_id": f"certifications:{index}", "document": "cv", "section": "certifications", "text": str(item.get("name") or ""), "matched_requirement_ids": ["certification"], "match_type": "exact", "confidence": 0.9}
        for index, item in enumerate(cv.get("certifications") or [])
        if isinstance(item, dict)
    )
    gaps = [{"requirement_id": name, "reason_code": "EDUCATION_EVIDENCE_MISSING", "text": f"No matching {name} evidence was found."} for name in missing]
    summary = f"Education and Certification: {_round(score)}/100. Requirement: {', '.join(name for _, _, name in parts)}. CV evidence: {len(evidence)} record(s). Gap: {', '.join(missing) or 'none'}."
    return _dimension(
        "education_certification",
        settings,
        score,
        "met" if not missing else "partial" if evidence else "not_met",
        [{"requirement_id": "education", "text": str(requirement), "source": {"document": "jd", "section": "education_requirement"}}],
        evidence,
        gaps,
        "DR-EDU-001",
        summary,
        {"components": {name: value for _, value, name in parts}},
        90.0 if evidence else 30.0,
    )


# Evaluates one supported role-specific requirement from explicit CV evidence.
def _evaluate_specific(
    requirement: dict[str, Any],
    cv: dict[str, Any],
    sources: dict[str, list[dict[str, Any]]],
    relation_resolver: SkillRelationResolver | None,
) -> tuple[str, float | None, list[dict[str, Any]], str]:
    evaluator = requirement.get("evaluator_type")
    parameters = requirement.get("parameters") or {}
    requirement_id = str(requirement["requirement_id"])
    if evaluator == "preferred_skill":
        skill = normalize_token(parameters.get("canonical_skill"))
        strength, _, source = _match_skill(skill, sources, relation_resolver)
        evidence = [_evidence_record(source, [requirement_id], "exact" if strength == 1 else "related")] if source else []
        return ("met" if strength == 1 else "partial" if strength else "not_met", strength * 100.0, evidence, skill)
    if evaluator == "language":
        language = str(parameters.get("language") or "").casefold()
        candidate = next((item for item in cv.get("languages") or [] if isinstance(item, dict) and str(item.get("language") or "").casefold() == language), None)
        if not candidate:
            return "not_met", 0.0, [], str(parameters.get("language"))
        required_level = parameters.get("level")
        candidate_level = candidate.get("level")
        score = 100.0 if not required_level or not candidate_level or _LANGUAGES.get(str(candidate_level), -1) >= _LANGUAGES.get(str(required_level), 0) else 50.0
        source = {"section": "languages", "index": (cv.get("languages") or []).index(candidate), "text": f"{candidate.get('language')} {candidate_level or ''}".strip(), "structured": True}
        return ("met" if score == 100 else "partial", score, [_evidence_record(source, [requirement_id])], str(parameters.get("language")))
    if evaluator == "research":
        publications = cv.get("publications") or []
        projects = [item for item in cv.get("projects") or [] if isinstance(item, dict) and "research" in str(item.get("description") or "").casefold()]
        minimum = int(parameters.get("minimum_count", 1))
        count = len(publications) + len(projects)
        score = min(count / minimum, 1.0) * 100.0
        evidence = [{"evidence_id": f"publications:{index}", "document": "cv", "section": "publications", "text": str(item.get("title") or ""), "matched_requirement_ids": [requirement_id], "match_type": "exact", "confidence": 0.9} for index, item in enumerate(publications) if isinstance(item, dict)]
        return ("met" if count >= minimum else "partial" if count else "not_met", score, evidence, "research evidence")
    if evaluator in {"management", "domain"}:
        needle = normalize_token(parameters.get("responsibility") or parameters.get("domain"))
        matches = []
        for index, item in enumerate(cv.get("experience") or []):
            text = normalize_token(f"{item.get('job_title', '')} {item.get('description', '')}") if isinstance(item, dict) else ""
            signal = evaluator == "management" and any(value in text.replace("_", " ") for value in ("managed", "led", "负责", "管理"))
            if (needle and needle in text) or signal:
                matches.append(_evidence_record({"section": "experience", "index": index, "text": str(item.get("description") or item.get("job_title") or ""), "structured": True}, [requirement_id]))
        return ("met" if matches else "not_met", 100.0 if matches else 0.0, matches, needle.replace("_", " "))
    if evaluator == "license":
        license_name = normalize_token(parameters.get("license") or parameters.get("canonical_skill"))
        evidence = []
        for index, item in enumerate(cv.get("certifications") or []):
            if isinstance(item, dict) and license_name in normalize_token(item.get("name")):
                evidence.append(_evidence_record({"section": "certifications", "index": index, "text": str(item.get("name")), "structured": True}, [requirement_id]))
        return ("met" if evidence else "not_met", 100.0 if evidence else 0.0, evidence, license_name.replace("_", " "))
    return "unknown", None, [], str(parameters.get("text") or evaluator)


# Scores the weighted average of evaluable role-specific requirements.
def _score_specific(
    config: dict[str, Any],
    cv: dict[str, Any],
    relation_resolver: SkillRelationResolver | None,
) -> dict[str, Any]:
    settings = config["dimensions"]["job_specific_match"]
    if not settings["active"]:
        return _inactive_dimension("job_specific_match", settings)
    sources = _skill_sources(cv)
    requirements: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    evaluated: list[tuple[float, float]] = []
    met_names: list[str] = []
    gap_names: list[str] = []
    unknown_count = 0
    for item in config["job_specific_requirements"]:
        requirement_id = str(item["requirement_id"])
        status, score, item_evidence, text = _evaluate_specific(item, cv, sources, relation_resolver)
        requirements.append({"requirement_id": requirement_id, "text": text, "source": {"document": "jd", "section": "job_specific_requirements"}})
        evidence.extend(item_evidence)
        if score is None:
            unknown_count += 1
        else:
            evaluated.append((float(item.get("weight", 1.0)), score))
        if status == "met":
            met_names.append(text)
        else:
            gap_names.append(text)
            gaps.append({"requirement_id": requirement_id, "reason_code": "REQUIREMENT_UNKNOWN" if status == "unknown" else "NO_EXPLICIT_CV_EVIDENCE", "text": f"No sufficient evidence for {text}."})
    denominator = sum(weight for weight, _ in evaluated)
    score = sum(weight * value for weight, value in evaluated) / denominator if denominator else 0.0
    status = "unknown" if not evaluated else "met" if not gaps else "partial" if evidence else "not_met"
    confidence = 0.0 if not evaluated else max(0.0, 90.0 * (len(evaluated) / len(requirements)))
    summary = f"Job-Specific Match: {_round(score)}/100. Met: {', '.join(met_names) or 'none'}. Partial or missing: {', '.join(gap_names) or 'none'}."
    return _dimension(
        "job_specific_match",
        settings,
        score,
        status,
        requirements,
        evidence,
        gaps,
        "DR-SPECIFIC-001",
        summary,
        {"met": met_names, "gaps": gap_names, "unknown_count": unknown_count},
        confidence,
    )


# Evaluates one mandatory rule without contributing to capability score.
# Builds one CV-sourced evidence record for an eligibility rule decision.
def _cv_evidence(section: str, text: str, rule_id: str, index: int = 0) -> dict[str, Any]:
    return _evidence_record(
        {"section": section, "index": index, "text": text, "structured": True},
        [rule_id],
    )



# Evaluates one mandatory rule without contributing to capability score.
def _evaluate_eligibility_rule(
    rule: dict[str, Any],
    config: dict[str, Any],
    cv: dict[str, Any],
    relevant_years: float,
    core_matches: dict[str, tuple[float, dict[str, Any] | None]],
) -> dict[str, Any]:
    rule_id = str(rule.get("rule_id"))
    parameters = rule.get("parameters") or {}
    status, reason, evidence = "unknown", "CV_EVIDENCE_MISSING", []
    requirement = rule_id.replace("_", " ")
    if rule_id == "work_authorization":
        authorization = cv.get("work_authorization")
        value = str(authorization.get("status") or "") if isinstance(authorization, dict) else ""
        if value:
            evidence = [_cv_evidence("work_authorization", value, rule_id)]
        if value in {"citizen", "permanent_resident", "has_work_permit"}:
            status, reason = "met", "REQUIREMENT_MET"
        elif value == "requires_sponsorship":
            status, reason = "not_met", "WORK_AUTHORIZATION_NOT_MET"
        requirement = f"Work authorization for {parameters.get('target_region') or 'the target region'}"
    elif rule_id.startswith("mandatory_language"):
        language = str(parameters.get("language") or "")
        candidate = next((item for item in cv.get("languages") or [] if isinstance(item, dict) and str(item.get("language") or "").casefold() == language.casefold()), None)
        requirement = f"{language} {parameters.get('level') or ''}".strip()
        if candidate:
            candidate_level = candidate.get("level")
            evidence = [_cv_evidence("languages", f"{language}: {candidate_level or 'level unknown'}", rule_id)]
            required_level = parameters.get("level")
            if not candidate_level or not required_level:
                status, reason = "unknown", "LANGUAGE_LEVEL_UNKNOWN"
            elif _LANGUAGES.get(str(candidate_level), -1) >= _LANGUAGES.get(str(required_level), 0):
                status, reason = "met", "REQUIREMENT_MET"
            else:
                status, reason = "not_met", "LANGUAGE_LEVEL_NOT_MET"
    elif rule_id == "mandatory_degree":
        required = _degree_level(parameters.get("minimum_degree"))
        records = [item for item in cv.get("education") or [] if isinstance(item, dict)]
        levels = [_degree_level(item.get("degree_level") or item.get("degree")) for item in records]
        requirement = f"Mandatory degree: {parameters.get('minimum_degree') or 'degree'}"
        evidence = [_cv_evidence("education", str(item.get("degree") or ""), rule_id, idx) for idx, item in enumerate(records[:3]) if item.get("degree")]
        if not records:
            status, reason = "unknown", "CV_EVIDENCE_MISSING"
        elif required is None or max((value for value in levels if value is not None), default=-1) >= required:
            status, reason = "met", "REQUIREMENT_MET"
        else:
            status, reason = "not_met", "DEGREE_NOT_MET"
    elif rule_id == "mandatory_field_of_study":
        records = [item for item in cv.get("education") or [] if isinstance(item, dict)]
        majors = [str(item.get("major")) for item in records if item.get("major")]
        requirement = f"Mandatory field of study: {parameters.get('field_of_study') or 'any listed major'}"
        evidence = [
            _cv_evidence("education", f"{item.get('degree') or 'Degree'} - {item.get('major')}", rule_id, idx)
            for idx, item in enumerate(records[:3])
            if item.get("major")
        ]
        if not records:
            status, reason = "unknown", "CV_EVIDENCE_MISSING"
        elif not majors:
            status, reason = "unknown", "CV_MAJOR_MISSING"
        elif _fields_satisfied(parameters.get("field_of_study"), majors):
            status, reason = "met", "REQUIREMENT_MET"
        else:
            status, reason = "not_met", "FIELD_OF_STUDY_NOT_MET"
    elif rule_id == "mandatory_education":
        required = _degree_level(parameters.get("minimum_degree"))
        records = [item for item in cv.get("education") or [] if isinstance(item, dict)]
        levels = [_degree_level(item.get("degree_level") or item.get("degree")) for item in records]
        majors = [str(item.get("major")) for item in records if item.get("major")]
        evidence = [_cv_evidence("education", str(item.get("degree") or item.get("major") or ""), rule_id, idx) for idx, item in enumerate(records[:3]) if item.get("degree") or item.get("major")]
        required_certs = {normalize_token(value) for value in parameters.get("certifications") or []}
        candidate_certs = {
            normalize_token(item.get("name"))
            for item in cv.get("certifications") or []
            if isinstance(item, dict)
        }
        requirement = f"Mandatory {parameters.get('minimum_degree') or 'education'}"
        if not records:
            status, reason = "unknown", "CV_EVIDENCE_MISSING"
        elif (
            (required is None or max((value for value in levels if value is not None), default=-1) >= required)
            and _fields_satisfied(parameters.get("field_of_study"), majors)
            and required_certs.issubset(candidate_certs)
        ):
            status, reason = "met", "REQUIREMENT_MET"
        else:
            status, reason = "not_met", "EDUCATION_REQUIREMENT_NOT_MET"
    elif rule_id in {"mandatory_license", "mandatory_certification"}:
        required_name = normalize_token(parameters.get("license") or parameters.get("certification"))
        candidate_certs = [
            normalize_token(item.get("name"))
            for item in cv.get("certifications") or []
            if isinstance(item, dict) and item.get("name")
        ]
        requirement = f"Mandatory {required_name.replace('_', ' ')}"
        evidence = [_cv_evidence("certifications", name, rule_id, idx) for idx, name in enumerate(candidate_certs[:3])]
        if not candidate_certs:
            status, reason = "unknown", "CV_EVIDENCE_MISSING"
        elif any(required_name in value for value in candidate_certs):
            status, reason = "met", "REQUIREMENT_MET"
        else:
            status, reason = "not_met", "CERTIFICATION_REQUIREMENT_NOT_MET"
    elif rule_id == "minimum_relevant_experience":
        minimum = float(parameters.get("minimum_years", 0))
        requirement = f"At least {minimum:g} years relevant experience"
        if relevant_years > 0:
            evidence = [_cv_evidence("experience", f"{relevant_years:g} dated relevant years", rule_id)]
        if relevant_years <= 0:
            status, reason = "unknown", "DATED_EXPERIENCE_MISSING"
        elif relevant_years >= minimum:
            status, reason = "met", "REQUIREMENT_MET"
        else:
            status, reason = "not_met", "MINIMUM_EXPERIENCE_NOT_MET"
    elif rule_id in {"minimum_must_skill_count", "minimum_must_skill_coverage"}:
        strengths = [strength for strength, _ in core_matches.values()]
        evidence = []
        for idx, (requirement_id, (strength, source)) in enumerate(core_matches.items()):
            if strength > 0 and source and source.get("text"):
                evidence.append(_cv_evidence(str(source.get("section") or "cv"), str(source.get("text")), rule_id, idx))
                if len(evidence) >= 3:
                    break
        if not strengths:
            status, reason = "unknown", "SKILL_EVIDENCE_MISSING"
        elif rule_id.endswith("count"):
            status = "met" if sum(value > 0 for value in strengths) >= int(parameters.get("minimum_count", 0)) else "not_met"
            reason = "REQUIREMENT_MET" if status == "met" else "MINIMUM_SKILL_COUNT_NOT_MET"
        else:
            coverage = sum(strengths) / len(strengths)
            status = "met" if coverage >= float(parameters.get("minimum_coverage", 0)) else "not_met"
            reason = "REQUIREMENT_MET" if status == "met" else "MINIMUM_SKILL_COVERAGE_NOT_MET"
    return {"rule_id": rule_id, "status": status, "reason_code": reason, "requirement": requirement, "evidence": evidence}



def _evaluate_eligibility(
    config: dict[str, Any],
    cv: dict[str, Any],
    relevant_years: float,
    core_matches: dict[str, tuple[float, dict[str, Any] | None]],
) -> dict[str, Any]:
    results = [
        _evaluate_eligibility_rule(rule, config, cv, relevant_years, core_matches)
        for rule in config["eligibility_rules"]
        if rule.get("mandatory", True)
    ]
    status = "failed" if any(item["status"] == "not_met" for item in results) else "needs_review" if any(item["status"] == "unknown" for item in results) else "passed"
    return {"status": status, "results": results}


# Adds a deterministic fixed-template interview question candidate.
def _question(
    candidates: list[dict[str, Any]],
    template_id: str,
    priority: str,
    dimension_id: str,
    reason_code: str,
    requirement_ids: list[str],
    text: str,
    variables: dict[str, Any],
) -> None:
    normalized = json.dumps(variables, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    identity = hashlib.sha256(f"{template_id}:{normalized}".encode("utf-8")).hexdigest()[:24]
    candidates.append(
        {
            "question_id": identity,
            "template_id": template_id,
            "priority": priority,
            "dimension_id": dimension_id,
            "trigger_reason_code": reason_code,
            "trigger_requirement_ids": requirement_ids,
            "question": text,
            "variables": variables,
        }
    )


# Selects up to six actionable prompts in the PRD trigger order.
# Selects up to six actionable prompts, sourcing evidence prompts from their owning dimensions.
def _build_questions(
    config: dict[str, Any],
    dimensions: list[dict[str, Any]],
    eligibility: dict[str, Any],
    relevant_years: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    by_id = {
        item["dimension_id"]: item
        for item in dimensions
        if isinstance(item.get("dimension_id"), str)
    }
    unknown = next((item for item in eligibility["results"] if item["status"] == "unknown"), None)
    if unknown:
        requirement = unknown["requirement"]
        _question(candidates, "IQ-ELIGIBILITY-001", "high", "eligibility", unknown["reason_code"], [unknown["rule_id"]], f"The application does not clearly confirm {requirement}. Could you confirm your current status for this requirement?", {"requirement": requirement})
    core = by_id.get("core_skill_match") or dimensions[0]
    skill_lookup = {item["requirement_id"]: item["text"] for item in core["requirements"]}
    skill_weights = {str(item["skill_id"]): float(item.get("weight", 1.0)) for item in config["must_skills"]}
    for gap in sorted(core["gaps"], key=lambda item: (-skill_weights.get(item["requirement_id"], 0), item["requirement_id"])):
        requirement = skill_lookup.get(gap["requirement_id"], gap["requirement_id"])
        _question(candidates, "IQ-MISSING-001", "high", "core_skill_match", gap["reason_code"], [gap["requirement_id"]], f"We could not find clear evidence of {requirement} in your CV. Do you have relevant experience? If so, please describe a specific example.", {"requirement": requirement})
    active = [item for item in dimensions if item["active"]]
    if active:
        lowest = min(active, key=lambda item: (item["score"], DIMENSION_IDS.index(item["dimension_id"])))
        if lowest["dimension_id"] == "core_skill_match" and lowest["evidence"]:
            evidence = lowest["evidence"][0]
            skill = skill_lookup.get(evidence["matched_requirement_ids"][0], "this skill")
            context = evidence["section"]
            _question(candidates, "IQ-SKILL-DEPTH-001", "medium", lowest["dimension_id"], "LOWEST_ACTIVE_DIMENSION", evidence["matched_requirement_ids"], f"Your CV mentions using {skill} in {context}. Please describe your responsibility, the main challenge, the approach you took, and the outcome.", {"skill": skill, "context": context})
    experience_dim = by_id.get("relevant_experience")
    if isinstance(experience_dim, dict):
        achievement_evidence = next(
            (
                item
                for item in experience_dim.get("evidence") or []
                if _METRIC_PATTERN.search(item.get("text") or "") and not _PROTECTED_TEXT_PATTERN.search(item.get("text") or "")
            ),
            None,
        )
        if achievement_evidence:
            achievement = achievement_evidence["text"]
            _question(candidates, "IQ-IMPACT-001", "medium", "relevant_experience", "QUANTIFIED_ACHIEVEMENT_VERIFY", ["quantified_impact"], f"Your CV mentions {achievement}. What metric was used, what was your personal contribution, and what was the final business or technical impact?", {"achievement": achievement})
    experience_rule = next((rule for rule in config["eligibility_rules"] if rule.get("rule_id") == "minimum_relevant_experience"), None)
    if experience_rule:
        required = float(experience_rule["parameters"]["minimum_years"])
        if relevant_years < required:
            domain = "relevant"
            _question(candidates, "IQ-DURATION-001", "high", "relevant_experience", "MINIMUM_EXPERIENCE_GAP", ["minimum_relevant_experience"], f"This role requests at least {required:g} years of {domain} experience. Please walk us through your most relevant responsibilities and their duration.", {"required_years": required, "domain": domain})
    role = by_id.get("role_seniority_fit")
    if isinstance(role, dict) and role["active"] and role["score"] < 100:
        responsibility = str(config.get("target_seniority") or "the target role")
        _question(candidates, "IQ-SENIORITY-001", "medium", "role_seniority_fit", "SENIORITY_GAP", ["target_seniority"], f"This role requires responsibility for {responsibility}. Please describe a situation where you owned a similar responsibility, including your decisions, collaborators, and outcome.", {"responsibility": responsibility})
    job_dim = by_id.get("job_specific_match")
    if isinstance(job_dim, dict):
        for gap in job_dim.get("gaps") or []:
            requirement = next((item["text"] for item in job_dim["requirements"] if item["requirement_id"] == gap["requirement_id"]), gap["requirement_id"])
            _question(candidates, "IQ-JD-REQUIREMENT-001", "medium", "job_specific_match", gap["reason_code"], [gap["requirement_id"]], f"This role requires {requirement}. Please describe a specific example where you demonstrated this capability.", {"requirement": requirement})
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        key = (item["template_id"], json.dumps(item["variables"], ensure_ascii=False, sort_keys=True))
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)
    maximum = min(6, int(config.get("interview_question_policy", {}).get("max_questions", 6)))
    return deduplicated[:maximum]
def _summaries(dimensions: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    strengths = [
        f"{item['label']}: {item['score']:.2f}/100"
        for item in sorted(
            (value for value in dimensions if value["active"] and value["score"] >= 60),
            key=lambda value: (-value["score"], DIMENSION_IDS.index(value["dimension_id"])),
        )[:3]
    ]
    gaps: list[str] = []
    for dimension in dimensions:
        for gap in dimension["gaps"]:
            if gap["text"] not in gaps:
                gaps.append(gap["text"])
            if len(gaps) == 3:
                return strengths, gaps
    return strengths, gaps


# Matches one CV parser payload against one effective job configuration.
def match_candidate(
    cv_structured_data: dict[str, Any],
    effective_config: EffectiveConfig,
    reference_date: date | str,
    relation_resolver: SkillRelationResolver | None = None,
) -> dict[str, Any]:
    reference = date.fromisoformat(reference_date) if isinstance(reference_date, str) else reference_date
    config = effective_config.config
    core, core_matches = _score_core(config, cv_structured_data, relation_resolver)
    experience, relevant_years = _score_experience(config, cv_structured_data, reference)
    dimensions = [
        core,
        experience,
        _score_role(config, cv_structured_data),
        _score_education(config, cv_structured_data),
        _score_specific(config, cv_structured_data, relation_resolver),
    ]
    total = _round(sum(float(item["score"]) * item["normalized_weight"] for item in dimensions if item["active"]))
    confidence = _round(sum(item["confidence"] * item["normalized_weight"] for item in dimensions if item["active"]))
    bands = config["fit_bands"]
    fit_band = "high" if total >= float(bands["high_min"]) else "medium" if total >= float(bands["medium_min"]) else "low"
    eligibility = _evaluate_eligibility(config, cv_structured_data, relevant_years, core_matches)
    strengths, gaps = _summaries(dimensions)
    return {
        "schema_version": config["schema_version"],
        "algorithm_version": config["algorithm_version"],
        "match_score": total,
        "fit_band": fit_band,
        "eligibility": eligibility,
        "evidence_confidence": confidence,
        "radar_dimensions": dimensions,
        "radar_summary": {item["dimension_id"]: item["score"] for item in dimensions},
        "top_strengths": strengths,
        "key_gaps": gaps,
        "interview_questions": _build_questions(config, dimensions, eligibility, relevant_years),
        "metadata": {"config_hash": effective_config.config_hash, "reference_date": reference.isoformat()},
    }
