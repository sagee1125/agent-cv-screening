from __future__ import annotations

import re
from typing import Any


class JDParserService:
    """Dedicated JD parser service placeholder.

    NOTE:
    - JD parser logic has not been implemented yet.
    - This service exists to keep CV/JD parser responsibilities separated.
    """

    COMMON_SKILLS = [
        "python",
        "java",
        "javascript",
        "typescript",
        "react",
        "node.js",
        "node",
        "sql",
        "postgresql",
        "docker",
        "kubernetes",
        "aws",
        "gcp",
        "azure",
        "rest api",
        "fastapi",
        "django",
        "flask",
        "git",
    ]

    def _extract_skills(self, text: str) -> tuple[list[str], list[str]]:
        lowered = text.lower()
        must: list[str] = []
        preferred: list[str] = []
        for skill in self.COMMON_SKILLS:
            if skill in lowered:
                if len(must) < 5:
                    must.append(skill)
                elif len(preferred) < 5:
                    preferred.append(skill)
        if not must:
            must = ["communication", "problem solving"]
        if not preferred:
            preferred = ["team collaboration"]
        return must[:5], preferred[:5]

    def _extract_years(self, text: str) -> int | None:
        matched = re.search(r"(\d+)\+?\s+years?", text, flags=re.IGNORECASE)
        if not matched:
            return None
        try:
            return int(matched.group(1))
        except ValueError:
            return None

    async def parse_jd(self, jd_text: str) -> dict[str, Any]:
        cleaned = (jd_text or "").strip()
        if not cleaned:
            return {
                "status": "invalid_input",
                "parse_path": "jd_placeholder",
                "error_message": "JD text is empty.",
                "structured_data": None,
            }
        must_skills, preferred_skills = self._extract_skills(cleaned)
        years = self._extract_years(cleaned)

        def build_skill_item(skill_name: str, order: int, weight: float) -> dict[str, Any]:
            return {
                "skill_id": f"{skill_name.replace(' ', '_')}_{order}",
                "display_name": skill_name.title(),
                "canonical_skill": skill_name.lower().replace(" ", "_"),
                "priority_order": order,
                "weight": weight,
                "provenance": {
                    "source_sentence": cleaned[:240],
                    "source_char_start": 0,
                    "source_char_end": min(len(cleaned), 240),
                    "confidence": 0.75,
                },
            }

        structured_data: dict[str, Any] = {
            "must_skills": [build_skill_item(skill, idx + 1, 1.0) for idx, skill in enumerate(must_skills)],
            "preferred_skills": [
                build_skill_item(skill, idx + 1, 0.6) for idx, skill in enumerate(preferred_skills)
            ],
            "language_requirements": [
                {
                    "language": "English",
                    "level": "business",
                    "is_mandatory": "english" in cleaned.lower(),
                    "provenance": cleaned[:120],
                }
            ],
            "education_requirement": {
                "minimum_degree": "bachelor" if "bachelor" in cleaned.lower() else "none",
                "field_of_study": None,
                "is_mandatory": "bachelor" in cleaned.lower(),
                "provenance": cleaned[:120],
            },
            "visa_requirement": {
                "requirement_type": "required" if "visa" in cleaned.lower() else "unknown",
                "target_region": None,
                "provenance": cleaned[:120],
            },
            "experience_requirement": {"minimum_years": years},
        }

        return {
            "status": "success",
            "parse_path": "jd_basic_parser",
            "error_message": None,
            "structured_data": structured_data,
            "raw_llm_response": {"note": "Rule-based placeholder parser result"},
        }


def build_jd_parser_service() -> JDParserService:
    return JDParserService()
