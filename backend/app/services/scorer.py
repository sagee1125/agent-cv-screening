from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.services.skill_matcher import SkillMatcherService
from app.services.cv_parser.helpers import degree_to_level
from app.services.cv_parser.certifications import certifications_to_skills


# Rank order for language proficiency levels (higher is better).
_LANGUAGE_LEVEL_RANK = {"basic": 0, "business": 1, "fluent": 2, "native": 3}


class ScorerService:
    """Deterministic scorer with no LLM dependency."""

    def __init__(self, skill_matcher: SkillMatcherService) -> None:
        self.skill_matcher = skill_matcher

    def score_candidate(self, extracted_data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        filters = config.get("hard_filters", {})
        filter_result = self._apply_hard_filters(extracted_data, filters)
        hard_filter_status = "passed" if filter_result["passed"] else "failed"

        required_skills = config.get("required_skills", [])
        additional_skills = self._collect_additional_skills(extracted_data)
        match = self.skill_matcher.match(
            candidate_skills=extracted_data.get("skills", []),
            required_skills=required_skills,
            experience_items=extracted_data.get("experience", []),
            additional_skills=additional_skills,
        )
        experience_match = self._experience_match_score(extracted_data, config)
        education_match = self._education_match_score(extracted_data, config)
        research_quality = self._research_quality_score(extracted_data.get("publications", []))
        experience_quality = float(match["quality_score"])
        language_match = self._language_match_score(extracted_data, config)
        work_authorization_match = self._work_authorization_match_score(extracted_data, config)
        location_match = self._location_match_score(extracted_data, config)

        dimension_scores = {
            "skill_match": float(match["score"]),
            "experience_match": experience_match,
            "education_match": education_match,
            "research_quality": research_quality,
            "experience_quality": experience_quality,
            "language_match": language_match,
            "work_authorization_match": work_authorization_match,
            "location_match": location_match,
        }

        if hard_filter_status == "failed":
            total = Decimal("0.00")
            tier = self._assign_tier(total, config.get("tiers", []))
        else:
            total = self._weighted_total(dimension_scores, config.get("weights", {}))
            tier = self._assign_tier(total, config.get("tiers", []))

        interview_suggestions = self._build_interview_suggestions(
            dimension_scores=dimension_scores,
            hard_filter_status=hard_filter_status,
            rejection_reasons=filter_result["reasons"],
        )
        snapshot = {
            "dimension_scores": dimension_scores,
            "skill_match_details": {
                "hit": match["hits"],
                "miss": match["misses"],
                "quality": round(float(match["quality_score"]) / 100, 4),
            },
            "interview_suggestions": interview_suggestions,
            "hard_filter_status": hard_filter_status,
        }

        return {
            "dimension_scores": dimension_scores,
            "total_score": total,
            "tier": tier,
            "rejected": hard_filter_status == "failed",
            "rejection_reasons": filter_result["reasons"],
            "skill_match_details": snapshot["skill_match_details"],
            "full_snapshot": snapshot,
        }

    def rank(self, scored_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(scored_items, key=lambda item: (item["total_score"], item["candidate_id"]), reverse=True)
        for idx, item in enumerate(ordered, start=1):
            item["rank"] = idx
        return ordered

    def _apply_hard_filters(self, extracted_data: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        min_experience_years = float(filters.get("min_experience_years", 0))
        years = self._estimate_experience_years(
            extracted_data.get("experience", []),
            reference_date=str(filters.get("reference_date", "2026-01")),
        )
        if years < min_experience_years:
            reasons.append("insufficient_experience")

        min_required_skill_hits = int(filters.get("min_required_skill_hits", 0))
        required_skills = filters.get("required_skills", [])
        if required_skills:
            additional_skills = self._collect_additional_skills(extracted_data)
            match = self.skill_matcher.match(
                extracted_data.get("skills", []),
                required_skills,
                extracted_data.get("experience", []),
                additional_skills=additional_skills,
            )
            if len(match["hits"]) < min_required_skill_hits:
                reasons.append("insufficient_required_skills")

        required_degrees = filters.get("required_degrees", [])
        if required_degrees and not self._has_required_degree(extracted_data, required_degrees):
            reasons.append("education_requirement_not_met")

        return {"passed": not reasons, "reasons": reasons}

    def _experience_match_score(self, extracted_data: dict[str, Any], config: dict[str, Any]) -> float:
        expected = float(config.get("target_experience_years", 0))
        years = self._estimate_experience_years(
            extracted_data.get("experience", []),
            reference_date=str(config.get("experience_reference_date", "2026-01")),
        )
        if expected <= 0:
            return 100.0 if years > 0 else 0.0
        ratio = min(years / expected, 1.0)
        return round(ratio * 100, 2)

    def _education_match_score(self, extracted_data: dict[str, Any], config: dict[str, Any]) -> float:
        target_degrees: list[str] = config.get("target_degrees", [])
        if not target_degrees:
            return 100.0
        return 100.0 if self._has_required_degree(extracted_data, target_degrees) else 0.0

    def _language_match_score(self, extracted_data: dict[str, Any], config: dict[str, Any]) -> float:
        # Score how well candidate languages meet JD language requirements.
        requirements = config.get("language_requirements", []) or []
        if not requirements:
            return 100.0
        candidate_languages = {
            str(item.get("language") or "").casefold(): item
            for item in extracted_data.get("languages", []) or []
            if isinstance(item, dict) and item.get("language")
        }
        total_weight = 0.0
        earned = 0.0
        for req in requirements:
            if not isinstance(req, dict):
                continue
            name = str(req.get("language") or "").casefold()
            if not name:
                continue
            weight = 1.0 if req.get("is_mandatory") else 0.5
            total_weight += weight
            candidate = candidate_languages.get(name)
            if not candidate:
                continue
            required_level = req.get("level")
            candidate_level = candidate.get("level")
            if required_level and candidate_level:
                if _LANGUAGE_LEVEL_RANK.get(candidate_level, 0) >= _LANGUAGE_LEVEL_RANK.get(required_level, 0):
                    earned += weight
                else:
                    earned += weight * 0.5
            else:
                earned += weight
        if total_weight <= 0:
            return 100.0
        return round((earned / total_weight) * 100, 2)

    def _work_authorization_match_score(self, extracted_data: dict[str, Any], config: dict[str, Any]) -> float:
        # Score work authorization fit against JD visa requirement.
        visa_req = config.get("visa_requirement", {}) or {}
        requirement_type = ""
        if isinstance(visa_req, dict):
            requirement_type = str(visa_req.get("requirement_type") or "").casefold()
        if requirement_type != "required":
            return 100.0
        auth = extracted_data.get("work_authorization", {}) or {}
        status = ""
        if isinstance(auth, dict):
            status = str(auth.get("status") or "").casefold()
        if status in {"citizen", "permanent_resident", "has_work_permit"}:
            return 100.0
        if status == "requires_sponsorship":
            return 60.0
        if status == "unknown" or not status:
            return 80.0
        return 80.0

    def _location_match_score(self, extracted_data: dict[str, Any], config: dict[str, Any]) -> float:
        # Score location proximity between candidate and JD location.
        jd_location = config.get("location")
        if not jd_location or not isinstance(jd_location, dict):
            return 100.0
        cv_location = extracted_data.get("location")
        if not cv_location or not isinstance(cv_location, dict):
            return 50.0
        jd_country = str(jd_location.get("country") or "").casefold()
        jd_city = str(jd_location.get("city") or "").casefold()
        cv_country = str(cv_location.get("country") or "").casefold()
        cv_city = str(cv_location.get("city") or "").casefold()
        if jd_country and cv_country and jd_country == cv_country:
            if jd_city and cv_city and jd_city == cv_city:
                return 100.0
            return 60.0
        if not jd_country and not jd_city:
            return 100.0
        return 0.0

    @staticmethod
    def _research_quality_score(publications: list[dict[str, Any]]) -> float:
        if not publications:
            return 0.0
        score = 0
        for pub in publications:
            journal_text = f"{pub.get('journal', '')} {pub.get('title', '')}"
            lowered = journal_text.lower()
            if any(keyword in lowered for keyword in ("nature", "science", "neurips", "icml", "acl", "ieee")):
                score += 30
            else:
                score += 15
        return float(min(score, 100))

    def _build_interview_suggestions(
        self,
        *,
        dimension_scores: dict[str, float],
        hard_filter_status: str,
        rejection_reasons: list[str],
    ) -> list[dict[str, str]]:
        suggestions: list[dict[str, str]] = []
        if hard_filter_status == "failed":
            suggestions.append(
                {
                    "rule_id": "HF-001",
                    "severity": "high",
                    "text": f"Hard filter failed: {', '.join(rejection_reasons) or 'unknown reason'}",
                }
            )
        for key, score in dimension_scores.items():
            if score < 50:
                suggestions.append(
                    {
                        "rule_id": f"LOW-{key.upper()}",
                        "severity": "high",
                        "text": f"Dimension `{key}` is below 50. Probe depth and practical evidence.",
                    }
                )
            elif score < 70:
                suggestions.append(
                    {
                        "rule_id": f"MID-{key.upper()}",
                        "severity": "medium",
                        "text": f"Dimension `{key}` is between 50-70. Verify consistency and recency.",
                    }
                )
        if not suggestions:
            suggestions.append(
                {
                    "rule_id": "GEN-OK",
                    "severity": "low",
                    "text": "Candidate profile is balanced. Focus interview on role fit and team collaboration.",
                }
            )
        return suggestions

    @staticmethod
    def _collect_additional_skills(extracted_data: dict[str, Any]) -> list[str]:
        # Gather skills_used across projects plus skills derived from certifications.
        collected: list[str] = []
        for project in extracted_data.get("projects", []) or []:
            if not isinstance(project, dict):
                continue
            collected.extend(project.get("skills_used") or [])
        collected.extend(
            certifications_to_skills(extracted_data.get("certifications", []))
        )
        return collected

    def _has_required_degree(self, extracted_data: dict[str, Any], required_degrees: list[str]) -> bool:
        # Preferred path: compare normalized degree_level against required levels.
        education = extracted_data.get("education", [])
        required_levels = {degree_to_level(deg) for deg in required_degrees}
        required_levels.discard(None)
        if required_levels:
            candidate_levels = {
                item.get("degree_level") for item in education if item.get("degree_level")
            }
            if candidate_levels & required_levels:
                return True
        # Backward-compatible substring fallback for raw degree labels (e.g. "MSc", "硕士").
        flattened = " ".join(str(item.get("degree", "")) for item in education)
        return any(degree in flattened for degree in required_degrees)

    def _estimate_experience_years(self, experiences: list[dict[str, Any]], reference_date: str) -> float:
        total_months = 0
        reference = self._parse_year_month(reference_date) or datetime(2026, 1, 1)
        for item in experiences:
            start = self._parse_year_month(item.get("start_date"))
            end = self._parse_year_month(item.get("end_date")) or reference
            if not start:
                continue
            months = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += max(months, 0)
        return round(total_months / 12, 2)

    @staticmethod
    def _parse_year_month(value: Any) -> datetime | None:
        if not value:
            return None
        text = str(value).strip()
        for fmt in ("%Y-%m", "%Y/%m", "%Y.%m", "%Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def _weighted_total(self, dimension_scores: dict[str, float], weights: dict[str, float]) -> Decimal:
        effective_weights = {
            "skill_match": float(weights.get("skill_match", 0.35)),
            "experience_match": float(weights.get("experience_match", 0.2)),
            "education_match": float(weights.get("education_match", 0.15)),
            "research_quality": float(weights.get("research_quality", 0.15)),
            "experience_quality": float(weights.get("experience_quality", 0.15)),
            # New dimensions default to 0 so existing configs are unaffected.
            "language_match": float(weights.get("language_match", 0.0)),
            "work_authorization_match": float(weights.get("work_authorization_match", 0.0)),
            "location_match": float(weights.get("location_match", 0.0)),
        }
        total = Decimal("0")
        for dimension, score in dimension_scores.items():
            total += Decimal(str(score)) * Decimal(str(effective_weights.get(dimension, 0)))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _assign_tier(total_score: Decimal, tiers: list[dict[str, Any]]) -> str:
        score_value = float(total_score)
        if tiers:
            for tier in tiers:
                min_score = float(tier.get("min_score", 0))
                max_score = float(tier.get("max_score", 100))
                if min_score <= score_value <= max_score:
                    return str(tier.get("name", "Tier 4"))
        default_tiers = [
            {"name": "Tier 1", "min_score": 85, "max_score": 100},
            {"name": "Tier 2", "min_score": 70, "max_score": 84.99},
            {"name": "Tier 3", "min_score": 50, "max_score": 69.99},
            {"name": "Tier 4", "min_score": 0, "max_score": 49.99},
        ]
        for tier in default_tiers:
            if float(tier["min_score"]) <= score_value <= float(tier["max_score"]):
                return str(tier["name"])
        return "Tier 4"
