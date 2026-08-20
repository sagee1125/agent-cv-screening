# Maps professional certification names to canonical skills for matching.
from __future__ import annotations

import re
from typing import Any

from app.core.taxonomy import SkillTaxonomyLoader
from app.services.cv_parser.helpers import _default_taxonomy, canonicalize_skill

# Curated regex patterns mapping certification name fragments to canonical skills.
# Patterns are intentionally specific to avoid false positives (e.g. "microsoft certified"
# alone is not enough — we require the cloud/tech keyword).
_CERT_SKILL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\baws\b|amazon web services", re.IGNORECASE), "aws"),
    (re.compile(r"\bazure\b", re.IGNORECASE), "azure"),
    (re.compile(r"\bgcp\b|google cloud", re.IGNORECASE), "gcp"),
    (re.compile(r"kubernetes", re.IGNORECASE), "kubernetes"),
    (re.compile(r"terraform", re.IGNORECASE), "terraform"),
    (re.compile(r"docker", re.IGNORECASE), "docker"),
    (re.compile(r"\bjava\b|spring professional", re.IGNORECASE), "java"),
    (re.compile(r"\bpython\b", re.IGNORECASE), "python"),
    (re.compile(r"\bsql\b|mysql|postgresql|oracle dba", re.IGNORECASE), "sql"),
    (re.compile(r"pmp\b|project management professional", re.IGNORECASE), "project_management"),
]


# Derive canonical skills from a list of certification objects.
def certifications_to_skills(
    certifications: list[dict[str, Any]] | None,
    taxonomy: SkillTaxonomyLoader | None = None,
) -> list[str]:
    loader = taxonomy or _default_taxonomy()
    canonicals: list[str] = []
    seen: set[str] = set()

    for cert in certifications or []:
        if not isinstance(cert, dict):
            continue
        name = cert.get("name")
        if not name:
            continue
        text = str(name)
        for pattern, canonical in _CERT_SKILL_PATTERNS:
            if pattern.search(text):
                resolved = canonicalize_skill(canonical, loader) or canonical
                if resolved not in seen:
                    seen.add(resolved)
                    canonicals.append(resolved)
                break

    return canonicals
