# Fingerprints HR reports so unchanged candidate PDFs and ranking HTML are skipped.
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# v3: board radar axes carry native-tooltip reasoning payload (Option A, PRD-REPORT-GEN-001).
# v4: radar axes print full dimension names plus on-chart scores, tooltip cards auto-size,
#     and the candidate match page shows an always-visible dimension breakdown (F1.3-F1.6).
# v5: ranking board carries a JD description + parsed-requirements panel keyed to a JD digest.
# v6: interview prompts carry template_id + allowlisted variables and highlight skill names.
# v7: the candidate page is keyed on the post applied for, so a multi-post advertisement
#     rebuilds an applicant's page when they move post (PRD-Multi_Post Section 6).
REPORT_FINGERPRINT_VERSION = "hr-report-v7"
INPUT_FINGERPRINT_VERSION = "hr-input-v1"
FINGERPRINTS_NAME = "report-fingerprints.json"


# Returns the SHA-256 hex digest of a file, or empty string if it is missing.
def sha256_file(path: Path | str | None) -> str:
    if not path:
        return ""
    target = Path(path)
    if not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Returns the SHA-256 hex digest of a UTF-8 string.
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Builds a stable fingerprint for one candidate HTML/PDF pair.
def candidate_report_fingerprint(
    *,
    engine: str | None,
    position: str | None,
    refno: str | None,
    appno: str | None,
    rank: object,
    total_score: object,
    tier: str | None,
    artifact_paths: list[Path | str | None],
    post: str | None = None,
) -> str:
    chunks = [
        REPORT_FINGERPRINT_VERSION,
        str(engine or ""),
        str(position or ""),
        str(refno or ""),
        str(appno or ""),
        str(rank or ""),
        str(total_score or ""),
        str(tier or ""),
        # An applicant moved to another post is scored against another JD, so their page is
        # stale even when the score is unchanged. Empty for a single-post job.
        str(post or ""),
    ]
    for path in artifact_paths:
        chunks.append(sha256_file(path))
    return sha256_text("|".join(chunks))


# Builds a comparable snapshot of JD + CV bytes so --resume can be invalidated.
def input_run_payload(
    *,
    engine: str | None,
    position: str | None,
    refno: str | None,
    jd_paths: list[Path | str | None],
    cv_hashes: dict[str, str],
    overrides_path: Path | str | None = None,
    apply_overrides: bool = False,
    posts: dict[str, str] | None = None,
) -> dict[str, Any]:
    jd_chunks = [sha256_file(path) for path in jd_paths if path]
    return {
        "version": INPUT_FINGERPRINT_VERSION,
        "engine": str(engine or ""),
        "position": str(position or ""),
        "refno": str(refno or ""),
        "jd": sha256_text("|".join(jd_chunks)),
        # HR-supplied conditions are tracked separately: they change scores, not the parse.
        "overrides": sha256_file(overrides_path),
        # Whether those conditions were actually merged: a "screen against the ad alone"
        # run must not reuse scores that were computed with conditions applied.
        "overrides_applied": bool(apply_overrides),
        "cvs": dict(sorted(cv_hashes.items())),
        # Which post each applicant was scored against, keyed by the same slug as "cvs". An
        # applicant re-assigned to another post is scored against a different JD even though the
        # advertisement and the CV are unchanged, so this has to take part in invalidation (PRD
        # Section 6) — per slug, through post_changed_slugs, so only that applicant is rebuilt
        # (FR-10). Absent for a single-post run, where both sides compare equal and nothing is
        # invalidated.
        "posts": dict(sorted((posts or {}).items())),
    }


# True when the advertisement text or the scoring engine changed and cached parse/score JSON must
# not be reused. A post re-assignment is deliberately NOT part of this: it invalidates the score of
# the applicant who moved, not the whole run, so it is reported separately (FR-10).
def jd_inputs_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    prior = previous or {}
    if not prior.get("jd"):
        return False
    return prior.get("jd") != current.get("jd") or prior.get("engine") != current.get("engine")


# Slugs whose post assignment differs between two runs, so their cached score was computed against
# a JD that no longer applies to them. Compared over the union of both maps: an applicant whose post
# became unreadable leaves the current map and must still be re-scored. A slug appearing for the
# first time is included too — it has no cached score, so clearing it is a no-op rather than a bug.
def post_changed_slugs(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    prior_posts = (previous or {}).get("posts")
    if not isinstance(prior_posts, dict):
        return []
    current_posts = current.get("posts") if isinstance(current.get("posts"), dict) else {}
    return sorted(
        str(slug)
        for slug in set(prior_posts) | set(current_posts)
        if prior_posts.get(slug) != current_posts.get(slug)
    )


# True when HR-supplied conditions changed and cached scores must be recomputed.
def overrides_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    prior = previous or {}
    # An absent key means the fingerprint predates conditions support: force one recompute.
    return prior.get("overrides", "") != current.get("overrides", "") or bool(
        prior.get("overrides_applied", False)
    ) != bool(current.get("overrides_applied", False))


# Slugs whose CV bytes changed (or are new) and must be re-parsed.
def stale_cv_slugs(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    prior_cvs = (previous or {}).get("cvs")
    if not isinstance(prior_cvs, dict):
        return []
    current_cvs = current.get("cvs") if isinstance(current.get("cvs"), dict) else {}
    stale: list[str] = []
    for slug, digest in current_cvs.items():
        if prior_cvs.get(slug) != digest:
            stale.append(str(slug))
    return stale


# Builds a fingerprint for ranking-overview.html from the current candidate set.
def board_report_fingerprint(
    *,
    position: str | None,
    refno: str | None,
    candidate_fingerprints: dict[str, str],
    resume_links_digest: str | None = None,
    jd_digest: str | None = None,
    post_order: list[str] | None = None,
) -> str:
    ordered = [candidate_fingerprints[key] for key in sorted(candidate_fingerprints)]
    return sha256_text(
        "|".join(
            [
                REPORT_FINGERPRINT_VERSION,
                str(position or ""),
                str(refno or ""),
                *ordered,
                f"links:{resume_links_digest or ''}",
                f"jd:{jd_digest or ''}",
                # The section order is part of the page, and the per-candidate fingerprints above
                # are compared key-sorted, so a reordered board would otherwise reuse a board
                # rendered in the old order (FR-6.3). Empty for a single-post job, which has no
                # sections.
                "posts:" + ",".join(post_order or []),
            ]
        )
    )


# Loads previously stored report fingerprints from the pipeline work directory.
def load_fingerprints(out_dir: Path) -> dict[str, Any]:
    path = out_dir / FINGERPRINTS_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


# Writes the current report fingerprints next to other pipeline JSON.
def save_fingerprints(out_dir: Path, payload: dict[str, Any]) -> None:
    path = out_dir / FINGERPRINTS_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "FINGERPRINTS_NAME",
    "INPUT_FINGERPRINT_VERSION",
    "REPORT_FINGERPRINT_VERSION",
    "board_report_fingerprint",
    "candidate_report_fingerprint",
    "input_run_payload",
    "jd_inputs_changed",
    "load_fingerprints",
    "overrides_changed",
    "post_changed_slugs",
    "save_fingerprints",
    "sha256_file",
    "sha256_text",
    "stale_cv_slugs",
]
