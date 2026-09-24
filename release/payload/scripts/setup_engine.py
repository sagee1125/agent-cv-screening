#!/usr/bin/env python3
"""One-shot installer for the CV screening engine and the WorkBuddy expert.

Cross-platform (Windows + macOS). Runs under any Python 3.10+ interpreter and
creates the engine venv itself. All console output is ASCII so Windows code
pages cannot garble it. The zip layout this script expects:

    CV-Screening-Setup.zip
    |-- setup.bat / setup.command      (thin launchers, any OS runs one)
    |-- update_engine.cmd / .command   (thin updater launchers)
    |-- START-HERE.txt
    |-- scripts/setup_engine.py        (this file)
    |-- scripts/update_engine.py
    |-- expert/hr-cv-screener/         (WorkBuddy expert package)
    `-- engine/                        (.codex, data/taxonomy, demo_mode.json,
                                        requirements.txt, .env.example)

After install, the engine root (default C:\\agent-cv-screening on Windows,
~/agent-cv-screening on macOS) holds .codex and venv at its top level, which is
exactly the layout the packaged skill's paths refer to.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_SLUG = "sagee1125/agent-cv-screening"
ENGINE_CODENAME = "agent-cv-screening"

# Interpreter versions the pinned dependency set actually ships wheels for.
# Verified against PyPI: PyYAML 6.0.2 and pydantic-core 2.27.2 have no cp314
# wheels (pip would need a C++/Rust toolchain), and numpy 2.5.2 has no cp310 /
# cp311 wheels either. 3.12 is the version the engine is tested on.
SUPPORTED_PYTHON = {(3, 12), (3, 13)}

# Required .env keys for screening_core.config.Settings (checked at import time
# even for CLI-only use, so the installer must write all of them).
ENV_TEMPLATE = """\
# Screening engine configuration.
#
# The API key below is the only value HR needs to supply.
ZAI_API_KEY={api_key}

LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4-flash
LLM_VISION_MODEL=glm-4v-flash

# The optional on-device name-detection model is switched off, because it
# needs a ~700 MB download that is not part of this package. Name detection
# falls back to the built-in text heuristics.
CV_LOCAL_NER_ENABLED=false

# Not used by the screening commands. The settings loader requires these two
# values to be present, so harmless placeholders are fine here.
DATABASE_URL=postgresql://unused:unused@localhost:5432/unused
SECRET_KEY={secret_key}

