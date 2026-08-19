from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

from app.config import settings
from app.services.jd_parser.prompts import (
    JD_SKILL_REFINER_OUTPUT_SCHEMA,
    JD_SKILL_REFINER_SYSTEM_PROMPT,
    build_jd_skill_refiner_user_prompt,
)
from app.services.jd_parser.providers import (
    JDEnrichmentProvider,
    build_enrichment_provider,
    normalize_mode,
)


class JDParserService:
    """Rule-based JD parser with optional pluggable enrichment providers.

    Modes:
    - rule: deterministic rule-based parsing (default).
    - hybrid: rule parsing + LLM skill refinement via the shared LLM client.
    - qwen: rule parsing + local Qwen3-0.6B overview extraction.
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

    SKILL_SYNONYMS: dict[str, list[str]] = {
        "javascript": ["javascript", "js"],
        "typescript": ["typescript", "ts"],
        "node.js": ["node.js", "nodejs", "node"],
        "react": ["react", "reactjs", "react.js"],
        "postgresql": ["postgresql", "postgres", "psql"],
        "rest api": ["rest api", "restful api", "restful"],
        "c#": ["c#", "csharp"],
        "c++": ["c++", "cpp"],
    }

    MUST_SECTION_MARKERS = (
        "requirement",
        "qualification",
        "must have",
        "required",
        "what you need",
    )
    PREFERRED_SECTION_MARKERS = ("preferred", "nice to have", "plus", "bonus")
    RESPONSIBILITY_SECTION_MARKERS = ("responsibilit", "what you will do", "you will")

    MUST_CUES = ("must", "required", "mandatory", "need to", "at least")
    PREFERRED_CUES = ("preferred", "nice to have", "plus", "bonus", "good to have")
    IGNORE_LINE_CUES = (
        "equal opportunity",
        "about us",
        "who we are",
        "benefits",
        "salary",
        "compensation",
    )
    SKILL_INTRO_PATTERNS = [
        re.compile(r"(?:experience with|proficient in|knowledge of|familiar with)\s+(.+)$"),
        re.compile(r"(?:hands[- ]on(?: experience)? with|expertise in)\s+(.+)$"),
        re.compile(r"(?:熟悉|精通|了解|掌握)\s*(.+)$"),
    ]
    CONNECTOR_SPLIT_RE = re.compile(r"[,/]|(?:\band\b)|(?:\bor\b)")
    TOKEN_CLEAN_RE = re.compile(r"[^a-z0-9+.#\-\s]")

    def _extract_skills(self, text: str) -> tuple[list[str], list[str]]:
        lowered = self._clean_text(text)
        sections = self._split_sections(lowered)

        must_scores: Counter[str] = Counter()
        preferred_scores: Counter[str] = Counter()

        for section_name, lines in sections.items():
            for line in lines:
                if self._should_ignore_line(line):
                    continue
                skills = self._extract_candidates_from_line(line)
                if not skills:
                    continue

                target, weight = self._line_target_and_weight(section_name, line)
                if target == "preferred":
                    preferred_scores.update({skill: weight for skill in skills})
                else:
                    must_scores.update({skill: weight for skill in skills})

        must = self._rank_skills(must_scores)
        preferred = self._rank_skills(preferred_scores, excluded=set(must))

        if not must or not preferred:
            combined = must_scores + preferred_scores
            ranked_all = self._rank_skills(combined, excluded=set(must + preferred), limit=10)
            if not must:
                must = ranked_all[:5]
            if not preferred:
                preferred = ranked_all[:5]

        return must[:5], preferred[:5]

    def _clean_text(self, text: str) -> str:
        squashed = re.sub(r"[ \t]+", " ", text or "")
        squashed = squashed.replace("\r\n", "\n").replace("\r", "\n")
        return squashed.lower().strip()

    def _split_sections(self, text: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {"must": [], "preferred": [], "responsibility": [], "other": []}
        current_section = "other"
        for raw_line in text.split("\n"):
            line = raw_line.strip(" -*\t")
            if not line:
                continue
            matched_section, remainder = self._match_section_line(line)
            if matched_section:
                current_section = matched_section
                if remainder:
                    sections[current_section].append(remainder)
                continue
            sections[current_section].append(line)
        return sections

    def _match_section_line(self, line: str) -> tuple[str | None, str]:
        marker_groups: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("must", self.MUST_SECTION_MARKERS),
            ("preferred", self.PREFERRED_SECTION_MARKERS),
            ("responsibility", self.RESPONSIBILITY_SECTION_MARKERS),
        )
        for section_name, markers in marker_groups:
            for marker in markers:
                position = line.find(marker)
                if position == -1:
                    continue
                remainder = line[position + len(marker) :].lstrip(" :.-\t").strip()
                other_markers = tuple(
                    m
                    for target_name, target_markers in marker_groups
                    if target_name != section_name
                    for m in target_markers
                )
                remainder = self._truncate_on_markers(remainder, other_markers)
                return section_name, remainder
        return None, ""

    @staticmethod
    def _truncate_on_markers(text: str, markers: tuple[str, ...]) -> str:
        cut_positions = [text.find(marker) for marker in markers if marker and text.find(marker) >= 0]
        if not cut_positions:
            return text
        return text[: min(cut_positions)].rstrip(" :.-\t")

    def _should_ignore_line(self, line: str) -> bool:
        return any(cue in line for cue in self.IGNORE_LINE_CUES)

    def _line_target_and_weight(self, section_name: str, line: str) -> tuple[str, int]:
        has_must_cue = any(cue in line for cue in self.MUST_CUES)
        has_preferred_cue = any(cue in line for cue in self.PREFERRED_CUES)
        if has_preferred_cue:
            return "preferred", 2
        if has_must_cue:
            return "must", 2
        if section_name == "preferred":
            return "preferred", 1
        if section_name == "must":
            return "must", 2
        if section_name == "responsibility":
            return "must", 1
        return "must", 1

    def _extract_candidates_from_line(self, line: str) -> list[str]:
        candidates: set[str] = set()
        alias_to_canonical = self._alias_to_canonical()

        for canonical in self.COMMON_SKILLS:
            if re.search(rf"\b{re.escape(canonical)}\b", line):
                candidates.add(canonical)

        for alias, canonical in alias_to_canonical.items():
            if re.search(rf"\b{re.escape(alias)}\b", line):
                candidates.add(canonical)

        for pattern in self.SKILL_INTRO_PATTERNS:
            matched = pattern.search(line)
            if not matched:
                continue
            fragment = matched.group(1)[:100]
            for part in self.CONNECTOR_SPLIT_RE.split(fragment):
                normalized = self._normalize_skill(part, alias_to_canonical)
                if normalized:
                    candidates.add(normalized)

        return sorted(candidates)

    def _normalize_skill(self, raw: str, alias_to_canonical: dict[str, str]) -> str | None:
        cleaned = self.TOKEN_CLEAN_RE.sub(" ", raw.lower()).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^(with|in|on|of)\s+", "", cleaned)
        if not cleaned:
            return None
        if len(cleaned) < 2 or len(cleaned.split()) > 4:
            return None
        if cleaned in {"experience", "skills", "ability", "knowledge"}:
            return None
        return alias_to_canonical.get(cleaned, cleaned)

    def _rank_skills(self, scores: Counter[str], excluded: set[str] | None = None, limit: int = 5) -> list[str]:
        excluded = excluded or set()
        ranked = sorted(
            ((skill, score) for skill, score in scores.items() if skill not in excluded),
            key=lambda item: (-item[1], item[0]),
        )
        return [skill for skill, _ in ranked[:limit]]

    def _alias_to_canonical(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for canonical, aliases in self.SKILL_SYNONYMS.items():
            mapping[canonical] = canonical
            for alias in aliases:
                mapping[alias] = canonical
        return mapping

    def _extract_years(self, text: str) -> int | None:
        matched = re.search(r"(\d+)\+?\s+years?", text, flags=re.IGNORECASE)
        if not matched:
            return None
        try:
            return int(matched.group(1))
        except ValueError:
            return None

    def _build_preprocessed_payload(self, text: str) -> dict[str, Any]:
        normalized = self._clean_text(text)
        sections = self._split_sections(normalized)

        skill_scores: dict[str, dict[str, Any]] = {}
        for section_name, lines in sections.items():
            for line in lines:
                if self._should_ignore_line(line):
                    continue
                candidates = self._extract_candidates_from_line(line)
                if not candidates:
                    continue
                target, weight = self._line_target_and_weight(section_name, line)
                for skill in candidates:
                    skill_entry = skill_scores.setdefault(
                        skill,
                        {"must_score": 0, "preferred_score": 0, "evidence": []},
                    )
                    score_key = "must_score" if target == "must" else "preferred_score"
                    skill_entry[score_key] += weight
                    evidence = line[:180]
                    if evidence and evidence not in skill_entry["evidence"]:
                        skill_entry["evidence"].append(evidence)

        ranked_candidates = sorted(
            skill_scores.items(),
            key=lambda item: (
                -max(item[1]["must_score"], item[1]["preferred_score"]),
                -(item[1]["must_score"] + item[1]["preferred_score"]),
                item[0],
            ),
        )

        candidate_skills = [
            {
                "skill": skill,
                "must_score": data["must_score"],
                "preferred_score": data["preferred_score"],
                "suggested_bucket": "must" if data["must_score"] >= data["preferred_score"] else "preferred",
                "evidence": data["evidence"][:2],
            }
            for skill, data in ranked_candidates[:30]
        ]

        def _trim_lines(lines: list[str], max_lines: int = 12) -> list[str]:
            return [line[:220] for line in lines[:max_lines]]

        reduced_sections = {
            "must": _trim_lines([line for line in sections["must"] if not self._should_ignore_line(line)]),
            "preferred": _trim_lines([line for line in sections["preferred"] if not self._should_ignore_line(line)]),
            "responsibility": _trim_lines(
                [line for line in sections["responsibility"] if not self._should_ignore_line(line)],
                max_lines=8,
            ),
        }
        if not reduced_sections["must"] and not reduced_sections["preferred"]:
            reduced_sections["must"] = _trim_lines(
                [line for line in sections["other"] if not self._should_ignore_line(line)],
                max_lines=12,
            )

        compressed_text = "\n".join(
            [*reduced_sections["must"], *reduced_sections["preferred"], *reduced_sections["responsibility"]]
        )

        return {
            "preprocessed_for_llm": {
                "sections": reduced_sections,
                "candidate_skills": candidate_skills,
                "compressed_text": compressed_text[:2200],
                "char_count_before": len(text),
                "char_count_after": min(len(compressed_text), 2200),
            }
        }

    def _build_llm_refine_request(self, preprocessed_payload: dict[str, Any]) -> dict[str, Any]:
        llm_input = preprocessed_payload.get("preprocessed_for_llm", {})
        return {
            "system_prompt": JD_SKILL_REFINER_SYSTEM_PROMPT,
            "user_prompt": build_jd_skill_refiner_user_prompt(llm_input),
            "response_format": {"type": "json_object"},
            "expected_output_example": JD_SKILL_REFINER_OUTPUT_SCHEMA,
            "input_preview": json.dumps(llm_input, ensure_ascii=False)[:900],
        }

    async def parse_jd(
        self,
        jd_text: str,
        *,
        mode: str | None = None,
        enrichment_provider: JDEnrichmentProvider | None = None,
    ) -> dict[str, Any]:
        cleaned_input = (jd_text or "").strip()
        if not cleaned_input:
            return {
                "status": "invalid_input",
                "parse_path": "jd_placeholder",
                "error_message": "JD text is empty.",
                "structured_data": None,
            }

        mode = normalize_mode(mode or settings.jd_parser_mode)
        provider = enrichment_provider or build_enrichment_provider(mode)

        must_skills, preferred_skills = self._extract_skills(cleaned_input)
        years = self._extract_years(cleaned_input)
        normalized_cleaned = self._clean_text(cleaned_input)
        preprocessed_payload = self._build_preprocessed_payload(cleaned_input)
        llm_refine_request = self._build_llm_refine_request(preprocessed_payload)

        def build_skill_item(skill_name: str, order: int, weight: float) -> dict[str, Any]:
            return {
                "skill_id": f"{skill_name.replace(' ', '_')}_{order}",
                "display_name": skill_name.title(),
                "canonical_skill": skill_name.lower().replace(" ", "_"),
                "priority_order": order,
                "weight": weight,
                "provenance": {
                    "source_sentence": cleaned_input[:240],
                    "source_char_start": 0,
                    "source_char_end": min(len(cleaned_input), 240),
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
                    "is_mandatory": "english" in normalized_cleaned,
                    "provenance": cleaned_input[:120],
                }
            ],
            "education_requirement": {
                "minimum_degree": "bachelor" if "bachelor" in normalized_cleaned else "none",
                "field_of_study": None,
                "is_mandatory": "bachelor" in normalized_cleaned,
                "provenance": cleaned_input[:120],
            },
            "visa_requirement": {
                "requirement_type": "required" if "visa" in normalized_cleaned else "unknown",
                "target_region": None,
                "provenance": cleaned_input[:120],
            },
            "experience_requirement": {"minimum_years": years},
        }

        raw_llm_response: dict[str, Any] = {
            "note": "Rule-based parser with LLM-ready preprocessed payload",
            **preprocessed_payload,
            "llm_refine_request": llm_refine_request,
        }

        parse_path = "jd_preprocessed_rule_parser"
        if provider is not None:
            raw_llm_response["enrichment_provider"] = provider.name
            result = await provider.refine(
                jd_text=cleaned_input,
                preprocessed_payload=preprocessed_payload,
                rule_structured=structured_data,
            )
            raw_llm_response["enrichment_raw_output"] = result.raw_output
            if result.notes:
                raw_llm_response["enrichment_notes"] = result.notes
            if result.succeeded:
                parse_path = f"jd_{provider.name}_parser"
                if result.must_skills or result.preferred_skills:
                    structured_data["must_skills"] = result.must_skills
                    structured_data["preferred_skills"] = result.preferred_skills
                if result.jd_overview:
                    structured_data["jd_overview"] = result.jd_overview
            else:
                parse_path = f"jd_{provider.name}_fallback_rule_parser"

        return {
            "status": "success",
            "parse_path": parse_path,
            "error_message": None,
            "structured_data": structured_data,
            "raw_llm_response": raw_llm_response,
        }


def build_jd_parser_service() -> JDParserService:
    return JDParserService()
