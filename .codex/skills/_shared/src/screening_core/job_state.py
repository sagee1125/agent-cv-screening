# Persists per-refno job state: last update snapshot + run history (audit).
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from screening_core.report_fingerprint import sha256_file, sha256_text

JOB_STATE_VERSION = "job-state-v1"
HISTORY_LIMIT = 100


# Returns the on-disk path for one refno's job state file.
def job_state_path(state_dir: str | Path, refno: str) -> Path:
    root = Path(state_dir)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(refno)) or "job"
    return root / f"{safe}.json"


# Loads the job state dict for a refno (fresh default when missing/corrupt).
def load_job_state(state_dir: str | Path, refno: str) -> dict[str, Any]:
    default = {"schema_version": JOB_STATE_VERSION, "refno": str(refno), "history": []}
    path = job_state_path(state_dir, refno)
    if not path.is_file():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(payload, dict):
        return default
    payload.setdefault("history", [])
    return payload


# Writes the job state dict for a refno (creating parent dirs).
def save_job_state(state_dir: str | Path, refno: str, state: dict[str, Any]) -> None:
    path = job_state_path(state_dir, refno)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# Builds a comparable snapshot (JD hash + candidate status map + per-candidate post) from a job payload.
def current_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    candidates = {
        str(c.get("appno")): c.get("status")
        for c in job.get("candidates", [])
        if c.get("appno")
    }
    snapshot: dict[str, Any] = {"jd": sha256_text(str(job.get("jd_text") or "")), "candidates": candidates}
    # The post dimension is recorded only when the page states one, so a single-post snapshot keeps
    # exactly its previous shape and no stored state has to be migrated (FR-12).
    posts = {
        str(c.get("appno")): str(c.get("post"))
        for c in job.get("candidates", [])
        if c.get("appno") and c.get("post")
    }
    if posts:
        snapshot["posts"] = posts
    return snapshot


# Diffs the post dimension: a new applicant in post X, an applicant whose post changed, and a post
# that appeared or disappeared (FR-12).
#
# A re-assignment leaves the applicant count and every status untouched, so without these keys it
# would be reported as no change at all - which is exactly the change HR most needs to see. A post
# is visible here exactly when it has an applicant on the page, because the records page is all this
# check reads; a post listed in the advertisement with no applicant is not something it can see.
def _diff_posts(
    previous: Any,
    current: Any,
    added: list[str],
    removed: list[str],
    *,
    has_baseline: bool,
) -> dict[str, Any]:
    prev_posts = previous if isinstance(previous, dict) else {}
    curr_posts = current if isinstance(current, dict) else {}
    post_changed = {
        appno: {"from": prev_posts.get(appno), "to": curr_posts[appno]}
        for appno in curr_posts
        if appno in prev_posts and prev_posts.get(appno) != curr_posts[appno]
    }
    prev_labels = {str(value) for value in prev_posts.values() if value}
    curr_labels = {str(value) for value in curr_posts.values() if value}
    return {
        # Which post each new / withdrawn applicant is in, so "3 new applicants" becomes
        # "2 new in Research Assistant, 1 new in Research Associate".
        "added_posts": {appno: str(curr_posts[appno]) for appno in added if curr_posts.get(appno)},
        "removed_posts": {appno: str(prev_posts[appno]) for appno in removed if prev_posts.get(appno)},
        "post_changed": post_changed,
        "posts_appeared": sorted(curr_labels - prev_labels) if has_baseline else [],
        "posts_disappeared": sorted(prev_labels - curr_labels) if has_baseline else [],
    }


