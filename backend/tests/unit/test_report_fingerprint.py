# Unit tests for HR report fingerprints used to skip unchanged PDFs.
from __future__ import annotations

from screening_core.report_fingerprint import (
    board_report_fingerprint,
    candidate_report_fingerprint,
    input_run_payload,
    jd_inputs_changed,
    load_fingerprints,
    save_fingerprints,
    stale_cv_slugs,
)


# The same score artifacts produce a stable fingerprint; a score change does not.
def test_candidate_fingerprint_changes_with_score_file(tmp_path) -> None:
    score = tmp_path / "score.json"
    score.write_text('{"total_score": 80}', encoding="utf-8")
    first = candidate_report_fingerprint(
        engine="legacy",
        position="PA",
        refno="260818001",
        appno="123456",
        rank=1,
        total_score=80,
        tier="Tier 2",
        artifact_paths=[score],
    )
    second = candidate_report_fingerprint(
        engine="legacy",
        position="PA",
        refno="260818001",
        appno="123456",
        rank=1,
        total_score=80,
        tier="Tier 2",
        artifact_paths=[score],
    )
    assert first == second
    score.write_text('{"total_score": 90}', encoding="utf-8")
    third = candidate_report_fingerprint(
        engine="legacy",
        position="PA",
        refno="260818001",
        appno="123456",
        rank=1,
        total_score=90,
        tier="Tier 2",
        artifact_paths=[score],
    )
    assert third != first


# Board fingerprint covers the current candidate set only.
def test_board_fingerprint_and_roundtrip(tmp_path) -> None:
    fps = {"123456": "aaa", "654321": "bbb"}
    first = board_report_fingerprint(position="PA", refno="1", candidate_fingerprints=fps)
    second = board_report_fingerprint(position="PA", refno="1", candidate_fingerprints={"654321": "bbb", "123456": "aaa"})
    assert first == second
    save_fingerprints(tmp_path, {"candidates": fps, "board": first})
    loaded = load_fingerprints(tmp_path)
    assert loaded["board"] == first


# JD or engine changes invalidate resume; a replaced CV is marked stale.
def test_input_fingerprint_detects_jd_and_cv_changes(tmp_path) -> None:
    jd = tmp_path / "jd.txt"
    jd.write_text("role A", encoding="utf-8")
    cv = tmp_path / "123456.pdf"
    cv.write_bytes(b"%PDF-1")
    first = input_run_payload(
        engine="matching",
        position="PA",
        refno="1",
        jd_paths=[jd],
        cv_hashes={"123456": "aaa"},
    )
    jd.write_text("role B", encoding="utf-8")
    second = input_run_payload(
        engine="matching",
        position="PA",
        refno="1",
        jd_paths=[jd],
        cv_hashes={"123456": "aaa"},
    )
    assert jd_inputs_changed(first, second)
    third = input_run_payload(
        engine="matching",
        position="PA",
        refno="1",
        jd_paths=[jd],
        cv_hashes={"123456": "bbb"},
    )
    assert stale_cv_slugs(second, third) == ["123456"]
    assert not jd_inputs_changed({}, first)
