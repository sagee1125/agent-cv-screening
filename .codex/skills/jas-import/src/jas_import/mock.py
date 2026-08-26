# Generates synthetic (clearly fictional) JAS mock data for end-to-end testing.
from __future__ import annotations

from pathlib import Path

MOCK_REFNO = "260818001"
BASE_URL = "https://jobs.polyu.edu.hk/internal"

# Two fictional candidate profiles used by the mock generator.
_MOCK_PROFILES = (
    {
        "appno": "123456",
        "status": "S",
        "title": "Mr",
        "surname": "CHAN",
        "given": "Tai Man",
        "chinese": "陳大文",
        "hkid": "A123",
        "email": "chan.taiman@example.com",
        "phone": "6123 4567",
        "qualification": "Master of Science in Data Science, The Hong Kong Polytechnic University",
        "cur_period": "Sep 2024 - Present",
        "cur_post": "Data Analyst, ABC Data Services Limited",
        "prev_period": "Jul 2022 - Aug 2024",
        "prev_post": "Junior Data Analyst, XYZ Consulting Limited",
        "discipline": "Data analytics, database management, data visualisation",
        "years": "4",
        "available": "2026-09-01",
        "salary": "$ 28,000",
        "expected": "$ 32,000",
        "applied": "2026-08-10",
        "cv_name": "CHAN Tai Man",
        "cv_contact": "Email: chan.taiman@example.com | Phone: 6123 4567",
        "cv_sections": (
            ("PROFILE", "Data analyst with 4 years of experience in data analytics, data governance, and business intelligence."),
            ("EDUCATION",
             "MSc in Data Science, The Hong Kong Polytechnic University (2022)\n"
             "BSc in Statistics, The Chinese University of Hong Kong (2020)"),
            ("WORK EXPERIENCE",
             "Data Analyst, ABC Data Services Limited (Sep 2024 - Present)\n"
             "- Built ETL pipelines in Python and SQL\n"
             "- Developed Power BI dashboards for management reporting\n"
             "- Implemented data quality checks and data governance documentation\n\n"
             "Junior Data Analyst, XYZ Consulting Limited (Jul 2022 - Aug 2024)\n"
             "- Analysed business data using Python, SQL, and Excel\n"
             "- Automated weekly reporting with Python scripts"),
            ("SKILLS", "Python, SQL, Power BI, Tableau, Excel, Data Governance, Data Quality, ETL, Statistics"),
            ("PUBLICATIONS", "- \"A Practical Guide to Data Governance\" (internal whitepaper, 2025)"),
        ),
    },
    {
        "appno": "654321",
        "status": "TBC",
        "title": "Ms",
        "surname": "LEE",
        "given": "Wai Yan",
        "chinese": "李慧欣",
        "hkid": "B456",
        "email": "lee.waiyan@example.com",
        "phone": "9876 5432",
        "qualification": "Bachelor of Arts in Business Administration, City University of Hong Kong",
        "cur_period": "Jan 2024 - Present",
        "cur_post": "Administrative Assistant, DEF Group Limited",
        "prev_period": "Jul 2022 - Dec 2023",
        "prev_post": "Office Assistant, GHI Company Limited",
        "discipline": "Office administration, document management",
        "years": "2",
        "available": "2026-09-15",
        "salary": "$ 18,000",
        "expected": "$ 22,000",
        "applied": "2026-08-12",
        "cv_name": "LEE Wai Yan",
        "cv_contact": "Email: lee.waiyan@example.com | Phone: 9876 5432",
        "cv_sections": (
            ("PROFILE", "Administrative assistant with 2 years of experience in office administration and document management."),
            ("EDUCATION", "BA in Business Administration, City University of Hong Kong (2022)"),
            ("WORK EXPERIENCE",
             "Administrative Assistant, DEF Group Limited (Jan 2024 - Present)\n"
             "- Maintained office records and databases\n"
             "- Prepared reports and presentations using Excel and Word\n\n"
             "Office Assistant, GHI Company Limited (Jul 2022 - Dec 2023)\n"
             "- Provided general clerical and administrative support"),
            ("SKILLS", "Excel, Word, PowerPoint, Outlook, Document Management, Basic Python"),
        ),
    },
)

# The 39 JAS candidate-table column headers (kept in real page order).
def _headers() -> list[str]:
    return [
        "No.", "Application no.", "Online job application form summary (printable version)",
        "Status", "Title", "Surname", "Given name", "Name in Chinese",
        "HKID card / Passport no. (first 4 digits)", "Former PolyU staff / Serving PolyU staff",
        "PolyU staff no.", "Email address", "Contact telephone number", "Curriculum vitae",
        "Other supplementary information", "Appraisal document(s)",
        "Highest / Relevant academic qualification and / or professional license",
        "Start date and end date of current / most recent full-time job",
        "Post title and organization of current / most recent full-time job",
        "Start date and end date of last / second last full-time job",
        "Post title and organization of last / second last full-time job",
        "Discipline(s) / Area(s) of expertise",
        "Total no. of year(s) of post-qualification experience", "Earliest available date",
        "Present / Most recent monthly salary (HK$)", "Other income",
        "Expected monthly salary (HK$)", "Other expectation (e.g. allowance, and / or fringe benefits)",
        "Have a close relationship with any serving PolyU staff?", "Relationship detail",
        "Convicted of any criminal offences in Hong Kong or other places?", "Criminal offence detail",
        "Applying for promotion or transfer", "Have the required appraisal rating(s) for promotion?",
        "I learned of this vacancy from", "Referrer's name", "Application date",
        "HR internal remark", "HR internal document",
    ]


