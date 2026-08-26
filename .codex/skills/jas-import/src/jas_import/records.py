# Parse the internal PolyU Job Application System (JAS) HTML pages.
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

JAS_SOURCE = "jas"
DEFAULT_BASE_URL = "https://jobs.polyu.edu.hk"


@dataclass(frozen=True)
class JASJobRow:
    """One row from the JAS records list table."""

    refno: str
    job_group: str
    unit: str
    post_title: str
    posting_date: str
    closing_date: str
    off_shelf_date: str
    list_type: str
    application_count: str
    records_url: str


@dataclass(frozen=True)
class JASCandidate:
    """One candidate row reduced to the non-PII fields the pipeline needs."""

    appno: str
    status: str | None
    cv_url: str | None
    supp_url: str | None
    record_detail_url: str | None


@dataclass
class JASJobDetail:
    """Job advertisement information plus candidate references from a records page."""

    refno: str
    job_group: str
    unit: str
    post_title: str
    appointment_period: str | None
    project_title: str | None
    posting_date: str
    list_type: str
    fields: list[tuple[str, str]]
    candidates: list[JASCandidate]


class _Cell:
    """Internal mutable buffer for one parsed table cell."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.text_parts: list[str] = []
        self.links: list[dict[str, Any]] = []


class _TableParser(HTMLParser):
    """Collect tables, rows, cells, and link hrefs without external dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._table: dict[str, Any] | None = None
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._link: dict[str, Any] | None = None
        self._in_link = False

    # Start a new table, row, cell, or anchor and remember its attributes.
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value for key, value in attrs}
        if tag == "table":
            self._table = {"attrs": attrs_dict, "rows": []}
            self.tables.append(self._table)
        elif tag == "tr":
            if self._table is None:
                self._table = {"attrs": {}, "rows": []}
                self.tables.append(self._table)
            self._row = []
            self._table["rows"].append(self._row)
        elif tag in ("td", "th"):
            if self._row is None:
                if self._table is None:
                    self._table = {"attrs": {}, "rows": []}
                    self.tables.append(self._table)
                self._row = []
                self._table["rows"].append(self._row)
            self._cell = _Cell(tag)
            self._row.append(self._cell)
        elif tag == "a":
            href = attrs_dict.get("href")
            if href is not None:
                self._in_link = True
                self._link = {"href": unescape(href), "text_parts": []}

    # Handle self-closing tags such as <br/> as line breaks.
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._append_newline()

    # Route text data into the current link or the current cell.
    def handle_data(self, data: str) -> None:
        if self._cell is None:
            return
        if self._in_link and self._link is not None:
            self._link["text_parts"].append(data)
        else:
            self._cell.text_parts.append(data)

    # Finalize anchors and close table structural tags.
    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            if self._in_link and self._link is not None and self._cell is not None:
                self._cell.links.append(
                    {"href": self._link["href"], "text_parts": list(self._link["text_parts"])}
                )
            self._in_link = False
            self._link = None
            return
        if tag in ("p", "div", "li", "tr"):
            self._append_newline()
        if tag in ("td", "th"):
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None

    # Insert a line break into the current text or link text buffer.
    def _append_newline(self) -> None:
        if self._cell is None:
            return
        if self._in_link and self._link is not None:
            self._link["text_parts"].append("\n")
        else:
            self._cell.text_parts.append("\n")


# Collapse whitespace into single spaces and strip surrounding blanks.
def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


# Convert a parsed cell buffer into a JSON-friendly dict.
def _normalize_cell(cell: _Cell) -> dict[str, Any]:
    links = []
    link_texts = []
    for link in cell.links:
        text = _clean(" ".join(link["text_parts"]))
        links.append({"href": link["href"], "text": text})
        if text:
            link_texts.append(text)
    return {
        "tag": cell.tag,
        "text": _clean(" ".join(cell.text_parts)),
        "link_text": _clean(" ".join(link_texts)),
        "links": links,
    }


