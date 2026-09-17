# Unit tests for scrubbing contact details out of JD text before it reaches an HR report.
from __future__ import annotations

from report_gen.html_board import _jd_meta_panel, _scrub_contact


# Emails and phone-like numbers are replaced with a placeholder.
def test_scrub_contact_removes_emails_and_phones() -> None:
    text = "Enquiries: hr@polyu.example or telephone 2766 1234, fax 2364 9663."
    scrubbed = _scrub_contact(text)
    assert "hr@polyu.example" not in scrubbed
    assert "2766 1234" not in scrubbed
    assert "2364 9663" not in scrubbed
    assert "[email removed]" in scrubbed
    assert scrubbed.count("[phone removed]") == 2


# A named contact behind an academic or honorific title is removed.
def test_scrub_contact_removes_a_titled_name() -> None:
    text = "Applicants are invited to contact Prof. Jane Doe at telephone number 2766 5678."
    scrubbed = _scrub_contact(text)
    assert "Jane Doe" not in scrubbed
    assert "contact [name removed] at telephone number" in scrubbed


# A multi-part name is removed whole, not just its first token.
def test_scrub_contact_removes_a_multi_part_name() -> None:
    text = "Please contact Dr. Anna K. C. Wong via email for further information."
    scrubbed = _scrub_contact(text)
    assert "Wong" not in scrubbed
    assert "Anna" not in scrubbed
    assert "[name removed]" in scrubbed


# An untitled name is removed when the contact details follow it directly.
def test_scrub_contact_removes_an_untitled_name_before_contact_details() -> None:
    text = "Contact Jane Doe at fax number 2364 9663."
    scrubbed = _scrub_contact(text)
    assert "Jane Doe" not in scrubbed
    assert "[name removed]" in scrubbed


# Ordinary requirement prose must survive untouched: no capitalised word may be lost.
def test_scrub_contact_leaves_ordinary_requirement_text_alone() -> None:
    unchanged = [
        "contact the project leader for approval",
        "Please contact us for further information.",
        "contact Research staff about the project",
        "have experience with contact lens design",
        "Contact Details: see below",
        "the appointee will contact clients at their site",
        "Applicants for the Senior Project Fellow post should have a doctoral degree.",
        "have a good command of written and spoken English, including Cantonese",
    ]
    for text in unchanged:
        assert _scrub_contact(text) == text


# The advertisement text is scrubbed at render time only, so the audit copy keeps the original.
def test_jd_panel_scrubs_without_mutating_the_source_text() -> None:
    jd_text = (
        "Reference number: 260901004\n"
        "Description: Duties: run the project.\n"
        "Applicants are invited to contact Prof. Jane Doe at telephone number 2766 5678.\n"
    )
    panel = _jd_meta_panel(jd_text)
    assert "Jane Doe" not in panel
    assert "2766 5678" not in panel
    # The caller's copy is untouched, so _pipeline keeps the advertisement for audit.
    assert "Jane Doe" in jd_text
    assert "2766 5678" in jd_text
