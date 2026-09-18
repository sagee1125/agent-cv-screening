# Split a multi-post advertisement into a shared base plus one delta per post (FR-4).
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import re
from typing import Iterable

from screening_core.posts import base_name

# A requirement unit is one bullet, and on the live pages one bullet is one line.
#
# Deliberately NOT split further at sentence boundaries. A single bullet can run to several
# sentences with its attribution marker only in the last one, e.g. the Senior Project Fellow
# duty "... with stakeholders in Hong Kong. This includes overseeing the entire design process
# ... (applicable to Senior Project Fellow only);". Splitting that bullet at the full stop would
# leave its first sentence in the shared base, so every other post would inherit a duty the
# advertisement reserves for one post. Attribution is therefore bullet-level.
_BULLET_PREFIX_RE = re.compile(r"^[\s\-*•·]+")

# The two attribution forms measured on the live multi-post advertisements (2026-09-17):
#   prefix       "Applicants for the Senior Project Fellow post should have ..."
#   parenthetical "act as a project manager ... (applicable to Senior Project Fellow only);"
#                 "have strong expertise in ... (for Senior Project Fellow post);"
# Both are matched against a known base name, so a parenthetical that merely starts with "for"
# (e.g. "(for example, ...)") cannot attribute anything on its own.
_ATTRIBUTION_TEMPLATE = (
    r"applicants?\s+for\s+(?:the\s+)?{name}\b"
    r"|\(\s*(?:applicable\s+to|for)\s+(?:the\s+)?{name}\b"
)
# Same two forms, but capturing the name so the advertisement can be cross-checked against the
# post universe the records page actually produced (FR-3).
_NAME_CAPTURE_RE = re.compile(
    r"applicants?\s+for\s+(?:the\s+)?(?P<prefix>[^,;.()]{2,80}?)\s+posts?\b"
    r"|\(\s*(?:applicable\s+to|for)\s+(?:the\s+)?(?P<suffix>[^,;.()]{2,80}?)\s*(?:\s+posts?)?\s*(?:only)?\s*\)",
    re.IGNORECASE,
)
# Trailing "only" / "post" left inside a captured suffix name.
_NAME_TAIL_RE = re.compile(r"\s+(?:posts?|only|applicants?)$", re.IGNORECASE)


@dataclass
class PostDelta:
    """One post's post-specific requirement sentences.

    The sentences are the delta's provenance: each one is the exact source sentence the
    requirement came from, so HR can be shown what the split decided (FR-4, §10).
    """

    label: str
    sentences: list[str] = field(default_factory=list)


@dataclass
class PostSplit:
    """One advertisement split into a shared base plus one delta per post."""

    base_sentences: list[str] = field(default_factory=list)
    # Keyed by base name, because attribution matches base names: the full-time and part-time
    # variants of one post inherit the same bullets (FR-4).
    delta_sentences: dict[str, list[str]] = field(default_factory=dict)
    # Base names the advertisement attributes requirements to, in first-appearance order.
    mentioned: list[str] = field(default_factory=list)
    # Mentioned by the advertisement but absent from the post universe: no applicant applied
    # for them, so no section is rendered. Recorded as the FR-3 cross-check disagreement.
    unclaimed: list[str] = field(default_factory=list)
    # The requirement sentences those posts were attributed, keyed by base name. Recorded because
    # the sentences are excluded from every artifact: without this, a run would silently drop a
    # requirement and nothing HR can read would say which one.
    unclaimed_sentences: dict[str, list[str]] = field(default_factory=dict)

    @property
    def base_text(self) -> str:
        """The shared requirements, with every post-specific unit removed."""
        return "\n".join(self.base_sentences)

    @property
    def deltas(self) -> list[PostDelta]:
        """One delta per mentioned base name, in first-appearance order."""
        return [PostDelta(label=name, sentences=self.delta_sentences.get(name, [])) for name in self.mentioned]

    def delta_for(self, label: str) -> list[str]:
        """The post-specific sentences a post label inherits, via its base name."""
        return self.delta_sentences.get(base_name(label), [])

    def effective_text(self, label: str) -> str:
        """The text one post is scored against: the shared base plus that post's delta."""
        return "\n".join([*self.base_sentences, *self.delta_for(label)])


