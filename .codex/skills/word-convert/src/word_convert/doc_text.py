"""Extracts the text layer from a legacy Word .doc file, in pure Python.

A .doc is an OLE2 compound file whose WordDocument stream holds the text as
pieces described by a piece table (CLX) in the 1Table/0Table stream. Reading
those pieces covers both simple and fast-saved documents and needs no
external software - which is the point: the screening engine must handle a
.doc submission on a machine that has neither Word nor LibreOffice.

Layout (fonts, columns, text boxes) is deliberately not reconstructed; the
screening pipeline only needs the text, and the resulting text-layer PDF
goes through the same masking as every other CV.
"""
from __future__ import annotations

import struct

_MIN_TEXT_CHARS = 40
# Piece-table constants (MS-DOC / [MS-DOC] fcClx in the FIB, Word 97-2003).
_FIB_CLX_OFFSET = 0x01A2
_FCOMPRESSED = 0x40000000


def extract_text_from_doc(path) -> str:
    """Returns the cleaned text of a legacy .doc file, or raises ValueError."""
    import olefile

    try:
        ole = olefile.OleFileIO(str(path))
    except Exception as exc:
        raise ValueError(f"not a readable Word document: {exc}") from exc
    try:
        word_stream = _read_stream(ole, "WordDocument")
        table_stream = _read_stream(ole, "1Table") or _read_stream(ole, "0Table")
    finally:
        ole.close()
    if not word_stream or not table_stream:
        raise ValueError("Word streams missing from the document")

    fc_clx, lcb_clx = struct.unpack_from("<II", word_stream, _FIB_CLX_OFFSET)
    if lcb_clx <= 0 or fc_clx + lcb_clx > len(table_stream):
        raise ValueError("document has no piece table (unsupported Word version)")

    clx = table_stream[fc_clx : fc_clx + lcb_clx]
    pieces = _parse_clx_pieces(clx)
    if not pieces:
        raise ValueError("piece table is empty")

    text_parts: list[str] = []
    for cp_start, cp_end, fc_raw in pieces:
        length = cp_end - cp_start
        if length <= 0:
            continue
        if fc_raw & _FCOMPRESSED:
            offset = (fc_raw & 0x3FFFFFFF) // 2
            raw = word_stream[offset : offset + length]
            text_parts.append(raw.decode("cp1252", errors="replace"))
        else:
            offset = fc_raw & 0x3FFFFFFF
            raw = word_stream[offset : offset + 2 * length]
            text_parts.append(raw.decode("utf-16-le", errors="replace"))

    text = _clean_word_text("".join(text_parts))
    if len(text) < _MIN_TEXT_CHARS:
        raise ValueError("extracted text is too short to be a usable CV")
    return text


def _read_stream(ole, name: str) -> bytes:
    try:
        return ole.openstream(name).read()
    except Exception:
        return b""


def _parse_clx_pieces(clx: bytes) -> list[tuple[int, int, int]]:
    """Walks the CLX: Prc blocks are skipped, the Pcdt carries the piece table.

    Returns (cp_start, cp_end, fc_raw) triples.
    """
    position = 0
    plcpcd = b""
    while position < len(clx):
        tag = clx[position]
        if tag == 1:  # Prc: a property modification, skip its payload
            if position + 3 > len(clx):
                break
            (cb,) = struct.unpack_from("<H", clx, position + 1)
            position += 3 + cb
        elif tag == 2:  # Pcdt: the piece descriptor table
            if position + 5 > len(clx):
                break
            (lcb,) = struct.unpack_from("<I", clx, position + 1)
            plcpcd = clx[position + 5 : position + 5 + lcb]
            break
        else:
            break
    if not plcpcd:
        return []

    count = (len(plcpcd) - 4) // 12
    if count <= 0:
        return []
    cps = struct.unpack_from(f"<{count + 1}I", plcpcd, 0)
    pieces: list[tuple[int, int, int]] = []
    for index in range(count):
        pcd = plcpcd[4 * (count + 1) + 8 * index : 4 * (count + 1) + 8 * index + 8]
        if len(pcd) < 8:
            break
        (fc_raw,) = struct.unpack_from("<I", pcd, 2)
        pieces.append((cps[index], cps[index + 1], fc_raw))
    return pieces


def _clean_word_text(text: str) -> str:
    # Word marks cell/row ends with \x07 and field boundaries with \x13-\x15;
    # neither survives a line-based text PDF, so they become plain separators.
    replacements = {
        "\x07": "\n",
        "\x0d": "\n",
        "\x0b": "\n",
        "\x1e": "-",
        "\x1f": "-",
        "\xa0": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    cleaned = []
    for char in text:
        if char in "\x13\x14\x15" or ord(char) < 0x20 and char != "\n":
            continue
        cleaned.append(char)
    lines = [" ".join(line.split()) for line in "".join(cleaned).splitlines()]
    return "\n".join(line for line in lines if line)
