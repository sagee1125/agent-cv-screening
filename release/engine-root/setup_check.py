# One-time environment self-check for the screening engine.
#
# Run by setup.bat, and safe to run again by hand at any time:
#   C:\agent-cv-screening\venv\Scripts\python.exe setup_check.py
#
# It only reads files and imports libraries. It changes nothing.
# Exit code 0 means the environment is usable.

from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent

# Third-party modules the screening chain imports, with the pip name to suggest.
REQUIRED_MODULES = (
    ("httpx", "httpx"),
    ("openpyxl", "openpyxl"),
    ("reportlab", "reportlab"),
    ("pymupdf", "pymupdf"),
    ("pdfplumber", "pdfplumber"),
    ("pypdf", "pypdf"),
    ("pypdfium2", "pypdfium2"),
    ("PIL", "pillow"),
    ("numpy", "numpy"),
    ("yaml", "PyYAML"),
    ("dotenv", "python-dotenv"),
    ("pydantic", "pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("tenacity", "tenacity"),
    ("zai", "zai-sdk"),
    ("cv2", "opencv-python"),
    ("rapidocr", "rapidocr"),
    ("truststore", "truststore"),
)

# Files and folders the engine needs in order to start at all.
REQUIRED_PATHS = (
    ".codex/skills/_shared",
    ".codex/skills/cv-parser",
    ".codex/skills/jd-parser",
    ".codex/skills/scorer",
    ".codex/skills/report-gen",
    ".codex/skills/jas-import",
    ".codex/skills/webridge-collect",
    ".codex/skills/host-envelope/scripts/run_workbuddy_tool.py",
    "data/taxonomy/skill_taxonomy.yaml",
    "demo_mode.json",
)

PLACEHOLDER_KEY = "PUT-YOUR-API-KEY-HERE"

passed = 0
failed = 0
warned = 0


# Prints one aligned result line and keeps the running totals.
def report(status: str, label: str, detail: str = "") -> None:
    global passed, failed, warned
    if status == "OK":
        passed += 1
    elif status == "FAIL":
        failed += 1
    else:
        warned += 1
    line = f"  {status:<4}  {label}"
    if detail:
        line = f"{line:<52}{detail}"
    print(line)


# Reads .env without importing anything, so it works even when libs are missing.
def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


# Checks the interpreter that is actually running this script.
def check_python() -> None:
    print("Python")
    version = sys.version_info
    label = f"Python {version.major}.{version.minor}.{version.micro} ({platform.architecture()[0]})"
    if version.major == 3 and version.minor >= 12:
        report("OK", label)
    else:
        report("FAIL", label, "need Python 3.12 - run setup.bat again")
    print()


# Checks every third-party module the chain imports.
def check_libraries() -> None:
    print("Screening libraries")
    for module_name, pip_name in REQUIRED_MODULES:
        try:
            found = importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            found = False
        if found:
            report("OK", module_name)
        else:
            report("FAIL", module_name, f"run: pip install {pip_name}")
    print()


# Checks the folders and files the engine reads at startup.
def check_engine_files() -> None:
    print("Engine files")
    for relative in REQUIRED_PATHS:
        target = REPO / relative
        if target.exists():
            report("OK", relative)
        else:
            report("FAIL", relative, "missing - the package may be incomplete")
    print()


# Confirms .env exists and the API key is not still the placeholder.
def check_settings() -> None:
    print("Settings")
    env_path = REPO / ".env"
    values = read_env_file(env_path)
    if not env_path.is_file():
        report("FAIL", ".env", "missing - run setup.bat again")
        print()
        return
    report("OK", ".env found")

    key = values.get("ZAI_API_KEY", "")
    if not key or key == PLACEHOLDER_KEY:
        report("WARN", "ZAI_API_KEY", "still a placeholder - screening cannot run yet")
    else:
        report("OK", "ZAI_API_KEY is set")

    if values.get("CV_LOCAL_NER_ENABLED", "").strip().lower() in {"false", "0", "no"}:
        report("OK", "CV_LOCAL_NER_ENABLED=false")
    else:
        report("WARN", "CV_LOCAL_NER_ENABLED", "should be false on this machine")
    print()


# Loads the real settings object, which is what every command does first.
def check_config_loads() -> None:
    print("Configuration")
    shared_src = REPO / ".codex" / "skills" / "_shared" / "src"
    if str(shared_src) not in sys.path:
        sys.path.insert(0, str(shared_src))
    try:
        from screening_core.config import settings  # noqa: F401
        from screening_core.paths import taxonomy_yaml_path

        report("OK", "settings load", f"model {settings.llm_model}")
        if taxonomy_yaml_path().is_file():
            report("OK", "skill taxonomy readable")
        else:
            report("FAIL", "skill taxonomy", "file not found")
    except Exception as error:  # noqa: BLE001 - report anything that goes wrong
        report("FAIL", "settings load", f"{type(error).__name__}: {error}")
    print()


# Runs every check and prints the closing summary plus the next step.
def main() -> int:
    print()
    print("CV Screening - environment self-check")
    print("=====================================")
    print()
    check_python()
    check_libraries()
    check_engine_files()
    check_settings()
    check_config_loads()

    print("Summary")
    print(f"  {passed} passed, {failed} failed, {warned} warning(s)")
    print()
    if failed:
        print("  This environment is NOT ready. Run setup.bat again.")
        print("  If it keeps failing, send this whole window to your IT contact.")
        return 1
    if warned:
        print("  The environment is ready, but you still have to put your API key")
        print(f"  into {REPO / '.env'} before screening will work.")
        return 0
    print("  The environment is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
