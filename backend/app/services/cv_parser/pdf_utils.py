# Extracts, redacts, and renders PDF content for local CV processing.
from __future__ import annotations

import base64
import io
from pathlib import Path

import pdfplumber
import pymupdf
import pypdfium2 as pdfium
from pypdf import PdfReader

from app.config import settings
from app.services.cv_parser.pii import EMAIL_PATTERN, PHONE_PATTERN, is_phone_candidate


# Extracts text from a PDF with pdfplumber.
def extract_with_pdfplumber(path: Path) -> str:
    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


# Extracts text from a PDF with pypdf as a compatibility fallback.
def extract_with_pypdf(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


# Extracts text with the same engine used to locate and redact PII.
def extract_with_pymupdf(path: Path) -> str:
    document = pymupdf.open(path)
    try:
        return "\n".join(page.get_text("text") for page in document).strip()
    finally:
        document.close()


# Renders original PDF pages for callers that do not require privacy redaction.
def render_pdf_pages_as_data_urls(file_path: str, max_pages: int) -> list[str]:
    # Render PDF pages to high-fidelity images for multimodal parsing.
    document = pdfium.PdfDocument(file_path)
    total_pages = len(document)
    if total_pages == 0:
        raise ValueError("PDF has no pages.")

    page_count = min(max_pages, total_pages)
    image_urls: list[str] = []
    image_format = settings.llm_vision_image_format.strip().upper()
    if image_format not in {"PNG", "JPEG"}:
        image_format = "PNG"
    for page_index in range(page_count):
        page = document[page_index]
        pil_image = page.render(scale=settings.llm_vision_render_scale).to_pil()
        buffer = io.BytesIO()
        if image_format == "JPEG":
            pil_image.save(buffer, format="JPEG", quality=settings.llm_vision_jpeg_quality)
            mime_type = "jpeg"
        else:
            pil_image.save(buffer, format="PNG")
            mime_type = "png"
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        image_urls.append(f"data:image/{mime_type};base64,{encoded}")
        page.close()
        pil_image.close()
    return image_urls


# Checks whether a redacted text layer still contains structured contact details.
def _contains_structured_pii(text: str) -> bool:
    if EMAIL_PATTERN.search(text):
        return True
    return any(is_phone_candidate(match.group(0)) for match in PHONE_PATTERN.finditer(text))


# Renders only pages whose detected contact details have been permanently redacted.
def render_redacted_pdf_pages_as_data_urls(
    file_path: str,
    max_pages: int,
    pii_values: list[str],
) -> list[str]:
    document = pymupdf.open(file_path)
    try:
        if document.page_count == 0:
            raise ValueError("PDF has no pages.")

        page_count = min(max_pages, document.page_count)
        image_urls: list[str] = []
        image_format = settings.llm_vision_image_format.strip().upper()
        if image_format not in {"PNG", "JPEG"}:
            image_format = "PNG"

        for page_index in range(page_count):
            page = document[page_index]
            original_page_text = page.get_text("text")
            values_on_page = [
                value
                for value in pii_values
                if value and value.casefold() in original_page_text.casefold()
            ]
            for value in values_on_page:
                rectangles = page.search_for(value)
                if not rectangles:
                    raise ValueError("Unable to locate detected PII for PDF redaction.")
                for rectangle in rectangles:
                    page.add_redact_annot(rectangle, fill=(1, 1, 1), cross_out=False)

            if values_on_page:
                page.apply_redactions()

            redacted_text = page.get_text("text")
            if _contains_structured_pii(redacted_text):
                raise ValueError("PII remains in the PDF text layer after redaction.")
            if any(value.casefold() in redacted_text.casefold() for value in values_on_page):
                raise ValueError("A detected identity value remains after PDF redaction.")

            matrix = pymupdf.Matrix(settings.llm_vision_render_scale, settings.llm_vision_render_scale)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            if image_format == "JPEG":
                image_bytes = pixmap.tobytes("jpeg", jpg_quality=settings.llm_vision_jpeg_quality)
                mime_type = "jpeg"
            else:
                image_bytes = pixmap.tobytes("png")
                mime_type = "png"
            encoded = base64.b64encode(image_bytes).decode("ascii")
            image_urls.append(f"data:image/{mime_type};base64,{encoded}")
        return image_urls
    finally:
        document.close()
