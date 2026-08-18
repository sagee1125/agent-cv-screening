"""Shared bootstrap for skill CLI scripts.

- Adds the backend directory to sys.path so `app.*` imports work from any cwd.
- Changes the working directory to the repository root so `.env`, `data/...`,
  and other repo-relative paths resolve consistently.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    # Walk up until we find the directory containing backend/app.
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
