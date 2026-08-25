# Shared bootstrap for the jd-parser CLI: skill packages on path, cwd at repo root.
from __future__ import annotations

import sys
from pathlib import Path


# Locates .codex/skills/_shared/src so screening_core can be imported.
def _prepend_shared_src(start: Path) -> None:
    for parent in (start, *start.parents):
        shared_src = parent / ".codex" / "skills" / "_shared" / "src"
        if shared_src.is_dir():
            if str(shared_src) not in sys.path:
                sys.path.insert(0, str(shared_src))
            return
    raise RuntimeError("Could not locate .codex/skills/_shared/src")


_prepend_shared_src(Path(__file__).resolve().parent)

from screening_core.bootstrap import chdir_repo_root, ensure_skill_imports

REPO_ROOT = ensure_skill_imports()
chdir_repo_root(REPO_ROOT)
