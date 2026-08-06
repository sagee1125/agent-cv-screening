import os
import sys
from pathlib import Path


os.environ.setdefault("ZAI_API_KEY", "test-key")
os.environ.setdefault("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
os.environ.setdefault("LLM_MODEL", "glm-4-flash")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("SECRET_KEY", "test-secret")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
