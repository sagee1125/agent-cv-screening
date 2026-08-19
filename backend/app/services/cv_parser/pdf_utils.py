# Extracts, redacts, and renders PDF content for local CV processing.
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import pdfplumber
import pymupdf
import pypdfium2 as pdfium
from pypdf import PdfReader
from PIL import Image, ImageDraw

from app.config import settings
from app.services.cv_parser.ocr import OCRLine, recognize_image_bytes
from app.services.cv_parser.pii import EMAIL_PATTERN, PHONE_PATTERN, is_phone_candidate

logger = logging.getLogger(__name__)


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


# Masks locally detected faces and QR codes before any rendered page leaves the server.
def _redact_visual_identifiers(image_bytes: bytes) -> bytes:
    import cv2
    import numpy as np

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unable to decode rendered PDF page for visual redaction.")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade_path = f"{cv2.data.haarcascades}haarcascade_frontalface_default.xml"
    face_detector = cv2.CascadeClassifier(cascade_path)
    if not face_detector.empty():
        for x, y, width, height in face_detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(40, 40),
        ):
            padding = max(4, round(max(width, height) * 0.08))
            top_left = (max(0, x - padding), max(0, y - padding))
            bottom_right = (
                min(image.shape[1], x + width + padding),
                min(image.shape[0], y + height + padding),
            )
            cv2.rectangle(image, top_left, bottom_right, (255, 255, 255), thickness=-1)

    qr_detector = cv2.QRCodeDetector()
    try:
        detected, _, points, _ = qr_detector.detectAndDecodeMulti(image)
        if detected and points is not None:
            for polygon in points:
                cv2.fillPoly(image, [polygon.astype(np.int32)], (255, 255, 255))
    except cv2.error:
        logger.warning("QR-code detection failed for one rendered CV page.", exc_info=True)

    encoded, buffer = cv2.imencode(".png", image)
    if not encoded:
        raise ValueError("Unable to encode visually redacted PDF page.")
    return buffer.tobytes()


# Converts a redacted PNG page to the configured external image format.
def _encode_page_image(image_bytes: bytes, image_format: str) -> bytes:
    if image_format != "JPEG":
        return image_bytes
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=settings.llm_vision_jpeg_quality)
    image.close()
    return output.getvalue()


# Covers OCR line polygons containing detected PII and verifies the resulting image locally.
def _redact_ocr_image(
    image_bytes: bytes,
    *,
    page_index: int,
    ocr_lines: list[OCRLine],
    pii_values: list[str],
    image_format: str,
) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    scale_ratio = settings.llm_vision_render_scale / settings.cv_ocr_render_scale
    page_values = [value for value in pii_values if value]
    for line in ocr_lines:
        matched_values = [
            value
            for value in page_values
            if value.casefold() in line.text.casefold()
        ]
        if not matched_values:
            continue
        polygon = [
            (round(x * scale_ratio), round(y * scale_ratio))
            for x, y in line.polygon
        ]
        draw.polygon(polygon, fill="white")

    output = io.BytesIO()
    if image_format == "JPEG":
        image.save(output, format="JPEG", quality=settings.llm_vision_jpeg_quality)
    else:
        image.save(output, format="PNG")
    image.close()
    safe_image_bytes = output.getvalue()

    remaining_lines = recognize_image_bytes(safe_image_bytes, page_index)
    remaining_text = "\n".join(line.text for line in remaining_lines)
    if _contains_structured_pii(remaining_text):
        raise ValueError("PII remains after scanned-page image redaction.")
    if any(value.casefold() in remaining_text.casefold() for value in page_values):
        raise ValueError("A detected identity value remains in a scanned page.")
    return safe_image_bytes


# Renders only pages whose detected contact details have been permanently redacted.
def render_redacted_pdf_pages_as_data_urls(
    file_path: str,
    max_pages: int,
    pii_values: list[str],
    ocr_lines: tuple[OCRLine, ...] = (),
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
            page_ocr_lines = [line for line in ocr_lines if line.page_index == page_index]
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
            image_bytes = pixmap.tobytes("png")
            image_bytes = _redact_visual_identifiers(image_bytes)
            if page_ocr_lines:
                image_bytes = _redact_ocr_image(
                    image_bytes,
                    page_index=page_index,
                    ocr_lines=page_ocr_lines,
                    pii_values=pii_values,
                    image_format=image_format,
                )
            else:
                image_bytes = _encode_page_image(image_bytes, image_format)
            mime_type = "jpeg" if image_format == "JPEG" else "png"
            encoded = base64.b64encode(image_bytes).decode("ascii")
            image_urls.append(f"data:image/{mime_type};base64,{encoded}")
        return image_urls
    finally:
        document.close()
