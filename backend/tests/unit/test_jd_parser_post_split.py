# Unit tests for splitting a multi-post advertisement into a shared base plus one delta per post.
from __future__ import annotations

from jd_parser.post_split import (
    attributed_bases,
    post_names_in,
    split_advertisement,
    split_units,
)

# Mirrors the shape of the live multi-post advertisements: shared bullets plus a few that name
# a post, one of them naming it only in the last sentence of a two-sentence bullet.
SAMPLE = """Duties:
The appointees will assist the project leader. They will be required to:
lead the research programme across sites. This includes coordinating partners and reporting to the funder (applicable to Senior Fellow only);
maintain the laboratory equipment register;
perform any other duties as assigned by the project leader.
Qualifications:
Applicants for the Senior Fellow post should have a doctoral degree in Physics;
Applicants for the Research Assistant post should have a bachelor's degree in Physics;
have a good command of written English; and
have experience with Python.
"""

LABELS = ["Senior Fellow (Full-time)", "Senior Fellow (Part-time)", "Research Assistant"]


def test_split_units_strips_bullet_decoration() -> None:
    """One bullet per line, with leading dashes and bullets removed from the stored unit."""
    units = split_units("- first requirement\n* second requirement\n\n  • third requirement\n")
    assert units == ["first requirement", "second requirement", "third requirement"]


def test_attributed_bases_reads_the_prefix_form() -> None:
    """The "Applicants for the X post should have ..." form attributes to X."""
    bases = ["Senior Fellow", "Research Assistant"]
    assert attributed_bases("Applicants for the Senior Fellow post should have a degree", bases) == ["Senior Fellow"]


def test_attributed_bases_reads_the_parenthetical_forms() -> None:
    """Both measured parenthetical forms attribute, with or without the trailing "post"."""
    bases = ["Senior Fellow", "Research Assistant"]
    assert attributed_bases("maintain the register (applicable to Senior Fellow only)", bases) == ["Senior Fellow"]
    assert attributed_bases("have strong expertise in physics (for Senior Fellow post)", bases) == ["Senior Fellow"]


def test_attributed_bases_ignores_unrelated_parentheticals() -> None:
    """A parenthetical that merely starts with "for" must not attribute anything."""
    bases = ["Senior Fellow", "Research Assistant"]
    assert attributed_bases("have experience with Python (for example, pandas and numpy)", bases) == []
    assert attributed_bases("maintain the laboratory equipment register", bases) == []


def test_attributed_bases_drops_a_name_contained_in_a_longer_match() -> None:
    """When one base name is a prefix of another, only the longer name is attributed."""
    assert attributed_bases("Applicants for the Senior Fellow post should have a degree", ["Senior", "Senior Fellow"]) == [
        "Senior Fellow"
    ]


def test_split_advertisement_keeps_shared_bullets_in_the_base() -> None:
    """A bullet naming no post stays shared; the post-specific bullets leave the base."""
    split = split_advertisement(SAMPLE, LABELS)
    assert any("laboratory equipment register" in unit for unit in split.base_sentences)
    assert any("good command of written English" in unit for unit in split.base_sentences)
    assert any("perform any other duties" in unit for unit in split.base_sentences)


def test_split_advertisement_attributes_a_whole_multi_sentence_bullet() -> None:
    """A bullet whose attribution sits in its last sentence moves as a whole, not sentence by sentence."""
    split = split_advertisement(SAMPLE, LABELS)
    senior = split.delta_for("Senior Fellow (Full-time)")
    assert any("lead the research programme" in unit for unit in senior)
    assert any("This includes coordinating partners" in unit for unit in senior)
    # The reserved duty must not stay shared, or every other post would inherit it.
    assert not any("lead the research programme" in unit for unit in split.base_sentences)


def test_full_time_and_part_time_variants_share_one_delta() -> None:
    """Attribution matches base names, so the FT and PT variants of one post inherit the same bullets."""
    split = split_advertisement(SAMPLE, LABELS)
    assert split.delta_for("Senior Fellow (Full-time)") == split.delta_for("Senior Fellow (Part-time)")
    assert split.mentioned == ["Senior Fellow", "Research Assistant"]


def test_effective_text_is_the_base_plus_the_delta() -> None:
    """The effective JD for a post is the shared base with that post's delta appended."""
    split = split_advertisement(SAMPLE, LABELS)
    assistant = split.effective_text("Research Assistant")
    assert "have experience with Python" in assistant
    assert "bachelor's degree in Physics" in assistant
    assert "doctoral degree in Physics" not in assistant
    assert "lead the research programme" not in assistant
    assert split.effective_text("Research Assistant").startswith(split.base_text)


def test_unclaimed_reports_a_post_the_advertisement_names_but_nobody_applied_for() -> None:
    """A post the advertisement describes with no applicant has no group, so it is recorded, not guessed."""
    split = split_advertisement(SAMPLE, ["Senior Fellow (Full-time)", "Senior Fellow (Part-time)"])
    assert split.unclaimed == ["Research Assistant"]
    # Its requirements are recorded too, so the exclusion can be audited afterwards.
    assert split.unclaimed_sentences == {
        "Research Assistant": [
            "Applicants for the Research Assistant post should have a bachelor's degree in Physics;"
        ]
    }


# A requirement the advertisement reserves for a post nobody applied for must not fall through to
# the shared base: it would then be scored against every post that DID receive applications.
def test_unclaimed_post_requirement_never_reaches_the_shared_base() -> None:
    split = split_advertisement(SAMPLE, ["Senior Fellow (Full-time)", "Senior Fellow (Part-time)"])

    assert not any("bachelor's degree in Physics" in unit for unit in split.base_sentences)
    # Only the claimed post keeps a delta, so HR's per-post derivation is unaffected.
    assert split.mentioned == ["Senior Fellow"]
    assert [delta.label for delta in split.deltas] == ["Senior Fellow"]
    # So the claimed post's effective JD is free of the unclaimed post's requirement.
    assert "bachelor's degree in Physics" not in split.effective_text("Senior Fellow (Full-time)")
    # And a bullet naming no post is still shared by everyone.
    assert any("have experience with Python" in unit for unit in split.base_sentences)


def test_post_names_in_returns_the_attributed_names_in_order() -> None:
    """The names the advertisement attributes requirements to, deduplicated and ordered."""
    assert post_names_in(SAMPLE) == ["Senior Fellow", "Research Assistant"]


def test_single_post_advertisement_yields_no_deltas() -> None:
    """With no post labels there is nothing to attribute, so every bullet stays in the base."""
    split = split_advertisement(SAMPLE, [])
    assert split.deltas == []
    assert split.mentioned == []
    assert len(split.base_sentences) == len(split_units(SAMPLE))
