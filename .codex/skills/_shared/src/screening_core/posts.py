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
    "post_key",
    "post_of",
]
