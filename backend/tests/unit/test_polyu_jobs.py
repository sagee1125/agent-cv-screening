# Unit tests for PolyU listing and job-detail HTML parsers.
from __future__ import annotations

from datetime import datetime

from app.services.polyu_jobs import (
    build_job_description,
    html_to_text,
    parse_detail_html,
    parse_listing_html,
    parse_polyu_date,
)


LISTING_HTML = """
<table>
  <tr>
    <th>Department / Unit</th>
    <th>Position</th>
    <th>Closing / Initial Screening Date</th>
    <th>Ref. No.</th>
  </tr>
  <tr class="ITS_clickableTableRow" data-href="job_detail.php?job=260818008" style="cursor:pointer;">
    <td>Office of Faculty of Science</td>
    <td>Assistant Officer</td>
    <td>24 August 2026</td>
    <td>260818008-IE</td>
  </tr>
  <tr class="ITS_clickableTableRow" data-href="job_detail.php?job=260814011" style="cursor:pointer;">
    <td>Human Resources Office</td>
    <td>Clerk / Human Resources Assistant (Temporary Appointment)</td>
    <td>21 August 2026</td>
    <td>260814011</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<main class="page-content">
  <p class="hro_topic"><strong>Office of Faculty of Science</strong></p>
  <h2><strong>Assistant Officer</strong></h2>
  <p class="hro_ref">(Ref. 260818008-IE)</p>
  <p><strong>Duties</strong></p>
  <p>The appointee will be required to:</p>
  <p>(a) provide administrative support to various committees and meetings;</p>
  <form action="apply.php" method="GET"><button>Apply Now</button></form>
  <p>The closing date for application is 24 August 2026.</p>
  Posting date: 18 August 2026
</main>
"""


def test_parse_listing_html_extracts_position_as_title() -> None:
    """Map table Position cells to listing titles and keep Ref. No. unique."""
    items = parse_listing_html(LISTING_HTML, base_url="https://jobs.polyu.edu.hk")
    assert len(items) == 2
    assert items[0].title == "Assistant Officer"
    assert items[0].external_ref == "260818008-IE"
    assert items[0].job_code == "260818008"
    assert items[0].department == "Office of Faculty of Science"
    assert items[0].closing_date == datetime(2026, 8, 24)
    assert items[0].detail_url == "https://jobs.polyu.edu.hk/job_detail.php?job=260818008"
    assert items[1].external_ref == "260814011"


def test_parse_detail_html_extracts_jd_and_posting_date() -> None:
    """Pull JD body text and posting date from a job_detail page."""
    text, posting_date = parse_detail_html(DETAIL_HTML)
    assert "provide administrative support" in text
    assert "Apply Now" not in text
    assert posting_date == datetime(2026, 8, 18)


def test_build_job_description_includes_department_and_ref() -> None:
    """Keep department and Ref. No. in the stored JD description."""
    items = parse_listing_html(LISTING_HTML, base_url="https://jobs.polyu.edu.hk")
    description = build_job_description(items[0], "JD body")
    assert "Department / Unit: Office of Faculty of Science" in description
    assert "Ref. No.: 260818008-IE" in description
    assert "JD body" in description


def test_html_to_text_decodes_entities() -> None:
    """Decode HTML entities used in PolyU JD copy."""
    assert html_to_text("Faculty&rsquo;s events") == "Faculty’s events"


def test_parse_polyu_date_rejects_open_ended_values() -> None:
    """Parse calendar dates and ignore open-ended closing date text."""
    assert parse_polyu_date("Until the position is filled") is None
    assert parse_polyu_date("5 August 2026") == datetime(2026, 8, 5)
