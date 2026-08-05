from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.services.skill_matcher import SkillMatcherService


class ScorerService:
    """Deterministic scorer with no LLM dependency."""

    def __init__(self, skill_matcher: SkillMatcherService) -> None:
        self.skill_matcher = skill_matcher

    def score_candidate(self, extracted_data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        filters = config.get("hard_filters", {})
        filter_result = self._apply_hard_filters(extracted_data, filters)
        hard_filter_status = "passed" if filter_result["passed"] else "failed"

        required_skills = config.get("required_skills", [])
        match = self.skill_matcher.match(
            candidate_skills=extracted_data.get("skills", []),
            required_skills=required_skills,
            experience_items=extracted_data.get("experience", []),
        )
        experience_match = self._experience_match_score(extracted_data, config)
        education_match = self._education_match_score(extracted_data, config)
        research_quality = self._research_quality_score(extracted_data.get("publications", []))
        experience_quality = float(match["quality_score"])

        dimension_scores = {
            "skill_match": float(match["score"]),
            "experience_match": experience_match,
            "education_match": education_match,
            "research_quality": research_quality,
            "experience_quality": experience_quality,
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
            match = self.skill_matcher.match(extracted_data.get("skills", []), required_skills, [])
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

    def _has_required_degree(self, extracted_data: dict[str, Any], required_degrees: list[str]) -> bool:
        education = extracted_data.get("education", [])
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
