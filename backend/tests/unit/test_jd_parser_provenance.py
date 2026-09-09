# Unit tests for JD source-excerpt location helpers.
from __future__ import annotations

from app.services.jd_parser.provenance import find_cue_excerpt, find_line_excerpt, find_source_excerpt


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


def test_find_source_excerpt_skips_metadata_lines() -> None:
    """Excerpt lookup must ignore job-board header/footer lines."""
    text = (
        "Job group: Research / Project Posts\n"
        "Post title: Research Assistant\n"
        "Requirements:\n"
        "- experience with research and data analysis\n"
    )
    result = find_source_excerpt(text, ["research"])
    assert result["source_sentence"].startswith("experience with research")
    assert "Job group" not in result["source_sentence"]


# A technical sentence mentioning Cantonese precedes the real fluency requirement.
_CUE_TEXT = (
    "have experience in building natural language processing pipelines and/or audio processing "
    "pipelines covering automatic speech recognition and the handling of code-switched "
    "Cantonese-English-Putonghua speech; be fluent in Cantonese, English and Putonghua, with a "
    "strong command of written and spoken English."
)
_LANGUAGE_CUES = [
    "fluent",
    "fluency",
    "proficient",
    "proficiency",
    "spoken",
    "written",
    "command of",
    "working knowledge",
    "native",
]


def test_find_cue_excerpt_prefers_cue_word_sentence() -> None:
    """A later fluency sentence wins over an earlier technical language mention."""
    excerpt = find_cue_excerpt(_CUE_TEXT, ["Cantonese"], prefer_cues=_LANGUAGE_CUES)
    assert "be fluent in Cantonese, English and Putonghua" in excerpt
    assert "natural language processing" not in excerpt


def test_find_cue_excerpt_keeps_earliest_match_without_cues() -> None:
    """Without prefer_cues the helper still returns the earliest mention."""
    excerpt = find_cue_excerpt(_CUE_TEXT, ["Cantonese"])
    assert "code-switched Cantonese-English-Putonghua" in excerpt


def test_find_cue_excerpt_falls_back_when_no_cue_sentence() -> None:
    """No cue-bearing sentence means the earliest mention is still returned."""
    text = "handle code-switched Cantonese-English speech\nlater Cantonese subtitles"
    excerpt = find_cue_excerpt(text, ["Cantonese"], prefer_cues=_LANGUAGE_CUES)
    assert excerpt.startswith("handle code-switched Cantonese-English speech")
    assert "subtitles" not in excerpt


def test_find_line_excerpt_relocates_original_case() -> None:
    """A lower-cased detection line maps back to the original-cased sentence."""
    excerpt = find_line_excerpt(
        _CUE_TEXT,
        "be fluent in cantonese, english and putonghua, with a strong command of written and spoken english",
    )
    assert "be fluent in Cantonese, English and Putonghua" in excerpt
