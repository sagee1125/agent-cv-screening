from __future__ import annotations

from typing import Any

from app.core.taxonomy import SkillTaxonomyLoader


ROLE_SCORES = {
    "主導": 15,
    "负责": 10,
    "負責": 10,
    "参与": 5,
    "參與": 5,
}

SCALE_SCORES = {
    "百萬": 20,
    "百万": 20,
    "千萬": 30,
    "千万": 30,
    "億": 40,
    "亿": 40,
}


class SkillMatcherService:
    def __init__(self, taxonomy: SkillTaxonomyLoader) -> None:
        self.taxonomy = taxonomy
        if not self.taxonomy.nodes:
            self.taxonomy.load()

    def match(
        self,
        candidate_skills: list[str],
        required_skills: list[str],
        experience_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_candidate = {
            skill: self.taxonomy.normalize_skill(skill) or skill.strip()
            for skill in candidate_skills
            if skill and skill.strip()
        }
        normalized_required = {
            skill: self.taxonomy.normalize_skill(skill) or skill.strip()
            for skill in required_skills
            if skill and skill.strip()
        }

        hits: list[dict[str, str]] = []
        misses: list[str] = []
        candidate_canonical = set(normalized_candidate.values())

        for original_required, canonical_required in normalized_required.items():
            matched_skill = self._find_match(canonical_required, candidate_canonical)
            if matched_skill:
                hits.append({"required": original_required, "matched_with": matched_skill})
            else:
                misses.append(original_required)

        hit_rate = (len(hits) / len(normalized_required) * 100) if normalized_required else 0.0
        quality_score = self._quality_score(experience_items or [])
        score = round((hit_rate * 0.7) + (quality_score * 0.3), 2)
        return {
            "score": score,
            "hit_rate": round(hit_rate, 2),
            "quality_score": quality_score,
            "hits": hits,
            "misses": misses,
        }

    def _find_match(self, required: str, candidate_values: set[str]) -> str | None:
        for candidate_skill in candidate_values:
            if candidate_skill == required or self.taxonomy.related(candidate_skill, required):
                return candidate_skill
        return None

    def _quality_score(self, experiences: list[dict[str, Any]]) -> float:
        if not experiences:
            return 0.0

        per_experience_scores: list[int] = []
        for item in experiences:
            description = str(item.get("description", ""))
            score = 0
            for keyword, value in SCALE_SCORES.items():
                if keyword in description:
                    score += value
            for keyword, value in ROLE_SCORES.items():
                if keyword in description:
                    score += value
            per_experience_scores.append(min(score, 100))

        return round(sum(per_experience_scores) / len(per_experience_scores), 2)