# Wrap one value as a JAS data cell.
def _cell(value: str) -> str:
    return f'<td class="f-data-1" style="text-align:left">{value}</td>'


# Build the status cell where the current status is plain text and the rest are links.
def _status_cell(refno: str, appno: str, current: str) -> str:
    parts = []
    for opt in ("TBC", "P", "S", "N"):
        if opt == current:
            parts.append(opt)
        else:
            parts.append(
                f'<a href="{BASE_URL}/records.php?appno={appno}&amp;refno={refno}&amp;appstatus={opt}">{opt}</a>'
            )
    return " ".join(parts)


# Build the printable application-form link cell.
def _record_detail_cell(refno: str, appno: str) -> str:
    return (
        f'<a href="{BASE_URL}/record_detail.php?id={appno}&amp;refno={refno}">'
        f'<img src="print_blue.png" alt="Printable form"></a>'
    )


# Build the CV download link cell.
def _cv_cell(refno: str, appno: str) -> str:
    return (
        f'<a href="{BASE_URL}/file.php?t=cv&amp;id={appno}&amp;refno={refno}">'
        f'<img src="download_purple.png" alt="Download CV"></a>'
    )


# Render one candidate as a full 39-cell JAS table row.
def _candidate_row(refno: str, no: str, profile: dict) -> str:
    values = [
        no,
        profile["appno"],
        _record_detail_cell(refno, profile["appno"]),
        _status_cell(refno, profile["appno"], profile["status"]),
        profile["title"],
        profile["surname"],
        profile["given"],
        profile["chinese"],
        profile["hkid"],
        "No",
        "",
        profile["email"],
        profile["phone"],
        _cv_cell(refno, profile["appno"]),
        "",
        "",
        profile["qualification"],
        profile["cur_period"],
        profile["cur_post"],
        profile["prev_period"],
        profile["prev_post"],
        profile["discipline"],
        profile["years"],
        profile["available"],
        profile["salary"],
        "",
        profile["expected"],
        "",
        "No",
        "",
        "No",
        "",
        "No",
        "N/A",
        "PolyU website",
        "",
        profile["applied"],
        "",
        "",
    ]
    assert len(values) == 39, len(values)
    return "<tr>\n" + "\n".join("  " + _cell(value) for value in values) + "\n</tr>"


# Build the JD rows of the Job advertisement information table.
def _jd_rows(refno: str) -> list[tuple[str, str]]:
    description = """
<p style="text-align: justify;">The appointee will be required to:</p>
<p style="text-align: justify;">(a) assist in the design and implementation of data governance and data management frameworks;</p>
<p style="text-align: justify;">(b) develop and maintain data pipelines and ETL processes using Python and SQL;</p>
<p style="text-align: justify;">(c) prepare data dashboards and visualisation reports using Power BI;</p>
<p style="text-align: justify;">(d) support data quality assurance, documentation, and user training;</p>
<p style="text-align: justify;">(e) perform any other duties as assigned by the supervisor.</p>
<p style="text-align: justify;">Applicants should have:</p>
<p style="text-align: justify;">(a) a good honours degree in Computer Science, Data Science, Statistics, Information Systems, or related disciplines;</p>
<p style="text-align: justify;">(b) at least two years of post-qualification experience in data analysis, data management, or related fields;</p>
<p style="text-align: justify;">(c) solid programming skills in Python and SQL;</p>
<p style="text-align: justify;">(d) good command of written and spoken English and Chinese;</p>
<p style="text-align: justify;">(e) good communication and interpersonal skills.</p>
"""
    return [
        ("Reference number", refno),
        ("Job group", "Research / Project Posts"),
        ("Unit", "Institute for Higher Education Research and Development"),
        ("Post title", "Project Associate"),
        ("Appointment Period", "12 months"),
        ("Project Title", "Design and implementation of data governance and data management"),
        ("Description", description),
        ("Conditions of service  (display to external ads only)",
         "<p><strong>Conditions of Service</strong></p><p>A highly competitive remuneration package will be offered.</p>"),
        ("Description", "<p><strong>Consideration of applications will commence on 1 Aug 2026 until the position is filled.</strong></p>"),
        ("Posting date", "2026-08-01"),
        ("List in external/internal", "Internal Advertisement"),
    ]


