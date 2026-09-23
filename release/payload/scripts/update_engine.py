#!/usr/bin/env python3
"""Self-updater for the CV screening engine (Windows + macOS, stdlib only).

Checks the latest GitHub Release of the engine repo and, when it is newer than
the installed version, applies it: refreshes the engine code and the WorkBuddy
expert, re-runs pip only when requirements changed, and invalidates the score
cache so new code is never silently ignored by the --resume mechanism.

Quiet mode (--quiet) is what the expert calls before the first screen of a
conversation: any failure exits 0 silently so a screening never blocks on the
network.

Cache rules (repo FR-10): on a version change, move (never delete) each report
folder's detail-*.json, rows.json, board-row-*.json and report-fingerprints.json
into _pipeline/_backup-<ts>/. Never touch jd-overrides.yaml or the JD parse
cache -- HR's conditions and the ad parsing are not invalidated by a code
update, and a full re-parse would not be score-neutral.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO_SLUG = "sagee1125/agent-cv-screening"
API_LATEST = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"
ASSET_URL = f"https://github.com/{REPO_SLUG}/releases/latest/download/CV-Screening-Setup.zip"
USER_AGENT = "agent-cv-screening-updater"

# Cache families a code update invalidates (FR-10). Move, never delete.
CACHE_PATTERNS = ("detail-*.json", "rows.json", "board-row-*.json", "report-fingerprints.json")


def log(message: str) -> None:
    print(message, flush=True)


def engine_root() -> Path:
    # Layout: <engine-root>/scripts/update_engine.py
    return Path(__file__).resolve().parents[1]


def read_version_stamp(root: Path) -> dict:
    path = root / "version.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"version": "0.0.0", "requirements_sha256": ""}


def version_tuple(text: str) -> tuple:
    parts = []
    for chunk in "".join(ch if ch.isdigit() or ch == "." else "" for ch in text).split("."):
        parts.append(int(chunk) if chunk else 0)
    return tuple(parts)


def fetch_json(url: str, timeout: float = 10.0):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, destination: Path, timeout: float = 120.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def bust_score_caches(quiet: bool) -> int:
    reports_root = Path.home() / "Desktop" / "workbuddy-cv-screen"
    if not reports_root.is_dir():
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    moved = 0
    for pipeline in sorted(reports_root.glob("*/_pipeline")):
        backup = pipeline / f"_backup-{stamp}"
        hits = [path for pattern in CACHE_PATTERNS for path in pipeline.glob(pattern)]
        if not hits:
            continue
        backup.mkdir(parents=True, exist_ok=True)
        for path in hits:
            target = backup / path.name
            if target.exists():
                continue
            shutil.move(str(path), str(target))
            moved += 1
    if moved and not quiet:
        log(f"[ok] invalidated {moved} cached score files (moved to per-job _backup-{stamp}/).")
        log("     The next screen re-scores with the new code. HR conditions files were untouched.")
    return moved


def apply_update(payload_zip: Path, quiet: bool) -> None:
    import setup_engine  # shipped beside this file

    root = engine_root()
    with tempfile.TemporaryDirectory(prefix="cvs-update-") as tmp:
        extract_dir = Path(tmp) / "payload"
        with zipfile.ZipFile(payload_zip) as archive:
            archive.extractall(extract_dir)
        staged = extract_dir / "engine"
        new_stamp = staged / "version.json"
        if not staged.is_dir() or not new_stamp.is_file():
            raise RuntimeError("downloaded package does not look like an engine release")
        new_version = json.loads(new_stamp.read_text(encoding="utf-8")).get("version", "0")

        requirements_changed = False
        old_req = root / "requirements.txt"
        new_req = staged / "requirements.txt"
        if new_req.is_file() and old_req.is_file():
            import hashlib

            def digest(path: Path) -> str:
                return hashlib.sha256(path.read_bytes()).hexdigest()

            requirements_changed = digest(new_req) != digest(old_req)

        ignore = shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", "_backup-*", ".env", "venv"
        )
        shutil.copytree(staged, root, dirs_exist_ok=True, ignore=ignore)
        pkg = extract_dir
        if (pkg / "expert" / "hr-cv-screener").is_dir():
            setup_engine.install_expert(pkg, root, setup_engine.workbuddy_config_dir())
        setup_engine.install_launcher_files(pkg, root)

        stamp = read_version_stamp(root)
        stamp["version"] = new_version
        if new_req.is_file():
            stamp["requirements_sha256"] = setup_engine.sha256_of(new_req)
        (root / "version.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")

        if requirements_changed:
            venv_python = root / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            if venv_python.is_file():
                log("[..] dependencies changed - updating the Python environment...")
                subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(new_req)], check=False)

        bust_score_caches(quiet)
        if not quiet:
            log(f"[ok] updated to version {new_version}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the CV screening engine from GitHub releases.")
    parser.add_argument("--quiet", action="store_true", help="Silent when up to date or offline; for the expert.")
    parser.add_argument("--check", action="store_true", help="Report only; do not apply.")
    parser.add_argument("--force", action="store_true", help="Apply even when not newer.")
    args = parser.parse_args()

    root = engine_root()
    local = read_version_stamp(root)
    try:
        release = fetch_json(API_LATEST)
        remote_version = str(release.get("tag_name", "")).lstrip("v")
    except Exception as error:  # offline, rate-limited, blocked: never block a screen
        if not args.quiet:
            log(f"[skip] could not check for updates: {error}")
        return 0

    if version_tuple(remote_version) <= version_tuple(local.get("version", "0")) and not args.force:
        if not args.quiet:
            log(f"[ok] up to date (installed {local.get('version')}, latest {remote_version}).")
        return 0

    if args.check:
        log(f"[update available] installed {local.get('version')}, latest {remote_version}.")
        return 0

    try:
        with tempfile.TemporaryDirectory(prefix="cvs-dl-") as tmp:
            payload_zip = Path(tmp) / "CV-Screening-Setup.zip"
            if not args.quiet:
                log(f"[..] downloading version {remote_version}...")
            download(ASSET_URL, payload_zip)
            apply_update(payload_zip, args.quiet)
    except Exception as error:
        if args.quiet:
            return 0
        log(f"[ERROR] update failed: {error}")
        log("The installed engine is untouched and still works. Try again later.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
