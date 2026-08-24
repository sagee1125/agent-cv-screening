# Shared bootstrap for the CV screening agent CLI scripts.
from __future__ import annotations

import os
import sys
from pathlib import Path


# Walk up until backend/app is found and return that directory as the repo root.
def _find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "backend" / "app").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root (backend/app not found).")


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if (REPO_ROOT / ".env").exists():
    os.chdir(REPO_ROOT)
