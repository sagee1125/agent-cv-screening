# Names and assembles the per-post effective JD artifacts of a multi-post run (FR-4, FR-5).
from __future__ import annotations

import re
from typing import Any, Iterable

from screening_core.hr_output import safe_pack_id
from screening_core.posts import base_name

# One effective JD per post, plus each delta's provenance (PRD Section 6).
POST_JDS_NAME = "post-jds.json"
# The shared base JD: the advertisement with every post-specific unit removed.
BASE_JD_TEXT_NAME = "jd-base.txt"
# Prefixes of the per-post artifacts: jd-post-<slug>.txt / jd-post-<slug>.json.
POST_JD_TEXT_PREFIX = "jd-post-"
POST_JD_JSON_SUFFIX = ".json"
# v1: base JD + one effective JD per post, each with its delta provenance.
POST_JD_VERSION = "post-jd-v1"

_RUN_OF_UNDERSCORES = re.compile(r"_{2,}")


# Turn a post's base name into a filename-safe slug ("Senior Project Fellow" -> "Senior_Project_Fellow").
# safe_pack_id alone can leave a run of underscores ("...Fellow__Full-time_"), so runs are collapsed
# before the slug is used to build a file name or an anchor.
def post_slug(name: str) -> str:
    """Return the stable artifact slug for one post base name."""
    slug = _RUN_OF_UNDERSCORES.sub("_", safe_pack_id(name, fallback="post")).strip("_")
    return slug or "post"


# The ordered base names behind a list of post labels, first appearance first.
# Full-time and part-time variants share one base name, so they share one effective JD (FR-4).
def base_names_of(labels: Iterable[str]) -> list[str]:
    """Return the distinct base names of the post universe, in first-appearance order."""
    names: list[str] = []
    for label in labels:
        name = base_name(label)
        if name and not any(name.casefold() == seen.casefold() for seen in names):
            names.append(name)
    return names


# The artifact paths of one post's effective JD.
def post_artifacts(out_dir: Any, name: str) -> tuple[Any, Any]:
    """Return (effective JD text path, effective JD JSON path) for one post base name."""
    slug = post_slug(name)
    return (
        out_dir / f"{POST_JD_TEXT_PREFIX}{slug}.txt",
        out_dir / f"{POST_JD_TEXT_PREFIX}{slug}{POST_JD_JSON_SUFFIX}",
    )


# Assemble _pipeline/post-jds.json: one entry per post, each carrying the JD it is scored
# against and the exact advertisement sentences that made it post-specific (FR-4 provenance).
def post_jd_payload(
    *,
    base_jd_json: str,
    base_text: str,
    posts: list[dict[str, Any]],
    mentioned: Iterable[str] = (),
    unclaimed: Iterable[str] = (),
) -> dict[str, Any]:
    """Return the post-jds.json payload for a multi-post run."""
    return {
        "version": POST_JD_VERSION,
        "base": {"jd_json": base_jd_json, "text": base_text},
        # Posts the advertisement describes but nobody applied for: recorded, never rendered.
        "unclaimed": list(unclaimed),
        "mentioned": list(mentioned),
        "posts": posts,
    }


__all__ = [
    "BASE_JD_TEXT_NAME",
    "POST_JD_JSON_SUFFIX",
    "POST_JD_TEXT_PREFIX",
    "POST_JD_VERSION",
    "POST_JDS_NAME",
    "base_names_of",
    "post_artifacts",
    "post_jd_payload",
    "post_slug",
]