# Diffs two snapshots into a compact change summary, including the post dimension (FR-12).
def diff_snapshots(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    prev = previous or {}
    prev_cands = prev.get("candidates") or {}
    curr_cands = current.get("candidates") or {}
    added = sorted(set(curr_cands) - set(prev_cands))
    removed = sorted(set(prev_cands) - set(curr_cands))
    status_changed = {
        appno: {"from": prev_cands.get(appno), "to": curr_cands.get(appno)}
        for appno in curr_cands
        if appno in prev_cands and prev_cands.get(appno) != curr_cands.get(appno)
    }
    jd_changed = bool(prev.get("jd") and prev.get("jd") != current.get("jd"))
    return {
        "jd_changed": jd_changed,
        "added": added,
        "removed": removed,
        "status_changed": status_changed,
        # has_baseline is read from the snapshot, not from the posts map: an absent key is what
        # tells us the baseline predates the post dimension.
        **_diff_posts(
            prev.get("posts"),
            current.get("posts"),
            added,
            removed,
            has_baseline="posts" in prev,
        ),
    }


# True when a change summary contains any difference.
def has_changes(changes: dict[str, Any]) -> bool:
    return bool(
        changes.get("jd_changed")
        or changes.get("added")
        or changes.get("removed")
        or changes.get("status_changed")
        # A re-assignment changes nothing else, so the post dimension has to count as a change.
        # added_posts / removed_posts are not listed: they are non-empty only when added /
        # removed already are, and those are checked above (FR-12).
        or changes.get("post_changed")
        or changes.get("posts_appeared")
        or changes.get("posts_disappeared")
    )


# Returns a local ISO-8601 timestamp for history entries.
def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# Builds a PII-free per-candidate score snapshot (appno only) for backtesting.
def score_snapshot(pipeline_manifest: dict[str, Any] | None, job: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = pipeline_manifest if isinstance(pipeline_manifest, dict) else {}
    statuses = {
        str(c.get("appno")): c.get("status")
        for c in job.get("candidates", [])
        if isinstance(c, dict) and c.get("appno")
    }
    rows: list[dict[str, Any]] = []
    for item in manifest.get("candidates") or []:
        if not isinstance(item, dict) or not item.get("appno"):
            continue
        appno = str(item.get("appno"))
        rows.append(
            {
                "appno": appno,
                "rank": item.get("rank"),
                "match_score": item.get("total_score"),
                "fit_band": item.get("tier"),
                "hr_status": statuses.get(appno),
            }
        )
    return rows


# Appends one history entry and caps the stored history length.
def append_history(state_dir: str | Path, refno: str, entry: dict[str, Any]) -> None:
    state = load_job_state(state_dir, refno)
    history = state.setdefault("history", [])
    history.append(entry)
    state["history"] = history[-HISTORY_LIMIT:]
    save_job_state(state_dir, refno, state)


# Records a screening run: snapshot + CV hashes + history entry (+ optional scores).
def record_screen_run(
    state_dir: str | Path,
    refno: str,
    *,
    job: dict[str, Any],
    cv_paths: dict[str, Path],
    result: str,
    output: str,
    at: str | None = None,
    scores: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timestamp = at or now_iso()
    state = load_job_state(state_dir, refno)
    state["last_screen"] = {"at": timestamp, **current_snapshot(job)}
    state["cv_hashes"] = {appno: sha256_file(path) for appno, path in cv_paths.items()}
    history = state.setdefault("history", [])
    entry = {
        "at": timestamp,
        "kind": "screen",
        "result": result,
        "refno": str(refno),
        "candidate_count": len(cv_paths),
        "output": output,
    }
    if scores:
        entry["scores"] = scores
    history.append(entry)
    state["history"] = history[-HISTORY_LIMIT:]
    save_job_state(state_dir, refno, state)
    return state


# Records an update check: snapshot + history entry.
def record_check(
    state_dir: str | Path,
    refno: str,
    *,
    job: dict[str, Any],
    result: str,
    changes: dict[str, Any],
    at: str | None = None,
) -> dict[str, Any]:
    timestamp = at or now_iso()
    state = load_job_state(state_dir, refno)
    state["last_check"] = {"at": timestamp, **current_snapshot(job)}
    history = state.setdefault("history", [])
    history.append(
        {
            "at": timestamp,
            "kind": "check",
            "result": result,
            "refno": str(refno),
            "has_changes": has_changes(changes),
            "changes": changes,
        }
    )
    state["history"] = state["history"][-HISTORY_LIMIT:]
    save_job_state(state_dir, refno, state)
    return state


__all__ = [
    "HISTORY_LIMIT",
    "JOB_STATE_VERSION",
    "append_history",
    "current_snapshot",
    "diff_snapshots",
    "has_changes",
    "job_state_path",
    "load_job_state",
    "now_iso",
    "record_check",
    "record_screen_run",
    "save_job_state",
    "score_snapshot",
]
