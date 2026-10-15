# Reads each CV page locally (layout and OCR). Page images never leave this machine.
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from screening_core.config import settings

logger = logging.getLogger(__name__)
_OCR_ENGINE: Any | None = None
_OCR_ENGINE_LOCK = threading.Lock()
_YEAR_IN_TEXT = re.compile(r"\d{4}")


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


@dataclass(frozen=True)
class _LayoutItem:
    """One text block or table, with its box on the page."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str


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


# True when two boxes sit on the same visual row.
def _same_row(left: _LayoutItem, right: _LayoutItem) -> bool:
    overlap = min(left.y1, right.y1) - max(left.y0, right.y0)
    shorter = min(left.y1 - left.y0, right.y1 - right.y0) or 1.0
    return overlap / shorter >= 0.5


# True when the text is a short date, not a column of prose.
def _is_date_token(text: str) -> bool:
    compact = " ".join(text.split())
    return len(compact) <= 32 and _YEAR_IN_TEXT.search(compact) is not None


# Orders items that share a row from left to right, then moves down the page.
def _band_sort(items: list[_LayoutItem]) -> list[_LayoutItem]:
    remaining = sorted(items, key=lambda item: (item.y0, item.x0))
    ordered: list[_LayoutItem] = []
    while remaining:
        head = remaining.pop(0)
        band = [head]
        rest: list[_LayoutItem] = []
        for item in remaining:
            if _same_row(head, item):
                band.append(item)
            else:
                rest.append(item)
        ordered.extend(sorted(band, key=lambda item: item.x0))
        remaining = rest
    return ordered


# Returns left-column then right-column order when the page is clearly two columns.
def _column_major(items: list[_LayoutItem], page_width: float) -> list[_LayoutItem] | None:
    if page_width <= 0 or len(items) < 4:
        return None
    full_ids = {
        id(item) for item in items if (item.x1 - item.x0) >= page_width * 0.65
    }
    full_width = [item for item in items if id(item) in full_ids]
    narrow = [item for item in items if id(item) not in full_ids]
    midpoint = page_width * 0.5
    left = [item for item in narrow if (item.x0 + item.x1) / 2 < midpoint]
    left_ids = {id(item) for item in left}
    right = [item for item in narrow if id(item) not in left_ids]
    if len(left) < 2 or len(right) < 2:
        return None
    gutter = min(item.x0 for item in right) - max(item.x1 for item in left)
    if gutter <= page_width * 0.03:
        return None
    if sum(len(item.text) for item in left) < 40 or sum(len(item.text) for item in right) < 40:
        return None
    paired_dates = sum(
        1
        for item in right
        if _is_date_token(item.text) and any(_same_row(item, other) for other in left)
    )
    if paired_dates / len(right) >= 0.5:
        return None
    widths = sorted(item.x1 - item.x0 for item in right)
    if widths[len(widths) // 2] < page_width * 0.2:
        return None
    columns = sorted(left, key=lambda item: (item.y0, item.x0)) + sorted(
        right, key=lambda item: (item.y0, item.x0)
    )
    ordered: list[_LayoutItem] = []
    pending = columns
    for banner in sorted(full_width, key=lambda item: (item.y0, item.x0)):
        above = [item for item in pending if item.y0 < banner.y0]
        pending = [item for item in pending if item.y0 >= banner.y0]
        ordered.extend(above)
        ordered.append(banner)
    ordered.extend(pending)
    return ordered


# Chooses column order for a real two-column page, otherwise row order.
def _order_layout_items(items: list[_LayoutItem], page_width: float) -> list[_LayoutItem]:
    columns = _column_major(items, page_width)
    if columns is not None:
        return columns
    return _band_sort(items)


# Renders table rows as a markdown block so the text model keeps the grid.
def _rows_to_markdown(rows: list[Any]) -> str:
    cleaned: list[list[str]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue
        cells = [" ".join(str(cell or "").split()) for cell in row]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)

    # Formats one table row as a markdown line.
    def _format(row: list[str]) -> str:
        padded = row + [""] * (width - len(row))
        return "| " + " | ".join(padded) + " |"

    lines = [
        _format(cleaned[0]),
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend(_format(row) for row in cleaned[1:])
    return "\n".join(lines)


# True when a text block's center sits inside a detected table.
def _center_inside(item: _LayoutItem, rect: Any) -> bool:
    center_x = (item.x0 + item.x1) / 2
    center_y = (item.y0 + item.y1) / 2
    return rect.x0 <= center_x <= rect.x1 and rect.y0 <= center_y <= rect.y1


# Reads one page in visual order, keeping tables as rows. The page image stays local.
def page_layout_text(page: pymupdf.Page) -> str:
    table_items: list[_LayoutItem] = []
    table_rects: list[Any] = []
    try:
        found = page.find_tables()
        tables = getattr(found, "tables", None) or []
    except Exception:
        logger.debug("Local table detection failed", exc_info=True)
        tables = []
    for table in tables:
        bbox = getattr(table, "bbox", None)
        try:
            rows = table.extract() or []
        except Exception:
            logger.debug("Local table extraction failed", exc_info=True)
            continue
        markdown = _rows_to_markdown(rows)
        if not markdown or bbox is None or len(bbox) < 4:
            continue
        x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        table_items.append(_LayoutItem(x0, y0, x1, y1, markdown))
        table_rects.append(pymupdf.Rect(x0, y0, x1, y1))

    text_items: list[_LayoutItem] = []
    for block in page.get_text("blocks") or []:
        if len(block) < 5:
            continue
        block_type = block[6] if len(block) > 6 else 0
        if block_type != 0:
            continue
        cleaned = str(block[4]).strip()
        if not cleaned:
            continue
        item = _LayoutItem(float(block[0]), float(block[1]), float(block[2]), float(block[3]), cleaned)
        if any(_center_inside(item, rect) for rect in table_rects):
            continue
        text_items.append(item)

    ordered = _order_layout_items(text_items + table_items, float(page.rect.width))
    return "\n\n".join(item.text for item in ordered).strip()


# Rebuilds OCR lines in the same reading order used for embedded text.
def _ocr_lines_text(lines: list[OCRLine], image_width: float) -> str:
    items: list[_LayoutItem] = []
    for line in lines:
        if not line.polygon:
            continue
        xs = [point[0] for point in line.polygon]
        ys = [point[1] for point in line.polygon]
        items.append(_LayoutItem(min(xs), min(ys), max(xs), max(ys), line.text))
    ordered = _order_layout_items(items, image_width)
    return "\n".join(item.text for item in ordered).strip()


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
            embedded_text = page_layout_text(page)
            if not embedded_text:
                embedded_text = page.get_text("text", sort=True).strip()
            needs_ocr = len(embedded_text) < settings.cv_ocr_min_page_chars
            if needs_ocr and settings.cv_ocr_enabled and page_index < settings.cv_ocr_max_pages:
                matrix = pymupdf.Matrix(settings.cv_ocr_render_scale, settings.cv_ocr_render_scale)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                ocr_lines = recognize_image_bytes(pixmap.tobytes("png"), page_index)
                if ocr_lines:
                    embedded_text = _ocr_lines_text(ocr_lines, float(pixmap.width)) or embedded_text
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
