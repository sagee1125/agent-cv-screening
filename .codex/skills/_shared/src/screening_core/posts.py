# Groups JAS applicants by the post they applied for (multi-post advertisements).
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# A post label is compared case-insensitively and with whitespace collapsed, but HR always sees
# the first spelling that appeared on the records page (FR-3).
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass
class PostGroup:
    """One post and the applicants who applied for it, in records-page order."""

    label: str
    rows: list[Any] = field(default_factory=list)


@dataclass
class PostGrouping:
    """The post dimension of one run: ordered groups plus the rows that could not be placed."""

    multi_post: bool
    groups: list[PostGroup] = field(default_factory=list)
    unassigned: list[Any] = field(default_factory=list)

    @property
    def labels(self) -> list[str]:
        """Post labels in first-appearance order."""
        return [group.label for group in self.groups]


# Read the post value from a candidate dict or dataclass, tolerating both shapes.
def post_of(row: Any) -> str:
    value = row.get("post") if isinstance(row, dict) else getattr(row, "post", None)
    return (value or "").strip()


# Build the case-insensitive grouping key for a post label.
def post_key(label: str) -> str:
    return " ".join(label.split()).casefold()


# Drop a trailing parenthetical so full-time and part-time variants share one base name.
# "Senior Project Fellow (Full-time)" -> "Senior Project Fellow".
def base_name(label: str) -> str:
    stripped = _TRAILING_PARENTHETICAL.sub("", (label or "").strip()).strip()
    return stripped or (label or "").strip()


# True when the advertisement's Post title mentions this post's base name (FR-3 cross-check).
def mentioned_in_post_title(post_title: str, label: str) -> bool:
    base = base_name(label).casefold()
    return bool(base) and base in (post_title or "").casefold()


# One entry per post with its applicant count, in first-appearance order of the sequence given.
# This is the post list the manifests and the update check report (PRD Section 6, FR-11). The two
# sides count different things on purpose: the JAS side counts everyone on the records page, the
# pipeline side counts the rows it actually scored, and the order follows whichever sequence the
# caller passes. Posts are keyed the way group_by_post keys them, so the counts agree with the
# board's sections, and the label is the first spelling the page used (FR-3).
def post_counts(candidates: Iterable[Any]) -> list[dict[str, Any]]:
    """Return [{'post': label, 'applicants': n}] per post, in first-appearance order."""
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for candidate in candidates or []:
        label = post_of(candidate)
        if not label:
            continue
        key = post_key(label)
        labels.setdefault(key, label)
        counts[key] = counts.get(key, 0) + 1
    return [{"post": labels[key], "applicants": count} for key, count in counts.items()]


# Reorder (appno, value) pairs into the order the records page lists the applicants (FR-6.3).
#
# The records page is the only artefact HR can check a report against, so every HR-facing list
# follows the page's own order and they agree by construction: the board's post sections, both
# manifests' post lists and the update check. The page lists the newest application first, so the
# post at the top of the board is the one the most recent applicant applied for — and it changes
# when a newer application arrives for a different post, which is the point: it can always be
# checked against the page.
#
# An appno the page does not list keeps its relative place, after the ones it does: CVs HR passed
# by hand with --cv are not on the page and must not displace what is. A page with no candidates
# leaves the sequence exactly as it came in.
def order_by_records_page(
    items: Iterable[tuple[str, Any]], page_candidates: Iterable[Any]
) -> list[tuple[str, Any]]:
    """Return `items` sorted into the records page's candidate order."""
    rank: dict[str, int] = {}
    for candidate in page_candidates or []:
        appno = str(candidate.get("appno") or "").strip() if isinstance(candidate, dict) else ""
        if appno and appno not in rank:
            rank[appno] = len(rank)
    beyond = len(rank)
    return sorted(items or [], key=lambda item: rank.get(str(item[0]).strip(), beyond))


# Group rows by post, keeping first-appearance order. Rows whose post value is blank cannot be
# placed in any group and are returned separately so the caller can ask HR (FR-7).
#
# Only a multi-post advertisement has a post dimension. Pass multi_post=False for a single-post
# page: the result then carries no groups and no unassigned rows, and the caller must keep using
# its flat candidate list unchanged. The post universe is exactly the posts that received at
# least one application; a post nobody applied for is invisible on the records page (see FR-6).
def group_by_post(rows: Iterable[Any], *, multi_post: bool) -> PostGrouping:
    if not multi_post:
        return PostGrouping(multi_post=False)
    groups: list[PostGroup] = []
    index: dict[str, PostGroup] = {}
    unassigned: list[Any] = []
    for row in rows:
        label = post_of(row)
        if not label:
            unassigned.append(row)
            continue
        key = post_key(label)
        group = index.get(key)
        if group is None:
            group = PostGroup(label=label)
            index[key] = group
            groups.append(group)
        group.rows.append(row)
    return PostGrouping(multi_post=True, groups=groups, unassigned=unassigned)


__all__ = [
    "PostGroup",
    "PostGrouping",
    "base_name",
    "group_by_post",
    "mentioned_in_post_title",
    "order_by_records_page",
    "post_counts",
    "post_key",
    "post_of",
]
