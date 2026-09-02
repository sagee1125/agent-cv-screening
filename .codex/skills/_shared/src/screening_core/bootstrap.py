# Puts skill package src dirs on sys.path so backend and CLIs import skill code.
from __future__ import annotations

import os
import sys
from pathlib import Path

# Third-party modules the screening chain cannot run without.
_REQUIRED_MODULES = ("httpx", "openpyxl", "reportlab")

# Set on the child process so a re-exec can never loop.
_REEXEC_GUARD_ENV = "SCREENING_VENV_REEXEC"

# Skill folders whose src/ contains an importable Python package.
_SKILL_SRC_DIRS = (
    ("_shared", "src"),
    ("cv-parser", "src"),
    ("jd-parser", "src"),
    ("scorer", "src"),
    ("report-gen", "src"),
    ("polyu-import", "src"),
    ("jas-import", "src"),
    ("host-envelope", "src"),
    ("webridge-collect", "src"),
)


# Finds the repository root by locating .codex/skills/_shared (not backend/).
def find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / ".codex" / "skills" / "_shared").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root (.codex/skills/_shared not found).")


# True when every third-party module the chain needs is importable here.
def _dependencies_available() -> bool:
    import importlib.util

    for name in _REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


# Re-runs the current CLI with the repo venv interpreter when dependencies are missing.
def ensure_venv_interpreter(root: Path) -> None:
    if _dependencies_available() or os.environ.get(_REEXEC_GUARD_ENV):
        return
    candidates = (root / "venv" / "Scripts" / "python.exe", root / "venv" / "bin" / "python")
    venv_python = next((path for path in candidates if path.is_file()), None)
    if venv_python is None:
        return
    try:
        if os.path.samefile(sys.executable, str(venv_python)):
            return
    except OSError:
        pass
    script = os.path.abspath(sys.argv[0]) if sys.argv else ""
    if not script or not os.path.isfile(script):
        return
    os.environ[_REEXEC_GUARD_ENV] = "1"
    os.execv(str(venv_python), [str(venv_python), script, *sys.argv[1:]])


# Adds shared and leaf-skill src directories to sys.path.
def ensure_skill_imports(start: Path | None = None) -> Path:
    root = start if start and (start / ".codex" / "skills" / "_shared").is_dir() else find_repo_root(start or Path(__file__).resolve())
    skills_dir = root / ".codex" / "skills"
    for parts in _SKILL_SRC_DIRS:
        src = skills_dir.joinpath(*parts)
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
    ensure_venv_interpreter(root)
    return root


# Changes cwd to the repo root so .env, data/, and relative skill paths resolve.
def chdir_repo_root(root: Path) -> None:
    os.chdir(root)