from __future__ import annotations

import base64
import io
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from pypdf import PdfReader

from app.config import settings


def extract_with_pdfplumber(path: Path) -> str:
    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


def extract_with_pypdf(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


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
