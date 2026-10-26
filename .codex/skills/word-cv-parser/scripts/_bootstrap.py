# Shared bootstrap for the word-cv-parser CLI: word-convert's src on path.
from __future__ import annotations

import sys
from pathlib import Path


# Locates .codex/skills/word-convert/src so its converter can be imported.
def _prepend_word_convert_src(start: Path) -> None:
    for parent in (start, *start.parents):
        converter_src = parent / ".codex" / "skills" / "word-convert" / "src"
        if converter_src.is_dir():
            if str(converter_src) not in sys.path:
                sys.path.insert(0, str(converter_src))
            return
    raise RuntimeError("Could not locate .codex/skills/word-convert/src")


_prepend_word_convert_src(Path(__file__).resolve().parent)
