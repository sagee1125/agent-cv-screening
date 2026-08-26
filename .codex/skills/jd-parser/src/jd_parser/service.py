# Rule-based JD parser: skills, languages, education, visa, and experience.
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import json
import re
from typing import Any

from screening_core.paths import taxonomy_yaml_path
from screening_core.taxonomy import SkillTaxonomyLoader
from jd_parser.prompts import (
    JD_SKILL_REFINER_OUTPUT_SCHEMA,
    JD_SKILL_REFINER_SYSTEM_PROMPT,
    build_jd_skill_refiner_user_prompt,
)
from jd_parser.provenance import (
    empty_skill_provenance,
    find_cue_excerpt,
    find_source_excerpt,
)
from jd_parser.mode import normalize_mode
from jd_parser.providers.base import JDEnrichmentProvider


# Taxonomy category whose nodes are languages, not job skills.
_LANGUAGE_CATEGORY = "languages"
# Maximum skills kept in each must/preferred bucket after extraction or LLM refine.
MAX_SKILLS_PER_BUCKET = 10
# Rank used to keep the strongest stated language level.
_LANGUAGE_LEVEL_RANK = {"basic": 0, "business": 1, "fluent": 2, "native": 3}
# CJK and common aliases not always present on taxonomy language nodes.
_LANGUAGE_EXTRA_ALIASES: tuple[tuple[str, str], ...] = (
    ("英语", "English"),
    ("英語", "English"),
    ("英文", "English"),
    ("中文", "Chinese"),
    ("汉语", "Chinese"),
    ("漢語", "Chinese"),
    ("华语", "Chinese"),
    ("華語", "Chinese"),
    ("普通话", "Mandarin"),
    ("普通話", "Mandarin"),
    ("国语", "Mandarin"),
    ("國語", "Mandarin"),
    ("粤语", "Cantonese"),
    ("粵語", "Cantonese"),
    ("广东话", "Cantonese"),
    ("廣東話", "Cantonese"),
    ("日语", "Japanese"),
    ("日語", "Japanese"),
    ("日文", "Japanese"),
    ("韩语", "Korean"),
    ("韓語", "Korean"),
    ("韩文", "Korean"),
    ("法語", "French"),
    ("法语", "French"),
    ("德語", "German"),
    ("德语", "German"),
    ("西班牙语", "Spanish"),
    ("西班牙語", "Spanish"),
)


@lru_cache(maxsize=1)
def _default_taxonomy_loader() -> SkillTaxonomyLoader:
    """Load and cache the standard all-industry taxonomy loader."""
    loader = SkillTaxonomyLoader(str(taxonomy_yaml_path()))
    loader.load()
    return loader


# Maps Chinese digit characters to their integer values.
_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "兩": 2, "两": 2,
}


def _cn_numeral_to_int(raw: str) -> int | None:
    """Convert a Chinese numeral phrase (1-99) to an integer, or None if invalid."""
    if raw == "十":
        return 10
    if raw.startswith("十"):
        return 10 + _CN_DIGITS.get(raw[1:], 0)
    if "十" in raw:
        head, _, tail = raw.partition("十")
        tens = _CN_DIGITS.get(head, 0) * 10
        units = _CN_DIGITS.get(tail, 0) if tail else 0
        return tens + units
    return _CN_DIGITS.get(raw)


