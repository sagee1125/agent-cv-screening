# Unit tests for JD source-excerpt location helpers.
from __future__ import annotations

from app.services.jd_parser.provenance import find_cue_excerpt, find_source_excerpt


SAMPLE = """Senior Backend Engineer

Requirements:
- 3+ years of experience with Python and FastAPI
- Must have postgres
- Bachelor's degree preferred
- Visa sponsorship available
"""


def test_find_source_excerpt_returns_original_line() -> None:
    """A skill needle returns the stripped original bullet line and its span."""
    result = find_source_excerpt(SAMPLE, ["Python"])
    assert result["source_sentence"] == "3+ years of experience with Python and FastAPI"
    start = result["source_char_start"]
    end = result["source_char_end"]
    assert SAMPLE[start:end] == result["source_sentence"]


def test_find_source_excerpt_empty_when_missing() -> None:
    """Needles that never appear in the JD yield an empty excerpt."""
    result = find_source_excerpt(SAMPLE, ["telepathy"])
    assert result["source_sentence"] == ""
    assert result["source_char_start"] == 0
    assert result["source_char_end"] == 0


def test_find_cue_excerpt_for_requirement_line() -> None:
    """Requirement cues return the matching original line."""
    assert find_cue_excerpt(SAMPLE, ["bachelor"]).startswith("Bachelor")
    assert find_cue_excerpt(SAMPLE, ["visa"]).startswith("Visa")
    assert find_cue_excerpt(SAMPLE, ["french"]) == ""
