# Shared bootstrap for the cv-portrait CLI: this skill's src plus the skill
# packages it reuses (cv_parser extraction/masking, word_convert conversion,
# screening_core settings/client) on sys.path.
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _prepend(src: Path) -> None:
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


for relative in ("../src", "../../cv-parser/src", "../../word-convert/src", "../../_shared/src"):
    _prepend((SCRIPT_DIR / relative).resolve())
