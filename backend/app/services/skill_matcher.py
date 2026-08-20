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
        candidate_skills: list[Any],
        required_skills: list[str],
        experience_items: list[dict[str, Any]] | None = None,
        additional_skills: list[Any] | None = None,
    ) -> dict[str, Any]:
        # Normalize candidate skills from structured dicts, plain strings, or a mix.
        candidate_canonicals = self._candidate_canonical_set(candidate_skills)
        # Also fold in skills_used attached to each experience entry.
        for item in experience_items or []:
            for used in item.get("skills_used") or []:
                canonical = self._canonicalize_one(used)
                if canonical:
                    candidate_canonicals.add(canonical)
        # Fold in extra skill evidence (e.g. project skills_used) without affecting quality.
        for extra in additional_skills or []:
            canonical = self._canonicalize_one(extra)
            if canonical:
                candidate_canonicals.add(canonical)

        normalized_required = {
            skill: self._canonicalize_one(skill) or str(skill).strip().casefold().replace(" ", "_")
            for skill in required_skills
            if skill and str(skill).strip()
        }

        hits: list[dict[str, str]] = []
        misses: list[str] = []

        for original_required, canonical_required in normalized_required.items():
            matched_skill = self._find_match(canonical_required, candidate_canonicals)
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

    # Build the set of canonical candidate skills from mixed-format input.
    def _candidate_canonical_set(self, candidate_skills: list[Any]) -> set[str]:
        canonicals: set[str] = set()
        for item in candidate_skills or []:
            canonical = self._canonicalize_one(item)
            if canonical:
                canonicals.add(canonical)
        return canonicals

    # Canonicalize one skill item (dict with raw/canonical_skill, or a plain string).
    def _canonicalize_one(self, item: Any) -> str | None:
        if item is None:
            return None
        if isinstance(item, dict):
            canonical = item.get("canonical_skill")
            if isinstance(canonical, str) and canonical.strip():
                return canonical.strip().casefold().replace(" ", "_")
            raw = item.get("raw") or item.get("name") or item.get("skill") or item.get("display_name")
            if not raw:
                return None
            return self._canonicalize_token(str(raw))
        return self._canonicalize_token(str(item))

    # Canonicalize a raw token to a lowercase-underscore canonical id via taxonomy.
    def _canonicalize_token(self, token: str) -> str | None:
        text = token.strip()
        if not text:
            return None
        preserved = self.taxonomy.normalize_skill(text)
        if preserved:
            return preserved.casefold().replace(" ", "_")
        cleaned = " ".join(text.casefold().split())
        return cleaned.replace(" ", "_") if cleaned else None

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
