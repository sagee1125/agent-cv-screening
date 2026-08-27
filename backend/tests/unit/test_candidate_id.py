# Unit tests for composite candidate identity (refno + appno, never a personal name).
from screening_core.candidate_id import appno_from_filename, format_candidate_label, refno_from_url


# Application no. is taken from the CV filename, stripping an optional refno prefix.
def test_appno_from_filename_strips_refno_prefix() -> None:
    assert appno_from_filename("123456", "260818001") == "123456"
    assert appno_from_filename("260818001_654321", "260818001") == "654321"
    assert appno_from_filename("extracted-123456", None) == "123456"


# On-screen labels are refno/appno, never a name (including first-letter masks).
def test_format_candidate_label_never_uses_a_name() -> None:
    assert format_candidate_label("260818001", "123456") == "260818001/123456"
    assert format_candidate_label(None, "123456") == "123456"
    assert format_candidate_label("260818001", None) == "260818001/unknown"


# JAS records URLs carry the job refno in the query string.
def test_refno_from_url() -> None:
    assert (
        refno_from_url("https://jobs.polyu.edu.hk/internal/records.php?refno=260818001")
        == "260818001"
    )
    assert refno_from_url(None) is None