# Build the full mock records.php job-detail HTML page.
def mock_records_html(refno: str = MOCK_REFNO) -> str:
    header_html = "<tr>\n" + "\n".join(
        f'  <th class="f-header">{header}</th>' for header in _headers()
    ) + "\n</tr>"
    rows = "\n".join(_candidate_row(refno, str(i), profile) for i, profile in enumerate(_MOCK_PROFILES, start=1))
    jd_html = "\n".join(
        f"<tr>\n  <td class=\"f-header\">{label}</td>\n  <td class=\"f-data-1\">{value}</td>\n</tr>"
        for label, value in _jd_rows(refno)
    )
    return f"""<!DOCTYPE html>
<html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Job Application Records</title>
<!-- SYNTHETIC MOCK DATA - NOT A REAL JAS EXPORT -->
</head><body>
<div id="main"><div id="middle">
<div id="topic" style="line-height:1.2em;">Project Associate ( Ref. No.: {refno} ) </div>
<div id="subtopic">Institute for Higher Education Research and Development<br>Design and implementation of data governance and data management<br>Posting Date: 2026-08-01</div>
</div>
<div id="middle-list">
<p>Number of applications: 02</p>
<p>Status<br>T: TBC<br>P: Potential<br>S: Shortlisted<br>N: Not Appointable<br></p>
<table id="f-list" class="listTable job-detail-table">
<thead>
{header_html}
</thead>
<tbody>
{rows}
</tbody>
</table>
<p>Job advertisement information</p>
<table id="f-list" style="margin:0px;">
<tbody>
{jd_html}
</tbody>
</table>
</div></div>
</body></html>
"""


# Build the mock records list HTML page.
def mock_list_html(refno: str = MOCK_REFNO) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Job Application Records</title>
<!-- SYNTHETIC MOCK DATA - NOT A REAL JAS EXPORT -->
</head><body>
<div id="main"><div id="middle">
<div id="topic">Welcome to the Job Application System!<br><br><br>Job Applications Records</div>
<div id="subtopic">Please click "View" to open the job application(s) received for each post</div>
</div>
<div id="middle-list">
<table id="f-list" class="listTable job-table">
<thead>
<tr>
<th class="f-header">Ref no.</th><th class="f-header">Job group</th><th class="f-header">Unit</th>
<th class="f-header">Post title</th><th class="f-header">Posting date</th><th class="f-header">Closing / Initial screening date</th>
<th class="f-header">Off-shelf date</th><th class="f-header">List in external/internal</th>
<th class="f-header">Number of applications</th><th class="f-header">Email notification for job application</th>
</tr>
</thead>
<tbody>
<tr>
<td class="f-data-1">{refno}<br><a class="status_button" style="background-color:green; color:#FFF" href="{BASE_URL}/records.php?refno={refno}" target="_blank">View</a></td>
<td class="f-data-1">Research / Project Posts</td>
<td class="f-data-1">Institute for Higher Education Research and Development</td>
<td class="f-data-1">Project Associate</td>
<td class="f-data-1">2026-08-01</td>
<td class="f-data-1">2026-08-24</td>
<td class="f-data-1">2027-02-01</td>
<td class="f-data-1">Internal Advertisement</td>
<td class="f-data-1">02</td>
<td class="f-data-1">****</td>
</tr>
</tbody>
</table>
</div></div>
</body></html>
"""


# Render one synthetic CV PDF with reportlab.
def _write_cv_pdf(path: Path, profile: dict) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    styles = getSampleStyleSheet()
    story = [
        Paragraph(profile["cv_name"], styles["Title"]),
        Paragraph(profile["cv_contact"], styles["Normal"]),
        Paragraph("<i>SYNTHETIC SAMPLE DATA &mdash; NOT A REAL PERSON</i>", styles["Normal"]),
        Spacer(1, 10),
    ]
    for heading, body in profile["cv_sections"]:
        story.append(Paragraph(heading, styles["Heading2"]))
        for line in body.splitlines():
            if line.strip():
                story.append(Paragraph(line, styles["BodyText"]))
        story.append(Spacer(1, 8))
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


# Generate the full mock JAS folder (list.html, records.html, cvs/, README.txt).
def generate_mock_jas_dir(target_dir: str | Path, *, refno: str = MOCK_REFNO) -> Path:
    root = Path(target_dir)
    cvs_dir = root / "cvs"
    cvs_dir.mkdir(parents=True, exist_ok=True)
    (root / "list.html").write_text(mock_list_html(refno), encoding="utf-8")
    (root / "records.html").write_text(mock_records_html(refno), encoding="utf-8")
    for profile in _MOCK_PROFILES:
        _write_cv_pdf(cvs_dir / f"{profile['appno']}.pdf", profile)
    (root / "README.txt").write_text(
        "SYNTHETIC / MOCK DATA - FOR TESTING ONLY\n"
        "Generated by the agent-cv-screening project.\n"
        "All persons, emails, phones, HKIDs, and salaries are fictional.\n"
        "Do NOT use for real recruitment; do not confuse with real JAS exports.\n",
        encoding="utf-8",
    )
    return root


__all__ = [
    "MOCK_REFNO",
    "generate_mock_jas_dir",
    "mock_list_html",
    "mock_records_html",
]