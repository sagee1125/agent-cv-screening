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


# Builds a comparable snapshot (JD hash + candidate status map) from a job payload.
def current_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    candidates = {
        str(c.get("appno")): c.get("status")
        for c in job.get("candidates", [])
        if c.get("appno")
    }
    return {"jd": sha256_text(str(job.get("jd_text") or "")), "candidates": candidates}


# Diffs two snapshots into a compact change summary.
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
    return {"jd_changed": jd_changed, "added": added, "removed": removed, "status_changed": status_changed}


# True when a change summary contains any difference.
def has_changes(changes: dict[str, Any]) -> bool:
    return bool(
        changes.get("jd_changed")
        or changes.get("added")
        or changes.get("removed")
        or changes.get("status_changed")
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
