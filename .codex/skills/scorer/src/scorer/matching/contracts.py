# Defines stable contracts and constants for deterministic candidate matching.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


SCHEMA_VERSION = "2.2.0"
ALGORITHM_VERSION = "candidate-matching-v2"
DIMENSION_IDS = (
    "core_skill_match",
    "relevant_experience",
    "role_seniority_fit",
    "education_certification",
    "language_match",
)
DEFAULT_WEIGHTS = {
    "core_skill_match": 0.38,
    "relevant_experience": 0.32,
    "role_seniority_fit": 0.15,
    "education_certification": 0.05,
    "language_match": 0.10,
}
DIMENSION_LABELS = {
    "core_skill_match": "Core Skill Match",
    "relevant_experience": "Relevant Experience",
    "role_seniority_fit": "Role and Seniority Fit",
    "education_certification": "Education and Certification",
    "language_match": "Language Match",
}

# NOTE: the language constants below are imported BY THE JD PARSER
# (jd_parser/service.py), i.e. an upstream skill depends on this module. That inversion is
# deliberate: parser and scorer must agree on one proficiency ladder and one CJK alias table.
# Keep this block dependency-free (stdlib only) so the parser can import it cheaply.
# Canonical spoken-language proficiency ranking shared by parser and matching engine.
LANGUAGE_LEVEL_RANK = {"basic": 0, "business": 1, "fluent": 2, "native": 3}
# Demand multiplier per required proficiency level used to weight language requirements.
LANGUAGE_LEVEL_DEMAND = {"basic": 0.6, "business": 1.0, "fluent": 1.4, "native": 1.6}
# Multiplier applied when a language requirement is mandatory.
MANDATORY_LANGUAGE_FACTOR = 1.5
# Graded per-language score for each proficiency gap (d = required rank - candidate rank).
LANGUAGE_LEVEL_SCORE_STEPS = {0: 100.0, 1: 70.0, 2: 40.0, 3: 10.0}
# Score when the language is present but the candidate proficiency level is unstated.
LANGUAGE_UNSTATED_SCORE = 50.0
# Score when a Cantonese/Mandarin requirement is only backed by a broad Chinese entry.
LANGUAGE_CHINESE_ONLY_SCORE = 50.0
# Score when a Cantonese/Mandarin requirement is only backed by its sibling dialect.
LANGUAGE_DIALECT_PARTIAL_SCORE = 15.0
# Distinct gap reason codes emitted for partial language matching outcomes.
LANGUAGE_GAP_UNSTATED = "LANGUAGE_LEVEL_UNSTATED"
LANGUAGE_GAP_CHINESE_ONLY = "LANGUAGE_CHINESE_ONLY"
LANGUAGE_GAP_DIALECT = "LANGUAGE_DIALECT_PARTIAL"
LANGUAGE_GAP_LEVEL = "LANGUAGE_LEVEL_GAP"

# CJK and common aliases mapped to canonical display names (shared with the JD parser).
LANGUAGE_EXTRA_ALIASES: tuple[tuple[str, str], ...] = (
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

# Broad Chinese family satisfied by either Cantonese or Mandarin.
LANGUAGE_BROAD_CHINESE = "chinese"
# Dialect families that fully satisfy a broad Chinese requirement.
LANGUAGE_CHINESE_DIALECTS = frozenset({"cantonese", "mandarin"})

# Display-name groups that share one spoken-language family identity.
_LANGUAGE_FAMILY_NAMES = {
    "chinese": frozenset({"chinese", "chinese language"}),
    "mandarin": frozenset({"mandarin", "mandarin chinese", "putonghua"}),
    "cantonese": frozenset({"cantonese"}),
    "english": frozenset({"english", "english language", "business english"}),
}
# Reverse alias lookup so any CJK token collapses to its canonical display name.
_LANGUAGE_ALIAS_TO_DISPLAY = {
    token.casefold(): display for token, display in LANGUAGE_EXTRA_ALIASES
}


# Canonicalizes any JD or CV language token into one spoken-language family key.
def language_family(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    display = _LANGUAGE_ALIAS_TO_DISPLAY.get(text.casefold(), text)
    folded = display.casefold().replace("-", " ").replace("_", " ").strip()
    for family, names in _LANGUAGE_FAMILY_NAMES.items():
        if folded in names:
            return family
    return " ".join(folded.split())


SkillRelationResolver = Callable[[str, str], bool]


@dataclass(frozen=True)
class EffectiveConfig:
    """Carries an immutable canonical matching configuration and its identity."""

    config: dict[str, Any]
    canonical_json: str
    config_hash: str


class MatchingConfigError(ValueError):
    """Reports a stable validation failure for matching configuration."""

    # Initializes a validation error with its machine-readable code.
    def __init__(self, message: str, code: str = "MATCHING_CONFIG_INVALID") -> None:
        super().__init__(message)
        self.code = code
