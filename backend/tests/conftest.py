# Pytest path and env setup so tests import backend app and skill packages.
import os
import sys
from pathlib import Path


os.environ.setdefault("ZAI_API_KEY", "test-key")
os.environ.setdefault("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
os.environ.setdefault("LLM_MODEL", "glm-4-flash")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CV_LOCAL_NER_ENABLED", "false")

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SHARED_SRC = REPO_ROOT / ".codex" / "skills" / "_shared" / "src"
if SHARED_SRC.is_dir() and str(SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(SHARED_SRC))

from screening_core.bootstrap import ensure_skill_imports

ensure_skill_imports(REPO_ROOT)
# Skill and taxonomy relative paths are repo-root based (same as CLI).
os.chdir(REPO_ROOT)
