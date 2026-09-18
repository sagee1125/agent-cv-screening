# Unit tests for HR report fingerprints used to skip unchanged PDFs.
from __future__ import annotations

from screening_core.report_fingerprint import (
    board_report_fingerprint,
    candidate_report_fingerprint,
    input_run_payload,
    jd_inputs_changed,
    load_fingerprints,
    post_changed_slugs,
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

# The JD digest changes the board fingerprint so a JD edit rebuilds the ranking board.
def test_board_fingerprint_changes_with_jd_digest() -> None:
    fps = {"123456": "aaa"}
    plain = board_report_fingerprint(position="PA", refno="1", candidate_fingerprints=fps)
    first = board_report_fingerprint(position="PA", refno="1", candidate_fingerprints=fps, jd_digest="aaa")
    second = board_report_fingerprint(position="PA", refno="1", candidate_fingerprints=fps, jd_digest="bbb")
    assert plain != first
    assert first != second
    repeat = board_report_fingerprint(position="PA", refno="1", candidate_fingerprints=fps, jd_digest="aaa")
    assert repeat == first


# A post re-assignment must not be read as "the advertisement changed": it invalidates the score of
# the applicant who moved, not the whole run's parse and every other post's score (FR-10).
def test_post_change_invalidates_one_slug_not_the_run(tmp_path) -> None:
    jd = tmp_path / "jd.txt"
    jd.write_text("role A", encoding="utf-8")

    def payload(posts: dict[str, str]) -> dict:
        return input_run_payload(
            engine="matching",
            position="PA",
            refno="1",
            jd_paths=[jd],
            cv_hashes={"260907001": "aaa", "260907002": "bbb"},
            posts=posts,
        )

    before = payload({"260907001": "Research Assistant", "260907002": "Research Associate"})
    after = payload({"260907001": "Research Assistant", "260907002": "Research Assistant"})

    # The advertisement is byte-identical, so nothing is re-parsed...
    assert jd_inputs_changed(before, after) is False
    # ...but the applicant who moved is scored against another JD, so their score is stale.
    assert post_changed_slugs(before, after) == ["260907002"]
    # An unchanged assignment invalidates nobody.
    assert post_changed_slugs(before, payload({"260907001": "Research Assistant", "260907002": "Research Associate"})) == []


# An applicant whose post became unreadable leaves the map entirely; their score is stale too.
def test_post_changed_slugs_covers_a_post_that_vanished(tmp_path) -> None:
    jd = tmp_path / "jd.txt"
    jd.write_text("role A", encoding="utf-8")

    def payload(posts: dict[str, str]) -> dict:
        return input_run_payload(
            engine="matching",
            position="PA",
            refno="1",
            jd_paths=[jd],
            cv_hashes={"260907001": "aaa", "260907002": "bbb"},
            posts=posts,
        )

    before = payload({"260907001": "Research Assistant", "260907002": "Research Associate"})
    after = payload({"260907001": "Research Assistant"})

    assert post_changed_slugs(before, after) == ["260907002"]


# Without a baseline there is nothing to compare, and a single-post run has no posts map at all.
def test_post_changed_slugs_needs_a_baseline_map(tmp_path) -> None:
    jd = tmp_path / "jd.txt"
    jd.write_text("role A", encoding="utf-8")
    current = input_run_payload(
        engine="matching",
        position="PA",
        refno="1",
        jd_paths=[jd],
        cv_hashes={"260907001": "aaa"},
        posts={"260907001": "Research Assistant"},
    )
    assert post_changed_slugs(None, current) == []
    assert post_changed_slugs({}, current) == []
    assert post_changed_slugs({"posts": None}, current) == []
