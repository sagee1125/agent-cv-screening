# Unit tests for per-refno job state (snapshots, diffs, history).
from __future__ import annotations

import sys
from pathlib import Path

# backend/tests/unit/test_job_state.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_SRC = REPO_ROOT / ".codex" / "skills" / "_shared" / "src"
sys.path.insert(0, str(SHARED_SRC))

from screening_core.job_state import (  # noqa: E402
    current_snapshot,
    diff_snapshots,
    has_changes,
    job_state_path,
    load_job_state,
    now_iso,
    record_check,
    record_screen_run,
    save_job_state,
)

JOB = {
    "refno": "2600827001",
    "post_title": "Senior Software Engineer",
    "jd_text": "Post title: Senior Software Engineer\nDescription: Python FastAPI",
    "candidates": [
        {"appno": "2600827001", "status": "S"},
        {"appno": "2600827002", "status": "P"},
    ],
}


# The state file path sanitizes the refno.
def test_job_state_path_sanitizes_refno() -> None:
    assert job_state_path("state", "2600827001").name == "2600827001.json"
    assert job_state_path("state", "a/b:1").name == "a_b_1.json"


# save/load round-trips a state dict.
def test_save_and_load_roundtrip(tmp_path) -> None:
    save_job_state(tmp_path, "2600827001", {"refno": "2600827001", "history": [{"at": "x"}]})
    state = load_job_state(tmp_path, "2600827001")
    assert state["refno"] == "2600827001"
    assert state["history"] == [{"at": "x"}]


# Missing or corrupt state returns a fresh default.
def test_load_missing_state_returns_default(tmp_path) -> None:
    state = load_job_state(tmp_path, "nope")
    assert state["schema_version"]
    assert state["history"] == []
    (tmp_path / "nope.json").write_text("{bad json", encoding="utf-8")
    state = load_job_state(tmp_path, "nope")
    assert state["history"] == []


# current_snapshot builds a JD hash and candidate status map.
def test_current_snapshot() -> None:
    snap = current_snapshot(JOB)
    assert snap["jd"]
    assert snap["candidates"] == {"2600827001": "S", "2600827002": "P"}


# diff_snapshots reports added / removed / status / JD changes.
def test_diff_snapshots() -> None:
    prev = {"jd": "abc", "candidates": {"2600827001": "S", "2600827002": "P"}}
    curr = {"jd": "def", "candidates": {"2600827001": "S", "2600827003": "N"}}
    diff = diff_snapshots(prev, curr)
    assert diff["jd_changed"] is True
    assert diff["added"] == ["2600827003"]
    assert diff["removed"] == ["2600827002"]
    assert diff["status_changed"] == {}


# has_changes is false only when nothing changed.
def test_has_changes() -> None:
    empty = {"jd_changed": False, "added": [], "removed": [], "status_changed": {}}
    assert has_changes(empty) is False
    assert has_changes({**empty, "jd_changed": True}) is True
    assert has_changes({**empty, "added": ["1"]}) is True
    assert has_changes({**empty, "removed": ["2"]}) is True
    assert has_changes({**empty, "status_changed": {"3": {"from": "P", "to": "S"}}}) is True


# now_iso returns a local ISO-8601 timestamp.
def test_now_iso() -> None:
    assert now_iso()[-6:] in ("+08:00", "+00:00") or now_iso().endswith("Z")


# record_screen_run stores the snapshot, CV hashes, and a history entry.
def test_record_screen_run(tmp_path) -> None:
    cv = tmp_path / "cvs" / "2600827001.pdf"
    cv.parent.mkdir(parents=True, exist_ok=True)
    cv.write_bytes(b"%PDF")
    state = record_screen_run(
        tmp_path / "state",
        "2600827001",
        job=JOB,
        cv_paths={"2600827001": cv},
        result="success",
        output="Desktop/workbuddy-cv-screen/2600827001",
        at="2026-08-31T10:00:00+08:00",
    )
    assert state["last_screen"]["at"] == "2026-08-31T10:00:00+08:00"
    assert state["cv_hashes"]["2600827001"]
    assert state["history"][-1]["kind"] == "screen"
    assert state["history"][-1]["result"] == "success"
    assert state["history"][-1]["candidate_count"] == 1
    assert state["history"][-1]["output"] == "Desktop/workbuddy-cv-screen/2600827001"


# record_check stores a snapshot and a check history entry.
def test_record_check(tmp_path) -> None:
    state = record_check(
        tmp_path / "state",
        "2600827001",
        job=JOB,
        result="no_change",
        changes={"jd_changed": False, "added": [], "removed": [], "status_changed": {}},
        at="2026-08-31T10:00:00+08:00",
    )
    assert state["last_check"]["candidates"]["2600827001"] == "S"
    assert state["history"][-1]["kind"] == "check"
    assert state["history"][-1]["has_changes"] is False