# Where working files are kept. Relative to this folder.
UPLOAD_DIR=./data/uploads
REPORT_DIR=./data/reports
CACHE_DIR=./data/cache
"""

MARKETPLACE_DESCRIPTION = (
    "Screens job applicants for HR: reads a job ad and every candidate CV, "
    "scores them on five dimensions, and writes a ranking overview plus "
    "individual reports to the Desktop. Identifies candidates by application "
    "number only."
)


def log(message: str) -> None:
    print(message, flush=True)


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_engine_target() -> Path:
    if sys.platform == "win32":
        candidate = Path("C:/") / ENGINE_CODENAME
        probe = candidate / ".write-probe"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            return Path.home() / ENGINE_CODENAME
    return Path.home() / ENGINE_CODENAME


def copy_engine(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".pytest_cache", "_backup-*", ".env", "venv"
    )
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
    # User state survives reinstalls and updates.
    for keep in ("jas_state", "cache", "uploads", "reports"):
        (dst / "data" / keep).mkdir(parents=True, exist_ok=True)


def install_launcher_files(pkg: Path, dst: Path) -> None:
    for name in (
        "START-HERE.txt",
        "setup.bat",
        "setup.command",
        "update_engine.cmd",
        "update_engine.command",
    ):
        src = pkg / name
        if src.is_file():
            shutil.copy2(src, dst / name)
    # Always copy from the payload's scripts dir. Copying from __file__ would
    # make the updater overwrite its own running file on Windows (WinError 32).
    scripts_src = pkg / "scripts"
    for name in ("setup_engine.py", "update_engine.py"):
        src = scripts_src / name
        dst_file = dst / "scripts" / name
        if not src.is_file() or src.resolve() == dst_file.resolve():
            continue
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_file)


def looks_like_real_key(value: str) -> bool:
    return bool(value) and not value.startswith("<") and "your-api-key" not in value


def write_env(engine_dst: Path, api_key: str) -> None:
    env_path = engine_dst / ".env"
    if env_path.is_file():
        existing = env_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^ZAI_API_KEY=(.*)$", existing, re.MULTILINE)
        if match and looks_like_real_key(match.group(1).strip()):
            log("[ok] .env already has an API key - keeping it.")
            return
    if not api_key:
        api_key = input("Paste your API key (ZAI_API_KEY): ").strip()
    if not looks_like_real_key(api_key):
        log("[WARN] No usable API key entered. A placeholder .env was written;")
        log("       edit .env in the engine folder later, then rerun setup.")
        api_key = "<your-api-key>"
    env_path.write_text(
        ENV_TEMPLATE.format(api_key=api_key, secret_key=secrets.token_hex(32)),
        encoding="utf-8",
    )
    log("[ok] .env written.")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def venv_python_path(engine_dst: Path) -> Path:
    return engine_dst / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def build_venv(engine_dst: Path, prepared_by_bootstrap: bool) -> None:
    """Ensure the private environment exists.

    The normal install path is the launcher (setup.bat / setup.command), which
    provisions Python 3.12 and the venv with uv and then passes --skip-venv.
    The creation path below only runs when someone starts this script directly
    with a system interpreter (development machines).
    """
    venv_dir = engine_dst / "venv"
    python = venv_python_path(engine_dst)
    if prepared_by_bootstrap:
        if python.is_file():
            log("[ok] private environment already prepared.")
            return
        log("[ERROR] --skip-venv was passed but no environment exists yet.")
        log("        Run setup.bat (Windows) or setup.command (Mac) instead.")
        raise SystemExit(1)
    log("[..] creating the Python environment (one-time, a few minutes)...")
    venv.create(venv_dir, with_pip=True)
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(engine_dst / "requirements.txt")],
        check=True,
    )
    log("[ok] Python environment ready.")


def workbuddy_config_dir() -> Path:
    for candidate in (Path.home() / ".workbuddy-ai", Path.home() / ".workbuddy"):
        if candidate.is_dir():
            return candidate
    chosen = Path.home() / ".workbuddy-ai"
    chosen.mkdir(parents=True, exist_ok=True)
    return chosen


def rewrite_skill_paths(skill_md: Path, engine_dst: Path) -> None:
    text = skill_md.read_text(encoding="utf-8")
    text = text.replace("C:/agent-cv-screening", engine_dst.as_posix())
    text = text.replace("C:\\\\agent-cv-screening", str(engine_dst))
    text = text.replace("C:\\agent-cv-screening", str(engine_dst))
    skill_md.write_text(text, encoding="utf-8")


def install_expert(pkg: Path, engine_dst: Path, config_dir: Path) -> None:
    src = pkg / "expert" / "hr-cv-screener"
    dst = config_dir / "plugins" / "marketplaces" / "my-experts" / "plugins" / "hr-cv-screener"
    shutil.copytree(src, dst, dirs_exist_ok=True)
    rewrite_skill_paths(dst / "skills" / "hr-cv-screening" / "SKILL.md", engine_dst)

    manifest_dir = config_dir / "plugins" / "marketplaces" / "my-experts" / ".codebuddy-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "marketplace.json"
    manifest = {"name": "my-experts", "description": "my-experts marketplace (auto-generated)", "plugins": []}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    manifest.setdefault("name", "my-experts")
    manifest.setdefault("description", "my-experts marketplace (auto-generated)")
    plugins = [p for p in manifest.get("plugins", []) if p.get("name") != "hr-cv-screener"]
    plugins.append({"name": "hr-cv-screener", "source": "./plugins/hr-cv-screener", "description": MARKETPLACE_DESCRIPTION})
    manifest["plugins"] = plugins
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"[ok] expert installed for WorkBuddy at: {dst}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the CV screening engine and expert.")
    parser.add_argument("--engine-target", default=None, help="Install location (default: C:\\agent-cv-screening or ~/agent-cv-screening).")
    parser.add_argument("--api-key", default=None, help="ZAI_API_KEY (skips the prompt).")
    parser.add_argument("--version", default="0.0.0", help="Version stamp written to version.json.")
    parser.add_argument("--skip-venv", action="store_true", help="The launcher already prepared Python 3.12 and the venv with uv.")
    args = parser.parse_args()

    pkg = package_root()
    engine_src = pkg / "engine"
    expert_src = pkg / "expert" / "hr-cv-screener"
    if not engine_src.is_dir() or not expert_src.is_dir():
        log("[ERROR] This installer must run from the release zip (engine/ or expert/ missing).")
        return 1

    # Only relevant when this script itself has to create the environment from
    # a system interpreter. With --skip-venv the interpreter is already the
    # private Python 3.12 that uv provisioned.
    if not args.skip_venv and sys.version_info[:2] not in SUPPORTED_PYTHON:
        current = f"{sys.version_info.major}.{sys.version_info.minor}"
        log(f"[ERROR] Python {current} cannot build this environment.")
        log("        Run setup.bat (Windows) or setup.command (Mac) instead - the")
        log("        launcher provisions its own private Python 3.12 with uv and")
        log("        never touches the Python installed on this computer.")
        return 1

    engine_dst = Path(args.engine_target).expanduser() if args.engine_target else default_engine_target()
    log(f"Installing the screening engine to: {engine_dst}")

    engine_dst.mkdir(parents=True, exist_ok=True)
    copy_engine(engine_src, engine_dst)
    (engine_dst / "scripts").mkdir(parents=True, exist_ok=True)
    install_launcher_files(pkg, engine_dst)
    write_env(engine_dst, args.api_key or "")

    build_venv(engine_dst, args.skip_venv)

    config_dir = workbuddy_config_dir()
    install_expert(pkg, engine_dst, config_dir)

    stamp = {
        "version": args.version,
        "requirements_sha256": sha256_of(engine_dst / "requirements.txt"),
    }
    (engine_dst / "version.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")

    # Post-install self-test: proves the private environment and the engine's
    # import chain work on THIS computer, before HR ever opens WorkBuddy.
    # Rule-mode JD parsing needs no API key and finishes in seconds.
    log("")
    log("[..] self-test: running a short parsing check on this computer...")
    interpreter = venv_python_path(engine_dst)
    if not interpreter.is_file():
        interpreter = Path(sys.executable)
    selftest = subprocess.run(
        [str(interpreter), str(engine_dst / ".codex" / "skills" / "jd-parser" / "scripts" / "run_jd_parse.py"),
         "--jd-text", "Requirements: Bachelor degree in Computer Science; programming experience in Python."],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(engine_dst), timeout=240,
    )
    if selftest.returncode == 0 and '"parse_path"' in (selftest.stdout or ""):
        log("[ok] self-test passed - the screening engine works on this computer.")
    else:
        log("[WARN] the engine self-test did not pass. The install itself is in place;")
        log("       please send us a screenshot of this window so we can see why.")

    log("")
    log("Install complete.")
    log(f"  Engine + reports : {engine_dst}")
    log(f"  Expert installed : {config_dir}")
    log("Next steps:")
    log("  1. Restart WorkBuddy (quit fully, then open it again).")
    log("  2. Open Experts -> My Experts -> Vera.")
    log("  3. Say: screen refno 260901004   (a demo job, safe to try).")
    log("  4. Reports land on your Desktop, in the folder workbuddy-cv-screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