# Split JD text into requirement units, one bullet per line, with bullet decoration stripped so
# a stored unit is the sentence itself.
def split_units(text: str) -> list[str]:
    units: list[str] = []
    for raw_line in (text or "").split("\n"):
        line = _BULLET_PREFIX_RE.sub("", raw_line).strip()
        if line:
            units.append(line)
    return units


# Build the case-insensitive attribution matcher for one base name.
@lru_cache(maxsize=256)
def _attribution_pattern(base: str) -> re.Pattern[str]:
    return re.compile(_ATTRIBUTION_TEMPLATE.format(name=re.escape(base)), re.IGNORECASE)


# Return the base names this requirement unit attributes itself to.
# A shorter name contained in a longer match is dropped, so a post called "Research Fellow"
# cannot fire inside a mention of "Senior Research Fellow".
def attributed_bases(unit: str, bases: list[str]) -> list[str]:
    hits = [name for name in bases if _attribution_pattern(name).search(unit)]
    kept: list[str] = []
    for name in sorted(hits, key=len, reverse=True):
        if any(name.casefold() in other.casefold() for other in kept):
            continue
        kept.append(name)
    return [name for name in bases if name in kept]


# List the post names the advertisement attributes requirements to, whether or not anybody
# applied for them. Used to cross-check the post universe (FR-3).
def post_names_in(text: str) -> list[str]:
    names: list[str] = []
    for match in _NAME_CAPTURE_RE.finditer(text or ""):
        raw = match.group("prefix") or match.group("suffix") or ""
        name = _NAME_TAIL_RE.sub("", " ".join(raw.split())).strip()
        if name and not any(name.casefold() == seen.casefold() for seen in names):
            names.append(name)
    return names


# Attribute every requirement unit to a post; a unit naming no post stays shared in the base.
def split_advertisement(text: str, labels: Iterable[str]) -> PostSplit:
    # Materialised because the labels are walked more than once, and a generator would be spent.
    labels = list(labels)
    # No labels is the single-post shape (the pipeline returns before splitting in that case): there
    # is no post to attribute anything to, so a bullet naming the post is ordinary prose and stays
    # shared — and nothing can be missing from a universe that does not exist, so nothing is recorded
    # as unclaimed either. Recording a name while leaving its bullet shared would make the trace lie.
    if not labels:
        return PostSplit(base_sentences=split_units(text))

    claimed: list[str] = []
    for label in labels:
        name = base_name(label)
        if name and not any(name.casefold() == seen.casefold() for seen in claimed):
            claimed.append(name)

    # A post the advertisement describes but nobody applied for has no group to render; it is
    # recorded rather than guessed at, because the records page cannot confirm it was an option.
    unclaimed = [
        name
        for name in post_names_in(text)
        if not any(base_name(label).casefold() == name.casefold() for label in labels)
    ]

    # Attribution runs over the claimed posts AND the unclaimed ones. Leaving the unclaimed names
    # out is not a harmless omission: a unit the advertisement reserves for such a post then matches
    # no base, falls through to the shared base, and every post that DID receive applications is
    # scored against a requirement that was never theirs (measured 2026-09-18).
    bases = list(claimed)
    for name in unclaimed:
        if not any(name.casefold() == seen.casefold() for seen in bases):
            bases.append(name)

    split = PostSplit()
    for unit in split_units(text):
        hits = attributed_bases(unit, bases)
        if not hits:
            split.base_sentences.append(unit)
            continue
        for name in hits:
            split.delta_sentences.setdefault(name, []).append(unit)
            # `mentioned` stays scoped to the post universe: it is what HR's per-post derivation is
            # built from, and an unclaimed post has no group for that answer to apply to.
            if name in claimed and name not in split.mentioned:
                split.mentioned.append(name)

    split.unclaimed = unclaimed
    # What was set aside, so the exclusion can be audited rather than only inferred from a name.
    split.unclaimed_sentences = {
        name: list(split.delta_sentences.get(name, [])) for name in unclaimed
    }
    return split


__all__ = [
    "PostDelta",
    "PostSplit",
    "attributed_bases",
    "post_names_in",
    "split_advertisement",
    "split_units",
]