class JDParserService:
    """Rule-based JD parser with optional pluggable enrichment providers.

    Modes:
    - rule: deterministic rule-based parsing (default).
    - hybrid: rule parsing + LLM skill refinement via the shared LLM client.
    - qwen: rule parsing + local Qwen3-0.6B overview extraction.
    """

    def __init__(self, taxonomy_loader: SkillTaxonomyLoader | None = None) -> None:
        """Initialize skill and language token matchers from the taxonomy."""
        loader = taxonomy_loader or _default_taxonomy_loader()
        self.skill_synonyms: dict[str, list[str]] = {}
        self._token_to_canonical: dict[str, str] = {}
        self._language_token_to_canonical: dict[str, str] = {}

        for node in loader.nodes.values():
            display_name = self._language_output_name(node.skill)
            if node.category.strip().casefold() == _LANGUAGE_CATEGORY:
                self._index_language_token(node.skill, display_name)
                for alias in node.synonyms:
                    self._index_language_token(alias, display_name)
                continue
            canonical = node.skill.casefold()
            self.skill_synonyms[canonical] = [syn.casefold() for syn in node.synonyms]
            self._token_to_canonical[canonical] = canonical
            for alias in self.skill_synonyms[canonical]:
                self._token_to_canonical[alias] = canonical

        for alias, display_name in _LANGUAGE_EXTRA_ALIASES:
            self._index_language_token(alias, display_name)

        self.common_skills = sorted(self.skill_synonyms)
        self._skill_token_re = self._compile_token_regex(self._token_to_canonical)
        self._language_token_re = self._compile_token_regex(self._language_token_to_canonical)

    @staticmethod
    def _language_output_name(skill: str) -> str:
        """Map a taxonomy language node to the language_requirements display name."""
        if skill.strip().casefold() == "business english":
            return "English"
        return skill.strip()

    def _index_language_token(self, token: str, display_name: str) -> None:
        """Register one language alias against its canonical display name."""
        key = (token or "").strip().casefold()
        if key:
            self._language_token_to_canonical[key] = display_name

    @staticmethod
    def _compile_token_regex(token_map: dict[str, str]) -> re.Pattern[str]:
        """Compile a longest-first token matcher, or a never-matching pattern."""
        tokens = sorted(token_map, key=len, reverse=True)
        if not tokens:
            return re.compile(r"(?!)")
        pattern = r"(?<![a-z0-9])(?:" + "|".join(re.escape(token) for token in tokens) + r")(?![a-z0-9])"
        return re.compile(pattern)

    MUST_SECTION_MARKERS = (
        "requirement",
        "qualification",
        "must have",
        "required",
        "what you need",
    )
    PREFERRED_SECTION_MARKERS = ("preferred", "nice to have", "plus", "bonus")
    # Matches ASCII digits or short Chinese numerals used in year requirements.
    _NUMBER_PATTERN = r"(?:\d{1,2}|[一二三四五六七八九十兩两]{1,3})"
    RESPONSIBILITY_SECTION_MARKERS = ("responsibilit", "what you will do", "you will")

    MUST_CUES = ("must", "required", "mandatory", "need to", "at least")
    PREFERRED_CUES = (
        "preferred",
        "nice to have",
        "plus",
        "bonus",
        "good to have",
        "familiarity with",
        "familiar with",
    )
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
            ranked_all = self._rank_skills(
                combined,
                excluded=set(must + preferred),
                limit=MAX_SKILLS_PER_BUCKET * 2,
            )
            if not must:
                must = ranked_all[:MAX_SKILLS_PER_BUCKET]
            if not preferred:
                preferred = ranked_all[:MAX_SKILLS_PER_BUCKET]

        return must[:MAX_SKILLS_PER_BUCKET], preferred[:MAX_SKILLS_PER_BUCKET]

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
        for matched in self._skill_token_re.finditer(line):
            canonical = self._token_to_canonical.get(matched.group(0))
            if canonical and not self._is_language_value(canonical):
                candidates.add(canonical)

        for pattern in self.SKILL_INTRO_PATTERNS:
            matched = pattern.search(line)
            if not matched:
                continue
            fragment = matched.group(1)[:100]
            for part in self.CONNECTOR_SPLIT_RE.split(fragment):
                normalized = self._normalize_skill(part, self._token_to_canonical)
                if normalized:
                    candidates.add(normalized)

        return sorted(candidates)

    def _normalize_skill(self, raw: str, alias_to_canonical: dict[str, str]) -> str | None:
        cleaned = self.TOKEN_CLEAN_RE.sub(" ", raw.lower()).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^(with|in|on|of)\s+", "", cleaned)
        cleaned = cleaned.strip(" .,:;")
        if not cleaned:
            return None
        if len(cleaned) < 2 or len(cleaned.split()) > 4:
            return None
        if cleaned in {"experience", "skills", "ability", "knowledge"}:
            return None
        if self._is_language_value(cleaned):
            return None
        return alias_to_canonical.get(cleaned, cleaned)

    def _rank_skills(self, scores: Counter[str], excluded: set[str] | None = None, limit: int | None = None) -> list[str]:
        excluded = excluded or set()
        bucket_limit = limit if limit is not None else MAX_SKILLS_PER_BUCKET
        ranked = sorted(
            ((skill, score) for skill, score in scores.items() if skill not in excluded),
            key=lambda item: (-item[1], item[0]),
        )
        return [skill for skill, _ in ranked[:bucket_limit]]

    def _is_language_value(self, value: str) -> bool:
        """Return True when a token or skill name is a spoken/written language."""
        key = (value or "").strip().casefold().replace("_", " ")
        return key in self._language_token_to_canonical

    def _extract_language_requirements(self, text: str) -> list[dict[str, Any]]:
        """Extract language requirements from JD lines, separate from job skills."""
        lowered = self._clean_text(text)
        sections = self._split_sections(lowered)
        found: dict[str, dict[str, Any]] = {}
        order: list[str] = []

        for section_name, lines in sections.items():
            for line in lines:
                if self._should_ignore_line(line):
                    continue
                matched_names = self._languages_in_line(line)
                if not matched_names:
                    continue
                target, _ = self._line_target_and_weight(section_name, line)
                is_mandatory = target != "preferred"
                level = self._infer_language_level(line)
                for name in matched_names:
                    key = name.casefold()
                    if key not in found:
                        found[key] = {
                            "language": name,
                            "level": level,
                            "is_mandatory": is_mandatory,
                            "provenance": "",
                        }
                        order.append(key)
                        continue
                    current = found[key]
                    if is_mandatory:
                        current["is_mandatory"] = True
                    if _LANGUAGE_LEVEL_RANK.get(level, 0) > _LANGUAGE_LEVEL_RANK.get(current["level"], 0):
                        current["level"] = level

        return [found[key] for key in order]

    def _languages_in_line(self, line: str) -> list[str]:
        """Return canonical language names mentioned on a line, in mention order."""
        names: list[str] = []
        seen: set[str] = set()
        for matched in self._language_token_re.finditer(line):
            display = self._language_token_to_canonical.get(matched.group(0).casefold())
            if not display:
                continue
            key = display.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(display)
        return names

    def _infer_language_level(self, line: str) -> str:
        """Infer PRD language level from wording on the same line."""
        if re.search(r"native|mother tongue|母語|母语", line):
            return "native"
        if re.search(r"fluent|fluency|excellent|proficient|精通|流利|出色", line):
            return "fluent"
        if re.search(r"basic|beginner|basic level|基本", line):
            return "basic"
        if re.search(r"business english|working (?:knowledge|proficiency)|商務|商务", line):
            return "business"
        return "business"

    def _drop_language_skill_items(self, items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Remove spoken-language entries that leaked into a skill bucket."""
        kept: list[dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            labels = (
                str(item.get("canonical_skill") or ""),
                str(item.get("display_name") or ""),
                str(item.get("extracted_name") or ""),
            )
            if any(self._is_language_value(label) for label in labels if label.strip()):
                continue
            kept.append(item)
        for idx, item in enumerate(kept, start=1):
            item["priority_order"] = idx
        return kept

    @staticmethod
    def _skill_bucket_key(item: dict[str, Any]) -> str:
        """Return the canonical key used to dedupe skill items across buckets."""
        return str(item.get("canonical_skill") or item.get("extracted_name") or "").strip().casefold()

    def _backfill_refined_skills(
        self,
        structured_data: dict[str, Any],
        rule_must: list[dict[str, Any]],
        rule_preferred: list[dict[str, Any]],
    ) -> None:
        """Restore rule-extracted skills that LLM refinement dropped from either bucket."""
        must = list(structured_data.get("must_skills") or [])
        preferred = list(structured_data.get("preferred_skills") or [])
        seen = {key for key in (self._skill_bucket_key(item) for item in must + preferred) if key}

        def append_missing(bucket: list[dict[str, Any]], source: list[dict[str, Any]]) -> None:
            for item in source:
                key = self._skill_bucket_key(item)
                if not key or key in seen or len(bucket) >= MAX_SKILLS_PER_BUCKET:
                    continue
                bucket.append(dict(item))
                seen.add(key)

        append_missing(must, rule_must)
        append_missing(preferred, rule_preferred)
        for idx, item in enumerate(must, start=1):
            item["priority_order"] = idx
        for idx, item in enumerate(preferred, start=1):
            item["priority_order"] = idx
        structured_data["must_skills"] = must[:MAX_SKILLS_PER_BUCKET]
        structured_data["preferred_skills"] = preferred[:MAX_SKILLS_PER_BUCKET]

    def _needles_for_language(self, language: str) -> list[str]:
        """Collect display name and aliases used to locate a language mention."""
        needles: list[str] = []
        seen: set[str] = set()
        key = (language or "").strip().casefold()

        def add(value: str | None) -> None:
            text = (value or "").strip()
            if len(text) < 2:
                return
            folded = text.casefold()
            if folded in seen:
                return
            seen.add(folded)
            needles.append(text)

        add(language)
        for token, display in self._language_token_to_canonical.items():
            if display.casefold() == key:
                add(token)
        return needles

    def _extract_experience_requirement(self, text: str) -> dict[str, Any]:
        """Parse the experience requirement into min/max years plus the raw phrase."""
        normalized = self._clean_text(text)
        number = self._NUMBER_PATTERN
        units = r"(?:\u5e74|years?|yrs?)"

        range_match = re.search(rf"({number})\s*[-\u2013\u2014~\u81f3]\s*({number})\s*{units}", normalized)
        if range_match:
            low, high = self._to_int_or_none(range_match.group(1)), self._to_int_or_none(range_match.group(2))
            if low is not None and high is not None:
                return {"minimum_years": low, "maximum_years": high, "raw_text": range_match.group(0)}

        plus_match = re.search(rf"({number})\s*\+\s*{units}", normalized)
        if plus_match:
            count = self._to_int_or_none(plus_match.group(1))
            if count is not None:
                return {"minimum_years": count, "maximum_years": None, "raw_text": plus_match.group(0)}

        lower_prefix = re.search(
            rf"(?:不少於|不少于|至少|最少|不低於|不低于|超過|超过|at least)\s*({number})\s*{units}",
            normalized,
        )
        if lower_prefix:
            count = self._to_int_or_none(lower_prefix.group(1))
            if count is not None:
                return {"minimum_years": count, "maximum_years": None, "raw_text": lower_prefix.group(0)}

        lower_suffix = re.search(
            rf"({number})\s*(?:\u5e74\u4ee5\u4e0a|\u5e74\u6216\u4ee5\u4e0a|\u5e74\u6216\u66f4\u591a)",
            normalized,
        )
        if lower_suffix:
            count = self._to_int_or_none(lower_suffix.group(1))
            if count is not None:
                return {"minimum_years": count, "maximum_years": None, "raw_text": lower_suffix.group(0)}

        plain_match = re.search(rf"({number})\s*{units}", normalized)
        if plain_match:
            count = self._to_int_or_none(plain_match.group(1))
            if count is not None:
                return {"minimum_years": count, "maximum_years": count, "raw_text": plain_match.group(0)}

        return {"minimum_years": None, "maximum_years": None, "raw_text": None}

    @staticmethod
    def _to_int_or_none(value: str) -> int | None:
        """Convert an ASCII or Chinese numeral token to an int, or None."""
        if value.isdigit():
            return int(value)
        return _cn_numeral_to_int(value)

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
                    if self._is_language_value(skill):
                        continue
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

    def _needles_for_skill(self, item: dict[str, Any]) -> list[str]:
        """Collect canonical names, aliases, and the pre-map phrase used to locate a JD line."""
        needles: list[str] = []
        seen: set[str] = set()

        def add(value: str | None) -> None:
            text = (value or "").strip()
            if len(text) < 2:
                return
            key = text.casefold()
            if key in seen:
                return
            seen.add(key)
            needles.append(text)

        extracted = str(item.get("extracted_name") or "").strip()
        display = str(item.get("display_name") or "").strip()
        canonical = str(item.get("canonical_skill") or "").strip()
        add(extracted)
        add(display)
        add(canonical.replace("_", " "))
        add(canonical.replace("_", "-"))
        add(canonical)

        lookup_keys = {value.casefold() for value in (extracted, display, canonical, canonical.replace("_", " ")) if value}
        mapped: set[str] = set()
        for key in lookup_keys:
            mapped_name = self._token_to_canonical.get(key)
            if mapped_name:
                mapped.add(mapped_name)
                add(mapped_name)
        for token, canon in self._token_to_canonical.items():
            if canon in mapped or canon in lookup_keys:
                add(token)
        return needles

    def _apply_source_excerpts(self, structured_data: dict[str, Any], jd_text: str) -> None:
        """Attach original JD excerpts to skills and requirement fields."""
        for bucket in ("must_skills", "preferred_skills"):
            for item in structured_data.get(bucket, []) or []:
                if not isinstance(item, dict):
                    continue
                previous = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
                excerpt = find_source_excerpt(jd_text, self._needles_for_skill(item))
                excerpt["confidence"] = previous.get("confidence", 0.75)
                item["provenance"] = excerpt
                item.pop("extracted_name", None)

        language_items = structured_data.get("language_requirements") or []
        for item in language_items:
            if not isinstance(item, dict):
                continue
            language = str(item.get("language") or "").strip()
            item["provenance"] = find_cue_excerpt(jd_text, self._needles_for_language(language))

        education = structured_data.get("education_requirement")
        if isinstance(education, dict):
            degree = str(education.get("minimum_degree") or "")
            degree_cues = {
                "bachelor": ["bachelor", "学士"],
                "master": ["master", "硕士"],
                "phd": ["phd", "doctorate", "博士"],
            }
            education["provenance"] = find_cue_excerpt(jd_text, degree_cues.get(degree, []))

        visa = structured_data.get("visa_requirement")
        if isinstance(visa, dict):
            if visa.get("requirement_type") == "required":
                visa["provenance"] = find_cue_excerpt(jd_text, ["visa", "work permit", "sponsorship"])
            else:
                visa["provenance"] = ""

    async def parse_jd(
        self,
        jd_text: str,
        *,
        mode: str | None = None,
        enrichment_provider: JDEnrichmentProvider | None = None,
    ) -> dict[str, Any]:
        """Parse JD text into structured requirements and attach original source excerpts."""
        cleaned_input = (jd_text or "").strip()
        if not cleaned_input:
            return {
                "status": "invalid_input",
                "parse_path": "jd_placeholder",
                "error_message": "JD text is empty.",
                "structured_data": None,
            }

        mode = normalize_mode(mode)
        # Skill default is rule-only. REST injects an enrichment_provider for hybrid/qwen.
        provider = enrichment_provider
        if provider is None:
            mode = "rule"

        must_skills, preferred_skills = self._extract_skills(cleaned_input)
        language_requirements = self._extract_language_requirements(cleaned_input)
        experience_requirement = self._extract_experience_requirement(cleaned_input)
        normalized_cleaned = self._clean_text(cleaned_input)
        preprocessed_payload = self._build_preprocessed_payload(cleaned_input)
        llm_refine_request = self._build_llm_refine_request(preprocessed_payload)

        def build_skill_item(skill_name: str, order: int, weight: float) -> dict[str, Any]:
            """Build a skill item; source excerpt is attached after enrichment."""
            return {
                "skill_id": f"{skill_name.replace(' ', '_')}_{order}",
                "display_name": skill_name.title(),
                "canonical_skill": skill_name.lower().replace(" ", "_"),
                "priority_order": order,
                "weight": weight,
                "extracted_name": skill_name,
                "provenance": empty_skill_provenance(),
            }

        structured_data: dict[str, Any] = {
            "must_skills": [build_skill_item(skill, idx + 1, 1.0) for idx, skill in enumerate(must_skills)],
            "preferred_skills": [
                build_skill_item(skill, idx + 1, 0.6) for idx, skill in enumerate(preferred_skills)
            ],
            "language_requirements": language_requirements,
            "education_requirement": {
                "minimum_degree": "bachelor" if "bachelor" in normalized_cleaned else "none",
                "field_of_study": None,
                "is_mandatory": "bachelor" in normalized_cleaned,
                "provenance": "",
            },
            "visa_requirement": {
                "requirement_type": "required" if "visa" in normalized_cleaned else "unknown",
                "target_region": None,
                "provenance": "",
            },
            "experience_requirement": experience_requirement,
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
                    rule_must = structured_data["must_skills"]
                    rule_preferred = structured_data["preferred_skills"]
                    structured_data["must_skills"] = self._drop_language_skill_items(result.must_skills)
                    structured_data["preferred_skills"] = self._drop_language_skill_items(result.preferred_skills)
                    self._backfill_refined_skills(structured_data, rule_must, rule_preferred)
                if result.jd_overview:
                    structured_data["jd_overview"] = result.jd_overview
            else:
                parse_path = f"jd_{provider.name}_fallback_rule_parser"

        self._apply_source_excerpts(structured_data, cleaned_input)

        return {
            "status": "success",
            "parse_path": parse_path,
            "error_message": None,
            "structured_data": structured_data,
            "raw_llm_response": raw_llm_response,
        }


def build_jd_parser_service(taxonomy_loader: SkillTaxonomyLoader | None = None) -> JDParserService:
    """Build a JD parser service, optionally with an injected taxonomy loader."""
    return JDParserService(taxonomy_loader=taxonomy_loader)
