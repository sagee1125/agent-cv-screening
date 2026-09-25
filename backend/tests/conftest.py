# Pytest path and env setup so tests import backend app and skill packages.
import os
import sys
from pathlib import Path

import pytest


os.environ.setdefault("ZAI_API_KEY", "test-key")
os.environ.setdefault("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
os.environ.setdefault("LLM_MODEL", "glm-4-flash")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CV_LOCAL_NER_ENABLED", "false")
# Tests exercise the public-demo profile by default (also the product default); a test that
# needs the internal system passes --site prod or monkeypatches JES_SITE_MODE=1.
# Forced, not setdefault: an exported JES_SITE_MODE=1 in a developer's shell would otherwise
# put the whole suite in prod mode, where a stray fetch could reach the real internal host.
os.environ["JES_SITE_MODE"] = "0"

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

# The repo's real job-state directory; a screening run writes a refno's snapshot here by default.
REPO_STATE_DIR = REPO_ROOT / "data" / "jas_state"


# Fingerprint the repo job-state dir as {relative path: (mtime_ns, size)} so a change is cheap
# to spot. Recursive on purpose: state now lives under a per-site subdirectory
# (data/jas_state/<site>/<refno>.json), so a top-level glob would miss it and silently stop
# guarding anything.
def _state_fingerprint() -> dict[str, tuple[int, int]]:
    if not REPO_STATE_DIR.is_dir():
        return {}
    return {
        str(path.relative_to(REPO_STATE_DIR)): (path.stat().st_mtime_ns, path.stat().st_size)
        for path in REPO_STATE_DIR.rglob("*.json")
    }


@pytest.fixture(autouse=True)
def repo_job_state_untouched():
    """Fail the test that rewrites the repo's real job-state dir (a run must pass its own --state-dir)."""
    before = _state_fingerprint()
    yield
    after = _state_fingerprint()
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    assert not changed, (
        f"the test wrote the repo job-state dir {REPO_STATE_DIR} ({', '.join(changed)}); "
        "pass a tmp_path-based --state-dir / state_dir instead"
    )
