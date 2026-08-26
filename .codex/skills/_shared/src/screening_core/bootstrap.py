# Puts skill package src dirs on sys.path so backend and CLIs import skill code.
from __future__ import annotations

import os
import sys
from pathlib import Path

# Skill folders whose src/ contains an importable Python package.
_SKILL_SRC_DIRS = (
    ("_shared", "src"),
    ("cv-parser", "src"),
    ("jd-parser", "src"),
    ("scorer", "src"),
    ("report-gen", "src"),
    ("polyu-import", "src"),
    ("jas-import", "src"),
)


# Finds the repository root by locating .codex/skills/_shared (not backend/).
def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / ".codex" / "skills" / "_shared").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root (.codex/skills/_shared not found).")


# Adds shared and leaf-skill src directories to sys.path.
def ensure_skill_imports(start: Path | None = None) -> Path:
    root = start if start and (start / ".codex" / "skills" / "_shared").is_dir() else find_repo_root(start or Path(__file__).resolve())
    skills_dir = root / ".codex" / "skills"
    for parts in _SKILL_SRC_DIRS:
        src = skills_dir.joinpath(*parts)
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
    return root


# Changes cwd to the repo root so .env, data/, and relative skill paths resolve.
def chdir_repo_root(root: Path) -> None:
    os.chdir(root)