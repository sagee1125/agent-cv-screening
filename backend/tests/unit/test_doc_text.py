# Pure-python .doc text extraction: the CLX piece-table parser must handle
# UTF-16 and compressed (8-bit) pieces, Prc blocks before the Pcdt, and the
# cleanup must map Word control characters to plain separators.
import struct

from word_convert.doc_text import _clean_word_text, _parse_clx_pieces, _read_stream


def _build_clx(pieces: list[tuple[int, int, int]]) -> bytes:
    """Builds a CLX blob: one Prc block, then the Pcdt piece table."""
    cps = struct.pack(f"<{len(pieces) + 1}I", *(p[0] for p in pieces + [(pieces[-1][1],)]))
    pcds = b"".join(
        b"\x00\x00" + struct.pack("<I", fc) + b"\x00\x00" for _, _, fc in pieces
    )
    plcpcd = cps + pcds
    prc = b"\x01" + struct.pack("<H", 4) + b"\x00" * 4
    pcdt = b"\x02" + struct.pack("<I", len(plcpcd)) + plcpcd
    return prc + pcdt


def test_parse_clx_pieces_utf16_and_compressed() -> None:
    pieces = [(0, 5, 0x00000010), (5, 9, 0x40000020)]  # utf16 piece + compressed piece
    clx = _build_clx(pieces)
    parsed = _parse_clx_pieces(clx)
    assert parsed == [(0, 5, 0x00000010), (5, 9, 0x40000020)]


def test_parse_clx_pieces_skips_prc_blocks() -> None:
    plcpcd = struct.pack("<2I", 0, 4) + b"\x00\x00" + struct.pack("<I", 0x10) + b"\x00\x00"
    clx = b"\x01" + struct.pack("<H", 2) + b"\x00\x00" + b"\x02" + struct.pack("<I", len(plcpcd)) + plcpcd
    assert _parse_clx_pieces(clx) == [(0, 4, 0x10)]


def test_parse_clx_pieces_empty_or_malformed() -> None:
    assert _parse_clx_pieces(b"") == []
    assert _parse_clx_pieces(b"\x03\xff") == []
    # A Pcdt header that claims more bytes than the buffer has: no crash, no pieces.
    assert _parse_clx_pieces(b"\x02" + struct.pack("<I", 999)) == []


def test_clean_word_text_maps_control_characters() -> None:
    raw = "Economics\x07Business\r\nCampaign\x131\x142\x15 done\xa0"
    cleaned = _clean_word_text(raw)
    assert "Economics" in cleaned and "Business" in cleaned
    assert "\x07" not in cleaned and "\x13" not in cleaned and "\xa0" not in cleaned
