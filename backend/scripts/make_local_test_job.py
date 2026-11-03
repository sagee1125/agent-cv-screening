"""Generate a synthetic local test job for offline end-to-end screening.

Produces a JAS-style export folder (records.html + cvs/) with FAKE applicants
that deliberately cover the engine's interesting paths, so everything except
the internal-web browser flow can be tested on a machine with no JAS access:

  9900001  full-time   clean text PDF, "Last, First" comma header name
  9900002  full-time   text PDF, honorific header name, name repeated in a
                       publications line (mask-every-occurrence regression)
  9900003  part-time   Word .docx bytes stored under a .pdf name (the JAS
                       Word-submission case; converts locally, no web)
  9900004  part-time   scanned/image-only PDF (local RapidOCR route)
  9900005  full-time   BLANK "Post applied for" (FR-7: reported for HR
                       confirmation, never silently grouped or dropped)
  9900006  part-time   records row with NO CV (warning-card path)

Usage:
    python backend/scripts/make_local_test_job.py --out <dir> [--refno 999990001]

Then run the whole chain offline (no browser, no internal network):
    python .codex/skills/jas-import/scripts/run_jas_import.py parse-job \
        --html-file <dir>/records.html --output-dir <dir>/_out \
        --state-dir <dir>/_state --scratch-dir <dir>/_scratch --no-open

All persons, emails, phones and CVs are fictional. See docs/TEST-LOCALLY.md.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

REFNO_DEFAULT = "999990001"
CV_DIR_NAME = "cvs"

TEXT_CV_1 = """Tam, Hoi Ching
Email: hoi.ching.tam@example.com | Tel: +852 9123 0001
EDUCATION
BSc Computer Science, Test University, 2020-2024 (First Class Honours)
EXPERIENCE
Software Engineer, TestCorp Ltd, 2024-2026.
Built data pipelines in Python and SQL; deployed services on Docker and Kubernetes.
SKILLS
Python, SQL, Docker, Kubernetes, FastAPI, Machine Learning basics
"""

TEXT_CV_2 = """Dr. Lam Wing Yan
Email: wingyan.lam@example.com | Tel: +852 9123 0002
PROFILE
Research assistant in natural language processing with teaching experience.
EDUCATION
PhD Information Engineering, Test University, 2025
EXPERIENCE
Research Assistant, Test Lab, 2023-2026. Fine-tuned language models for
education applications; ran classroom experiments with 60 participants.
PUBLICATIONS
Lam Wing Yan et al. "Prompting tutors with LLMs", Workshop on Test NLP, 2025.
SKILLS
PyTorch, Transformers, Experiment design, Tutoring
"""

SCANNED_CV_TEXT = """Ng Au Yeung, Kai
Email: kai.ngauyeung@example.com | Tel: +852 9123 0004
SUMMARY
Part-time tutor with three years of weekend coding classes for teenagers.
SKILLS
Scratch, Python basics, Classroom management
"""

DOCX_PARAGRAPHS = [
    "Poon Chi Wai",
    "Email: chiwai.poon@example.com | Tel: +852 9123 0003",
    "EXPERIENCE",
    "Teaching Assistant, Test Learning Centre, 2022-2026. Ran small-group",
    "part-time tutorials; maintained student progress records in Excel.",
    "SKILLS",
    "Cantonese, English, Mandarin, Excel, Lesson planning",
]

DOCX_BODY = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
{}
</w:body></w:document>"""

DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCX_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _write_text_pdf(path: Path, text: str) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    y = 72
    for line in text.splitlines():
        page.insert_text((72, y), line, fontname="helv", fontsize=11)
        y += 16
    document.save(path)
    document.close()


def _write_scanned_pdf(path: Path, text: str) -> None:
    """Image-only PDF: render the text to a pixmap, embed just the image."""
    import pymupdf

    source = pymupdf.open()
    page = source.new_page()
    y = 72
    for line in text.splitlines():
        page.insert_text((72, y), line, fontname="helv", fontsize=11)
        y += 16
    pixmap = page.get_pixmap(dpi=200)
    image_bytes = pixmap.tobytes("png")
    source.close()

    scanned = pymupdf.open()
    target = scanned.new_page()
    target.insert_image(target.rect, stream=image_bytes)
    scanned.save(path)
    scanned.close()


def _write_docx_named_pdf(path: Path, paragraphs: list[str]) -> None:
    body = DOCX_BODY.format(
        "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in paragraphs)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", DOCX_CONTENT_TYPES)
        archive.writestr("_rels/.rels", DOCX_RELS)
        archive.writestr("word/_rels/document.xml.rels", DOCX_DOC_RELS)
        archive.writestr("word/document.xml", body)


