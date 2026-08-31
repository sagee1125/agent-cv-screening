# Unit tests for the JAS internal records HTML parsers.
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# backend/tests/unit/test_jas_import.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
JAS_SRC = REPO_ROOT / ".codex" / "skills" / "jas-import" / "src"
sys.path.insert(0, str(JAS_SRC))

from jas_import.records import (  # noqa: E402
    build_jd_text,
    parse_job_html,
    parse_list_html,
)
from jas_import.skill import parse_job_skill, parse_list_skill  # noqa: E402


LIST_HTML = """
<html><body>
<table id="f-list" class="listTable job-table">
  <thead>
    <tr><th>Ref no.</th><th>Job group</th><th>Unit</th><th>Post title</th><th>Posting date</th><th>Closing date</th><th>Off-shelf date</th><th>List type</th><th>Number of applications</th><th>Email notification</th></tr>
    <tr class="fancySearchRow"><th><input placeholder="Filter..."></th><th><input></th><th><input></th><th><input></th><th><input></th><th><input></th><th><input></th><th><input></th><th><input></th><th><input></th></tr>
  </thead>
  <tbody>
    <tr>
      <td class="f-data-1">190001010<br><a class="status_button" href="https://jobs.polyu.edu.hk/internal/records.php?refno=190001010" target="_blank">View</a></td>
      <td class="f-data-1">Research / Project Posts</td>
      <td class="f-data-1">Institute for Higher Education Research and Development </td>
      <td class="f-data-1">Project Associate</td>
      <td class="f-data-1">1900-01-01</td>
      <td class="f-data-1">1900-01-01</td>
      <td class="f-data-1">1900-01-01</td>
      <td class="f-data-1">External Advertisement</td>
      <td class="f-data-1">01</td>
      <td class="f-data-1">****</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

JOB_HTML = """
<html><body>
<table id="f-list" class="listTable job-detail-table">
  <thead>
    <tr><th>No.</th><th>Application no.</th><th>Online job application form summary</th><th>Status</th><th>Title</th><th>Surname</th><th>Given name</th><th>Chinese</th><th>HKID</th><th>Former staff</th><th>Staff no.</th><th>Email</th><th>Phone</th><th>Curriculum vitae</th><th>Supplementary</th></tr>
  </thead>
  <tbody>
    <tr>
      <td class="f-data-1">1</td>
      <td class="f-data-1">123456</td>
      <td class="f-data-1"><a href="https://jobs.polyu.edu.hk/internal/record_detail.php?id=123456&amp;refno=190001010"><img src="print_blue.png"></a></td>
      <td class="f-data-1">TBC <a href="https://jobs.polyu.edu.hk/internal/records.php?appno=123456&amp;refno=190001010&amp;appstatus=P">P</a> <a href="https://jobs.polyu.edu.hk/internal/records.php?appno=123456&amp;refno=190001010&amp;appstatus=S">S</a> <a href="https://jobs.polyu.edu.hk/internal/records.php?appno=123456&amp;refno=190001010&amp;appstatus=N">N</a></td>
      <td class="f-data-1">**</td>
      <td class="f-data-1">CHAN</td>
      <td class="f-data-1">Tai Man</td>
      <td class="f-data-1">陳大文</td>
      <td class="f-data-1">A123</td>
      <td class="f-data-1">No</td>
      <td class="f-data-1"></td>
      <td class="f-data-1">chan@example.com</td>
      <td class="f-data-1">91234567</td>
      <td class="f-data-1"><a href="https://jobs.polyu.edu.hk/internal/file.php?t=cv&amp;id=123456&amp;refno=190001010"><img src="download_purple.png"></a></td>
      <td class="f-data-1"></td>
    </tr>
  </tbody>
</table>
<p>Job advertisement information</p>
<table id="f-list" style="margin:0px;">
  <tbody>
    <tr><td class="f-header">Reference number</td><td class="f-data-1">190001010</td></tr>
    <tr><td class="f-header">Job group</td><td class="f-data-1">Research / Project Posts</td></tr>
    <tr><td class="f-header">Unit</td><td class="f-data-1">Institute for Higher Education Research and Development</td></tr>
    <tr><td class="f-header">Post title</td><td class="f-data-1">Project Associate</td></tr>
    <tr><td class="f-header">Appointment Period</td><td class="f-data-1">12 months</td></tr>
    <tr><td class="f-header">Project Title</td><td class="f-data-1">Data governance and data management</td></tr>
    <tr><td class="f-header">Description</td><td class="f-data-1"><p>Design and implement data governance and data management.</p></td></tr>
    <tr><td class="f-header">Conditions of service</td><td class="f-data-1"><p><strong>Conditions of Service</strong></p><p>A highly competitive remuneration package will be offered.</p></td></tr>
    <tr><td class="f-header">Posting date</td><td class="f-data-1">1900-01-01</td></tr>
    <tr><td class="f-header">List in external/internal</td><td class="f-data-1">External Advertisement</td></tr>
  </tbody>
