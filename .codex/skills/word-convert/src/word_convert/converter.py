# Converts Word documents to PDF locally, so the privacy pipeline (masking,
# page redaction, OCR) keeps working on one input format only.
from __future__ import annotations

import logging
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_WORD_PDF_FORMAT = 17  # Word's wdFormatPDF
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0"


# Routes a submission by content: "pdf", "doc", "docx" or "other".
def detect_kind(path: Path) -> str:
    with path.open("rb") as file_obj:
        header = file_obj.read(8)
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header[:4] == _OLE2_MAGIC:
        return "doc"
    if header[:2] == b"PK" and _is_docx(path):
        return "docx"
    return "other"


# Converts a Word file (any extension) to PDF at the explicit target path.
# A file that is already a real PDF is copied to the target unchanged.
def convert_to_pdf(source: Path, target: Path) -> tuple[Path, str]:
    kind = detect_kind(source)
    if kind == "pdf":
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target, "already_pdf"
    if kind not in {"doc", "docx"}:
        raise ValueError("Unsupported file type; submit a PDF or a Word document.")
    target.parent.mkdir(parents=True, exist_ok=True)
    # A submission can carry the wrong extension (an OLE2 stream named .pdf);
    # Word and LibreOffice refuse such files, so stage a correctly named copy.
    staged = target.with_suffix(f".{kind}")
    shutil.copyfile(source, staged)
    errors: list[str] = []
    try:
        for backend in (_convert_with_word_com, _convert_with_soffice):
            target.unlink(missing_ok=True)
            backend_error: Exception | None = None
            try:
                backend(staged, target)
            except Exception as exc:  # cleanup noise must not mask a produced PDF
                backend_error = exc
            if target.is_file() and target.stat().st_size > 0:
                logger.info("Converted .%s to PDF via %s.", kind, backend.__name__)
                return target, backend.__name__
            if backend_error is not None:
                errors.append(f"{backend.__name__}: {backend_error}")
        if kind == "docx":
            target.unlink(missing_ok=True)
            try:
                _convert_docx_via_text(staged, target)
                if target.is_file() and target.stat().st_size > 0:
                    logger.info("Converted .docx to text-layer PDF (offline fallback).")
                    return target, "docx_text"
            except Exception as exc:
                errors.append(f"_convert_docx_via_text: {exc}")
        elif kind == "doc":
            # Pure-code last resort for legacy .doc: a machine with neither
            # Word nor LibreOffice must still produce a scannable text-layer
            # PDF, so the offline text extraction covers .doc as well.
            target.unlink(missing_ok=True)
            try:
                from word_convert.doc_text import extract_text_from_doc

                paragraphs = [
                    line.strip()
                    for line in extract_text_from_doc(staged).splitlines()
                    if line.strip()
                ]
                if not paragraphs:
                    raise ValueError("no text recovered from the .doc piece table")
                _typeset_text_pdf(paragraphs, target)
                if target.is_file() and target.stat().st_size > 0:
                    logger.info("Converted .doc to text-layer PDF (offline extraction).")
                    return target, "doc_text"
            except Exception as exc:
                errors.append(f"_convert_doc_text: {exc}")
    finally:
        staged.unlink(missing_ok=True)
    raise ValueError(f"Could not convert this .{kind} file to PDF locally. " + " | ".join(errors))


# A .docx is a ZIP archive containing word/document.xml.
def _is_docx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


# Highest fidelity: drives the installed Microsoft Word via COM (Windows).
def _convert_with_word_com(source: Path, target: Path) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        # msoAutomationSecurityForceDisable: open without running macros, so
        # macro prompts can never block an unattended conversion.
        word.AutomationSecurity = 3
        document = word.Documents.Open(
            str(source), ReadOnly=True, ConfirmConversions=False, AddToRecentFiles=False
        )
        if document is None:
            raise RuntimeError("Word refused to open the document")
        try:
            document.SaveAs2(str(target), FileFormat=_WORD_PDF_FORMAT)
        except AttributeError:
            # Word 2007 exposes only SaveAs, not SaveAs2.
            document.SaveAs(str(target), FileFormat=_WORD_PDF_FORMAT)
    finally:
        # Old Word builds can raise from Close/Quit themselves; cleanup is
        # best-effort because success is judged by the produced PDF.
        try:
            if document is not None:
                document.Close(False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


# Cross-platform fallback: LibreOffice headless, when installed.
def _convert_with_soffice(source: Path, target: Path) -> None:
    soffice = shutil.which("soffice") or _soffice_candidate()
    if not soffice:
        raise RuntimeError("LibreOffice not found")
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(target.parent), str(source)],
        capture_output=True,
        timeout=180,
        check=True,
    )
    produced = target.parent / f"{source.stem}.pdf"
    if not produced.is_file():
        raise RuntimeError("LibreOffice produced no PDF")
    if produced != target:
        produced.replace(target)


def _soffice_candidate() -> str | None:
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


# Typesets plain paragraphs into a simple text-layer PDF (the shared tail of
# both offline paths). Screening only needs the text layer; layout is lost.
def _typeset_text_pdf(paragraphs: list[str], target: Path) -> None:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas as pdf_canvas

    if not paragraphs:
        raise ValueError("no text to typeset")

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font = "STSong-Light"
    except Exception:
        font = "Helvetica"

    buffer = BytesIO()
    page_width, page_height = A4
    margin = 2 * cm
    line_height = 11 * 1.35
    max_lines_per_page = max(1, int((page_height - 2 * margin) / line_height))
    renderer = pdf_canvas.Canvas(buffer, pagesize=A4)
    lines: list[str] = []
    for paragraph in paragraphs:
        wrapped = _wrap(paragraph, font, page_width - 2 * margin)
        lines.extend(wrapped if wrapped else [""])
    for start in range(0, len(lines), max_lines_per_page):
        renderer.setFont(font, 11)
        y = page_height - margin
        for line in lines[start : start + max_lines_per_page]:
            renderer.drawString(margin, y, line)
            y -= line_height
        renderer.showPage()
    renderer.save()
    target.write_bytes(buffer.getvalue())


# Last-resort offline path for .docx: pull the text out of the XML and typeset
# a simple text-layer PDF with reportlab. No layout survives, but the
# screening parser only needs the text layer, and every masking rule applies.
def _convert_docx_via_text(source: Path, target: Path) -> None:
    paragraphs = _docx_paragraphs(source)
    if not paragraphs:
        raise ValueError("No text found inside the .docx")
    _typeset_text_pdf(paragraphs, target)


# Extracts paragraph text (including table cells) from a .docx archive.
def _docx_paragraphs(source: Path) -> list[str]:
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(source) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        if text.strip():
            paragraphs.append(text.strip())
    return paragraphs


def _wrap(text: str, font: str, max_width: float) -> list[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines: list[str] = []
    current = ""
    for char in text:
        if stringWidth(current + char, font, 11) <= max_width:
            current += char
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines
