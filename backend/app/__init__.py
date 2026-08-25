# Expose skill packages on sys.path so FastAPI imports domain logic from .codex/skills.
from pathlib import Path
import os
import sys


# Walks parents (and optional CODEX_SKILLS_DIR) until .codex/skills/_shared exists.
def _find_skills_root() -> Path:
    extra = os.environ.get("CODEX_SKILLS_DIR")
    search = []
    if extra:
        search.append(Path(extra))
    search.extend(Path(__file__).resolve().parents)
    for parent in search:
        if (parent / ".codex" / "skills" / "_shared").is_dir():
            return parent
    raise RuntimeError(
        "Could not locate .codex/skills/_shared. "
        "In Docker, mount ./.codex to /app/.codex (see docker-compose.yml)."
    )


_REPO_ROOT = _find_skills_root()
_SHARED_SRC = _REPO_ROOT / ".codex" / "skills" / "_shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from screening_core.bootstrap import ensure_skill_imports

ensure_skill_imports(_REPO_ROOT)