# Parse HTML into a list of tables, each carrying attributes and normalized rows.
def parse_tables(html: str) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(html)
    return [
        {
            "attrs": table["attrs"],
            "rows": [[_normalize_cell(cell) for cell in row] for row in table["rows"]],
        }
        for table in parser.tables
    ]


# Return data rows whose cells are all <td> (skips <th> header/search rows).
def _data_rows(table: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [row for row in table["rows"] if row and all(cell["tag"] == "td" for cell in row)]


# Locate a table whose class attribute contains the given token.
def _find_table(tables: list[dict[str, Any]], class_token: str) -> dict[str, Any] | None:
    for table in tables:
        classes = table["attrs"].get("class", "") or ""
        if class_token in classes:
            return table
    return None


# Locate a table that contains a key/value row with the given header label.
def _find_table_with_label(tables: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    for table in tables:
        for row in _data_rows(table):
            if len(row) >= 2 and _text(row[0]) == label:
                return table
    return None


# Extract the plain text of a cell.
def _text(cell: dict[str, Any]) -> str:
    return cell["text"]


# Extract a query parameter value from an absolute or relative URL.
def _query_value(url: str, key: str) -> str | None:
    try:
        values = parse_qs(urlparse(url).query).get(key, [])
    except ValueError:
        return None
    return values[0].strip() if values else None


# Resolve the first link href in a cell against the base URL.
def _first_link_url(cell: dict[str, Any], origin: str) -> str | None:
    for link in cell["links"]:
        href = link["href"]
        if href:
            return urljoin(origin.rstrip("/") + "/", href)
    return None


# Extract the refno and records URL from the first list-table cell.
def _refno_from_cell(cell: dict[str, Any], origin: str) -> tuple[str, str | None]:
    for link in cell["links"]:
        refno = _query_value(link["href"], "refno")
        if refno:
            return refno, urljoin(origin.rstrip("/") + "/", link["href"])
    text = _text(cell)
    match = re.search(r"(\d{6,})", text)
    return (match.group(1) if match else text), None


# Build key/value rows from a JAS advertisement information table.
def _key_value_rows(table: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for row in _data_rows(table):
        if len(row) >= 2:
            label = _text(row[0])
            if label:
                fields.append((label, _text(row[1])))
    return fields


# Derive the current HR status as the plain-text label (clickable labels are links).
def _current_status(cell: dict[str, Any]) -> str | None:
    plain = _text(cell)
    for token in ("TBC", "P", "S", "N"):
        if re.search(rf"\b{re.escape(token)}\b", plain):
            return token
    return None


# Resolve the application no. from a record-detail or CV URL.
def _appno_from_url(url: str | None) -> str:
    if not url:
        return ""
    return _query_value(url, "id") or ""


# Maps candidate columns by their header labels, with legacy positions as fallback.
def _candidate_column_indexes(table: dict[str, Any] | None) -> dict[str, int]:
    indexes = {"appno": 1, "record_detail": 2, "status": 3, "cv": 13, "supp": 14}
    if not table:
        return indexes
    for row in table["rows"]:
        if row and all(cell["tag"] == "th" for cell in row):
            for index, cell in enumerate(row):
                label = _text(cell).casefold()
                key = None
                if label == "application no.":
                    key = "appno"
                elif label.startswith("online job application form summary"):
                    key = "record_detail"
                elif label == "status":
                    key = "status"
                elif label == "curriculum vitae":
                    key = "cv"
                elif label in ("supplementary", "other supplementary information"):
                    key = "supp"
                if key:
                    indexes[key] = index
            break
    return indexes


# Convert one candidate table row into a minimal non-PII candidate reference.
def _candidate_from_row(row: list[dict[str, Any]], origin: str, indexes: dict[str, int]) -> JASCandidate:
    # Returns a cell at a mapped index when the row is wide enough.
    def cell(key: str) -> dict[str, Any] | None:
        index = indexes[key]
        return row[index] if index < len(row) else None

    appno_cell = cell("appno")
    detail_cell = cell("record_detail")
    status_cell = cell("status")
    cv_cell = cell("cv")
    supp_cell = cell("supp")
    appno = _text(appno_cell) if appno_cell else ""
    record_detail_url = _first_link_url(detail_cell, origin) if detail_cell else None
    status = _current_status(status_cell) if status_cell else None
    cv_url = _first_link_url(cv_cell, origin) if cv_cell else None
    supp_url = _first_link_url(supp_cell, origin) if supp_cell else None
    if not appno:
        appno = _appno_from_url(cv_url or record_detail_url)
    return JASCandidate(
        appno=appno,
        status=status,
        cv_url=cv_url,
        supp_url=supp_url,
        record_detail_url=record_detail_url,
    )


# Parse the JAS records list HTML into job rows.
def parse_list_html(html: str, *, base_url: str | None = None) -> list[JASJobRow]:
    origin = base_url or DEFAULT_BASE_URL
    tables = parse_tables(html)
    table = _find_table(tables, "job-table")
    items: list[JASJobRow] = []
    for row in _data_rows(table) if table else []:
        if len(row) < 9:
            continue
        refno, records_url = _refno_from_cell(row[0], origin)
        if not refno:
            continue
        items.append(
            JASJobRow(
                refno=refno,
                job_group=_text(row[1]),
                unit=_text(row[2]),
                post_title=_text(row[3]),
                posting_date=_text(row[4]),
                closing_date=_text(row[5]),
                off_shelf_date=_text(row[6]),
                list_type=_text(row[7]),
                application_count=_text(row[8]),
                records_url=records_url or "",
            )
        )
    return items


# Parse the JAS records job-detail HTML into JD text and candidate references.
def parse_job_html(html: str, *, base_url: str | None = None) -> JASJobDetail:
    origin = base_url or DEFAULT_BASE_URL
    tables = parse_tables(html)
    candidate_table = _find_table(tables, "job-detail-table")
    jd_table = _find_table_with_label(tables, "Reference number")
    candidate_rows = _data_rows(candidate_table) if candidate_table else []
    jd_fields = _key_value_rows(jd_table) if jd_table else []

    # Return the first value for a case-insensitive JD field label.
    def value(label: str, default: str = "") -> str:
        for field_label, field_value in jd_fields:
            if field_label.casefold() == label.casefold():
                return field_value
        return default

    # Fall back to the refno found in candidate record-detail URLs.
    def refno_from_rows(rows: list[list[dict[str, Any]]]) -> str:
        for row in rows:
            for cell in row:
                for link in cell["links"]:
                    refno = _query_value(link["href"], "refno")
                    if refno:
                        return refno
        return ""

    column_indexes = _candidate_column_indexes(candidate_table)
    candidates = [
        candidate
        for row in candidate_rows
        if (candidate := _candidate_from_row(row, origin, column_indexes)).appno
    ]
    return JASJobDetail(
        refno=value("Reference number") or refno_from_rows(candidate_rows),
        job_group=value("Job group"),
        unit=value("Unit"),
        post_title=value("Post title"),
        appointment_period=value("Appointment Period") or None,
        project_title=value("Project Title") or None,
        posting_date=value("Posting date"),
        list_type=value("List in external/internal"),
        fields=jd_fields,
        candidates=candidates,
    )


# Build plain JD text from the JAS advertisement information rows.
def build_jd_text(detail: JASJobDetail) -> str:
    lines: list[str] = []
    for label, value in detail.fields:
        lines.append(f"{label}: {value}" if value else f"{label}:")
    return "\n".join(lines).strip()


__all__ = [
    "DEFAULT_BASE_URL",
    "JAS_SOURCE",
    "JASCandidate",
    "JASJobDetail",
    "JASJobRow",
    "build_jd_text",
    "parse_job_html",
    "parse_list_html",
    "parse_tables",
]