def _row(
    row_class: str,
    no: int,
    appno: str,
    post: str,
    cv: bool,
    surname: str,
    given: str,
) -> str:
    post_cell = f"<td class='{row_class}'>{post}</td>" if post else f"<td class='{row_class}'></td>"
    cv_cell = (
        f"<td class='{row_class}'><a href='file.php?t=cv&id={appno}&refno={REFNO_DEFAULT}'>cv</a></td>"
        if cv
        else f"<td class='{row_class}'></td>"
    )
    return f"""<tr>
<td class='{row_class}'>{no}</td><td class='{row_class}'>{appno}</td>{post_cell}
<td class='{row_class}'><a href='record_detail.php?id={appno}&refno={REFNO_DEFAULT}'>p</a></td>
<td class='{row_class}'>TBC</td><td class='{row_class}'>Ms/Mr</td>
<td class='{row_class}'>{surname}</td><td class='{row_class}'>{given}</td>
{cv_cell}<td class='{row_class}'></td><td class='{row_class}'>Test qualification</td>
<td class='{row_class}'>2026-01</td><td class='{row_class}'>Test Post / Test Org</td>
</tr>"""


def _records_html(refno: str) -> str:
    rows = "".join(
        [
            _row("f-data-1", 1, "9900001", "Research Assistant", True, "Tam", "Hoi Ching"),
            _row("f-data-2", 2, "9900002", "Research Assistant", True, "Lam", "Wing Yan"),
            _row("f-data-1", 3, "9900003", "Part-time Research Assistant", True, "Poon", "Chi Wai"),
            _row("f-data-2", 4, "9900004", "Part-time Research Assistant", True, "Ng", "Kai"),
            _row("f-data-1", 5, "9900005", "", True, "Cheung", "Siu Ming"),
            _row("f-data-2", 6, "9900006", "Part-time Research Assistant", False, "Wong", "Tai Man"),
        ]
    )
    return f"""<!DOCTYPE html>
<html><head><META http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Job Application Records</title></head><body>
<div id="main"><div id="middle">
<div id="topic">Research Assistant / Part-time Research Assistant ( Ref. No.: {refno} )</div>
<div id="subtopic">Department of Testing<br>LLM test platform project<br>Posting Date: 2026-01-01</div>
</div>
<div id="middle-list"><p>Number of applications: 6</p>
<table id="f-list" class="listTable job-detail-table">
<thead><tr>
<th class="f-header">No.</th><th class="f-header">Application no.</th>
<th class="f-header">Post applied for</th>
<th class="f-header">Online job application form summary (printable version)</th>
<th class="f-header">Status</th><th class="f-header">Title</th>
<th class="f-header">Surname</th><th class="f-header">Given name</th>
<th class="f-header">Curriculum vitae</th>
<th class="f-header">Other supplementary information</th>
<th class="f-header">Highest qualification</th>
<th class="f-header">Job dates</th><th class="f-header">Job title / organization</th>
</tr></thead><tbody>{rows}</tbody></table>
<table id="f-list">
<tr><td class="f-header">Reference number</td><td class="f-data-1">{refno}</td></tr>
<tr><td class="f-header">Post title</td><td class="f-data-1">Research Assistant / Part-time Research Assistant</td></tr>
<tr><td class="f-header">Description</td><td class="f-data-1"><p>Test project: an LLM platform for tutoring.</p></td></tr>
<tr><td class="f-header">Qualifications</td><td class="f-data-1"><p>Applicants should have an honours degree or an equivalent qualification.</p></td></tr>
<tr><td class="f-header">Posting date</td><td class="f-data-1">2026-01-01</td></tr>
</table>
</div></div></body></html>"""


def generate(out_dir: Path, refno: str) -> Path:
    global REFNO_DEFAULT
    REFNO_DEFAULT = refno
    cvs = out_dir / CV_DIR_NAME
    cvs.mkdir(parents=True, exist_ok=True)
    _write_text_pdf(cvs / "9900001.pdf", TEXT_CV_1)
    _write_text_pdf(cvs / "9900002.pdf", TEXT_CV_2)
    _write_docx_named_pdf(cvs / "9900003.pdf", DOCX_PARAGRAPHS)
    _write_scanned_pdf(cvs / "9900004.pdf", SCANNED_CV_TEXT)
    _write_text_pdf(
        cvs / "9900005.pdf",
        "Cheung Siu Ming\nEmail: sm.cheung@example.com | Tel: +852 9123 0005\n"
        "SKILLS\nData entry, Office tools\n",
    )
    (out_dir / "records.html").write_text(_records_html(refno), encoding="utf-8")
    (out_dir / "README.txt").write_text(
        "SYNTHETIC TEST DATA - generated by make_local_test_job.py\n"
        "All persons, emails, phones and documents are fictional.\n"
        "9900003.pdf is really a .docx; 9900004.pdf is image-only (OCR path);\n"
        "9900005 has a blank post (FR-7); 9900006 has no CV at all.\n",
        encoding="utf-8",
    )
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic offline test job folder.")
    parser.add_argument("--out", required=True, help="Target folder to create.")
    parser.add_argument("--refno", default=REFNO_DEFAULT)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    generate(out, args.refno)
    print(f"[ok] synthetic job generated: {out}  (refno {args.refno})")
    print("Run the full offline chain with:")
    print(
        "  python .codex/skills/jas-import/scripts/run_jas_import.py parse-job "
        f"--html-file {out / 'records.html'} "
        f"--output-dir {out / '_out'} --state-dir {out / '_state'} "
        f"--scratch-dir {out / '_scratch'} --no-open"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
