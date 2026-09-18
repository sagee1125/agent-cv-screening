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
    score_snapshot,
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


# score_snapshot merges pipeline manifest scores with JAS hr statuses (appno only).
def test_score_snapshot_merges_manifest_and_status() -> None:
    manifest = {
        "status": "success",
        "candidates": [
            {"rank": 1, "appno": "2600827001", "total_score": 57.4, "tier": "low"},
            {"rank": 2, "appno": "2600827002", "total_score": 51.7, "tier": "low"},
        ],
    }
    rows = score_snapshot(manifest, JOB)
    assert rows == [
        {"appno": "2600827001", "rank": 1, "match_score": 57.4, "fit_band": "low", "hr_status": "S"},
        {"appno": "2600827002", "rank": 2, "match_score": 51.7, "fit_band": "low", "hr_status": "P"},
    ]


# score_snapshot tolerates missing/failed manifests and skips rows without appno.
def test_score_snapshot_tolerates_bad_manifests() -> None:
    assert score_snapshot(None, JOB) == []
    assert score_snapshot({}, JOB) == []
    assert score_snapshot({"status": "error", "error_message": "boom"}, JOB) == []
    rows = score_snapshot({"candidates": [{"rank": 1}, {"rank": 2, "appno": "2600827001"}]}, JOB)
    assert rows == [{"appno": "2600827001", "rank": 2, "match_score": None, "fit_band": None, "hr_status": "S"}]


# record_screen_run stores the per-candidate scores in the history entry when given.
def test_record_screen_run_stores_scores(tmp_path) -> None:
    cv = tmp_path / "cvs" / "2600827001.pdf"
    cv.parent.mkdir(parents=True, exist_ok=True)
    cv.write_bytes(b"%PDF")
    scores = [{"appno": "2600827001", "rank": 1, "match_score": 57.4, "fit_band": "low", "hr_status": "S"}]
    state = record_screen_run(
        tmp_path / "state",
        "2600827001",
        job=JOB,
        cv_paths={"2600827001": cv},
        result="success",
        output="Desktop/workbuddy-cv-screen/2600827001",
        at="2026-08-31T10:00:00+08:00",
        scores=scores,
    )
    assert state["history"][-1]["scores"] == scores


# record_screen_run omits the scores key when no snapshot is provided (legacy shape).
def test_record_screen_run_without_scores_keeps_entry_shape(tmp_path) -> None:
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
    assert "scores" not in state["history"][-1]


# A multi-post page records each applicant's post; a single-post page records none (FR-12).
def test_current_snapshot_records_post_only_when_the_page_has_one() -> None:
    assert "posts" not in current_snapshot(JOB)
    multi_post = {
        **JOB,
        "candidates": [
            {"appno": "2600827001", "status": "S", "post": "Research Assistant (Full-time)"},
            {"appno": "2600827002", "status": "P", "post": None},
        ],
    }
    assert current_snapshot(multi_post)["posts"] == {
        "2600827001": "Research Assistant (Full-time)"
    }


# A re-assignment changes no count and no status, so only the post dimension can report it (FR-12).
def test_diff_snapshots_reports_a_re_assignment() -> None:
    prev = {"jd": "abc", "candidates": {"1": "S"}, "posts": {"1": "Research Assistant"}}
    curr = {"jd": "abc", "candidates": {"1": "S"}, "posts": {"1": "Research Associate"}}
    diff = diff_snapshots(prev, curr)
    assert diff["jd_changed"] is False
    assert diff["added"] == [] and diff["removed"] == [] and diff["status_changed"] == {}
    assert diff["post_changed"] == {
        "1": {"from": "Research Assistant", "to": "Research Associate"}
    }
    assert has_changes(diff) is True


# A new applicant is reported with the post they applied for, and a withdrawn one with theirs.
def test_diff_snapshots_reports_which_post_each_mover_is_in() -> None:
    prev = {"jd": "abc", "candidates": {"1": "S"}, "posts": {"1": "Research Assistant"}}
    curr = {
        "jd": "abc",
        "candidates": {"1": "S", "2": "TBC"},
        "posts": {"1": "Research Assistant", "2": "Research Associate"},
    }
    diff = diff_snapshots(prev, curr)
    assert diff["added"] == ["2"]
    assert diff["added_posts"] == {"2": "Research Associate"}
    assert diff["removed"] == [] and diff["removed_posts"] == {}


# A post that appeared or disappeared is reported on its own (FR-12).
def test_diff_snapshots_reports_posts_appearing_and_disappearing() -> None:
    prev = {"jd": "abc", "candidates": {"1": "S"}, "posts": {"1": "Research Assistant"}}
    curr = {"jd": "abc", "candidates": {"1": "S"}, "posts": {"1": "Research Associate"}}
    diff = diff_snapshots(prev, curr)
    assert diff["posts_appeared"] == ["Research Associate"]
    assert diff["posts_disappeared"] == ["Research Assistant"]


# A single-post job reports an empty post dimension and is not a change.
def test_diff_snapshots_post_dimension_is_empty_without_posts() -> None:
    diff = diff_snapshots(
        {"jd": "abc", "candidates": {"1": "S"}}, {"jd": "abc", "candidates": {"1": "S"}}
    )
    assert diff["post_changed"] == {}
    assert diff["added_posts"] == {} and diff["removed_posts"] == {}
    assert diff["posts_appeared"] == [] and diff["posts_disappeared"] == []
    assert has_changes(diff) is False


# has_changes treats a post-only difference as a change (FR-12).
def test_has_changes_covers_the_post_dimension() -> None:
    empty = {"jd_changed": False, "added": [], "removed": [], "status_changed": {}}
    assert has_changes(empty) is False
    assert has_changes({**empty, "post_changed": {"1": {"from": "A", "to": "B"}}}) is True
    assert has_changes({**empty, "posts_appeared": ["A"]}) is True
    assert has_changes({**empty, "posts_disappeared": ["A"]}) is True


# A baseline written before the post dimension existed is not a change: there is nothing to
# compare, so no post is reported as having appeared.
def test_diff_snapshots_without_a_post_baseline_reports_no_appearance() -> None:
    prev = {"jd": "abc", "candidates": {"1": "S"}}
    curr = {"jd": "abc", "candidates": {"1": "S"}, "posts": {"1": "Research Assistant"}}
    diff = diff_snapshots(prev, curr)
    assert diff["posts_appeared"] == [] and diff["posts_disappeared"] == []
    assert diff["post_changed"] == {}
    assert has_changes(diff) is False


# A recorded check keeps the post dimension, so a later check can still see a re-assignment.
def test_record_check_stores_the_post_dimension(tmp_path) -> None:
    job = {
        **JOB,
        "candidates": [{"appno": "2600827001", "status": "S", "post": "Research Assistant"}],
    }
    state = record_check(
        tmp_path / "state",
        "2600827001",
        job=job,
        result="no_change",
        changes={"jd_changed": False, "added": [], "removed": [], "status_changed": {}},
        at="2026-08-31T10:00:00+08:00",
    )
    assert state["last_check"]["posts"] == {"2600827001": "Research Assistant"}