</table>
</body></html>
"""


# Parse the JAS records list table into job rows.
def test_parse_list_html_extracts_job_rows() -> None:
    items = parse_list_html(LIST_HTML, base_url="https://jobs.polyu.edu.hk")
    assert len(items) == 1
    row = items[0]
    assert row.refno == "190001010"
    assert row.job_group == "Research / Project Posts"
    assert row.unit.strip() == "Institute for Higher Education Research and Development"
    assert row.post_title == "Project Associate"
    assert row.application_count == "01"
    assert row.records_url == "https://jobs.polyu.edu.hk/internal/records.php?refno=190001010"


# Parse the JAS job-detail page into JD fields and candidate references.
def test_parse_job_html_extracts_jd_and_candidates() -> None:
    detail = parse_job_html(JOB_HTML, base_url="https://jobs.polyu.edu.hk")
    assert detail.refno == "190001010"
    assert detail.post_title == "Project Associate"
    assert detail.unit == "Institute for Higher Education Research and Development"
    assert detail.appointment_period == "12 months"
    assert detail.project_title == "Data governance and data management"
    assert detail.posting_date == "1900-01-01"

    assert len(detail.candidates) == 1
    candidate = detail.candidates[0]
    assert candidate.appno == "123456"
    assert candidate.status == "TBC"
    assert candidate.cv_url == "https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=123456&refno=190001010"
    assert candidate.record_detail_url == "https://jobs.polyu.edu.hk/internal/record_detail.php?id=123456&refno=190001010"
    assert candidate.supp_url is None


# Candidate fields follow header labels when JAS inserts a new column.
def test_parse_job_html_maps_shifted_candidate_columns_by_header() -> None:
    shifted = JOB_HTML.replace(
        "<tr><th>No.</th><th>Application no.</th>",
        "<tr><th>No.</th><th>New field</th><th>Application no.</th>",
    ).replace(
        '<td class="f-data-1">1</td>\n      <td class="f-data-1">123456</td>',
        '<td class="f-data-1">1</td>\n      <td class="f-data-1">ignored</td>\n'
        '      <td class="f-data-1">123456</td>',
    )
    candidate = parse_job_html(shifted).candidates[0]
    assert candidate.appno == "123456"
    assert candidate.status == "TBC"
    assert candidate.cv_url and "id=123456" in candidate.cv_url


# Candidate rows without an application number or linked ID are omitted.
def test_parse_job_html_skips_candidate_without_appno() -> None:
    no_appno = JOB_HTML.replace(
        '<td class="f-data-1">123456</td>',
        '<td class="f-data-1"></td>',
        1,
    ).replace("id=123456", "id=", 2)
    assert parse_job_html(no_appno).candidates == []


# Build JD text from the advertisement information rows.
def test_build_jd_text_includes_description() -> None:
    detail = parse_job_html(JOB_HTML)
    text = build_jd_text(detail)
    assert "Post title: Project Associate" in text
    assert "Description: Design and implement data governance and data management." in text
    assert "Conditions of service: Conditions of Service A highly competitive remuneration package will be offered." in text


# Confirm the skill payload never carries identity columns from the candidate table.
def test_parse_job_skill_drops_candidate_pii() -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as handle:
        handle.write(JOB_HTML)
        html_file = handle.name

    payload = parse_job_skill(html_file)
    Path(html_file).unlink(missing_ok=True)

    assert payload["schema_version"] == "1.0.0"
    assert payload["status"] == "success"
    assert payload["refno"] == "190001010"
    assert len(payload["candidates"]) == 1

    candidate = payload["candidates"][0]
    assert set(candidate.keys()) == {"appno", "status", "cv_url", "supp_url", "record_detail_url"}

    raw_json = json.dumps(payload, ensure_ascii=False)
    assert "chan@example.com" not in raw_json
    assert "91234567" not in raw_json
    assert "CHAN" not in raw_json
    assert "陳大文" not in raw_json


# Parse the HR-provided sample files when they are present on this machine.
@pytest.mark.skipif(
    not (Path(r"C:\Users\User\Desktop\jasweb\Job Application Recordslist.html").is_file()),
    reason="HR sample files not available",
)
def test_parse_real_hr_sample_files() -> None:
    base = Path(r"C:\Users\User\Desktop\jasweb")
    list_payload = parse_list_skill(base / "Job Application Recordslist.html")
    assert list_payload["schema_version"] == "1.0.0"
    assert list_payload["status"] == "success"
    assert list_payload["items"][0]["refno"] == "190001010"

    job_payload = parse_job_skill(base / "Job Application Recordsrecords.html")
    assert job_payload["status"] == "success"
    assert job_payload["refno"] == "190001010"
    assert job_payload["candidates"][0]["appno"] == "123456"
    assert job_payload["candidates"][0]["status"] == "TBC"


# A status cell showing only "T" (other labels are links) maps to TBC.
def test_parse_job_status_single_t_maps_to_tbc() -> None:
    html = JOB_HTML.replace(
        'TBC <a href="https://jobs.polyu.edu.hk/internal/records.php?appno=123456&amp;refno=190001010&amp;appstatus=P">P</a>',
        'T <a href="https://jobs.polyu.edu.hk/internal/records.php?appno=123456&amp;refno=190001010&amp;appstatus=P">P</a>',
    )
    detail = parse_job_html(html)
    assert detail.candidates[0].status == "TBC"