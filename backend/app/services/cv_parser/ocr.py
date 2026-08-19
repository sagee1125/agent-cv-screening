# Performs fully local OCR and retains page coordinates for scanned-CV redaction.
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from app.config import settings

logger = logging.getLogger(__name__)
_OCR_ENGINE: Any | None = None
_OCR_ENGINE_LOCK = threading.Lock()


@dataclass(frozen=True)
class OCRLine:
    """Stores one recognized line and its polygon in rendered-image coordinates."""

    page_index: int
    text: str
    confidence: float
    polygon: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class LocalCVDocument:
    """Contains locally extracted text and OCR coordinates for every scanned page."""

    raw_text: str
    page_texts: tuple[str, ...]
    ocr_lines: tuple[OCRLine, ...]
    ocr_page_indexes: frozenset[int]


# Lazily initializes one process-local RapidOCR engine.
def _get_ocr_engine() -> Any:
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    with _OCR_ENGINE_LOCK:
        if _OCR_ENGINE is None:
            from rapidocr import RapidOCR

            _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


# Recognizes text and line polygons from one locally rendered page image.
def recognize_image_bytes(image_bytes: bytes, page_index: int) -> list[OCRLine]:
    result = _get_ocr_engine()(image_bytes)
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []

    lines: list[OCRLine] = []
    for box, text, score in zip(boxes, texts, scores):
        cleaned_text = " ".join(str(text).split()).strip()
        confidence = float(score)
        if not cleaned_text or confidence < settings.cv_ocr_confidence_threshold:
            continue
        polygon = tuple((float(point[0]), float(point[1])) for point in box)
        lines.append(
            OCRLine(
                page_index=page_index,
                text=cleaned_text,
                confidence=confidence,
                polygon=polygon,
            )
        )
    return lines


# Extracts embedded text and runs local OCR only on pages without a usable text layer.
def extract_local_cv_document(path: Path) -> LocalCVDocument:
    document = pymupdf.open(path)
    try:
        if document.page_count == 0:
            raise ValueError("PDF has no pages.")

        page_texts: list[str] = []
        all_ocr_lines: list[OCRLine] = []
        ocr_page_indexes: set[int] = set()
        for page_index, page in enumerate(document):
            embedded_text = page.get_text("text").strip()
            needs_ocr = len(embedded_text) < settings.cv_ocr_min_page_chars
            if needs_ocr and settings.cv_ocr_enabled and page_index < settings.cv_ocr_max_pages:
                matrix = pymupdf.Matrix(settings.cv_ocr_render_scale, settings.cv_ocr_render_scale)
                image_bytes = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
                ocr_lines = recognize_image_bytes(image_bytes, page_index)
                if ocr_lines:
                    embedded_text = "\n".join(line.text for line in ocr_lines)
                    all_ocr_lines.extend(ocr_lines)
                    ocr_page_indexes.add(page_index)
            page_texts.append(embedded_text)

        raw_text = "\n\n".join(text for text in page_texts if text).strip()
        if not raw_text:
            if settings.cv_ocr_enabled:
                raise ValueError("Local OCR could not extract text from the PDF.")
            raise ValueError("PDF has no extractable text and local OCR is disabled.")
        logger.info(
            "Local CV extraction complete pages=%s ocr_pages=%s",
            document.page_count,
            sorted(ocr_page_indexes),
        )
        return LocalCVDocument(
            raw_text=raw_text,
            page_texts=tuple(page_texts),
            ocr_lines=tuple(all_ocr_lines),
            ocr_page_indexes=frozenset(ocr_page_indexes),
        )
    finally:
        document.close()
