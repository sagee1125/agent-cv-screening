#!/usr/bin/env python3
"""Builds the CV-Screening-Setup.zip release asset.

Layout produced (this is the layout release/payload/scripts/setup_engine.py
expects when it runs from the extracted zip):

    CV-Screening-Setup.zip
    |-- setup.bat / setup.command / update_engine.cmd / update_engine.command
    |-- START-HERE.txt
    |-- scripts/{setup_engine.py,update_engine.py}
    |-- expert/hr-cv-screener/     (WorkBuddy expert, TESTING.md excluded)
    `-- engine/                    (.codex, data/taxonomy, demo_mode.json,
                                    requirements.txt, .env.example,
                                    version.json  <- build version stamp)

The asset name is intentionally version-free so the self-updater can always
fetch releases/latest/download/CV-Screening-Setup.zip; the version lives in
engine/version.json and in the git tag.

Expert source resolution:
- default: the committed snapshot at release/expert/hr-cv-screener (what CI uses)
- --expert-dir <path>: use another copy (e.g. the live WorkBuddy marketplace dir)
- --sync-expert: copy the live dir into release/expert/hr-cv-screener first,
  so the committed snapshot stays current after expert edits. TESTING.md is
  never synced or packaged: it is an internal test protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = Path(__file__).resolve().parent
PAYLOAD = RELEASE_ROOT / "payload"
LIVE_EXPERT = Path.home() / ".workbuddy-ai" / "plugins" / "marketplaces" / "my-experts" / "plugins" / "hr-cv-screener"

ENGINE_COPY = (".codex", "data/taxonomy", "demo_mode.json", ".env.example")
EXPERT_EXCLUDE = ("TESTING.md",)
IGNORE_DIRS = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "_backup-*")
EXECUTABLE_NAMES = ("setup.command", "update_engine.command")

# Files that must never end up in a public release.
FORBIDDEN_IN_ZIP = (".env", "id_rsa", "*.pem", "jas_state")


def sync_expert(live: Path, snapshot: Path) -> None:
    if not (live / ".codebuddy-plugin" / "plugin.json").is_file():
        raise SystemExit(f"[ERROR] live expert not found at {live}")
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(live, snapshot, ignore=IGNORE_DIRS)
    for name in EXPERT_EXCLUDE:
        doomed = snapshot / name
        if doomed.exists():
            doomed.unlink()
    print(f"[ok] expert snapshot synced from {live}")


def stage_engine(stage: Path, version: str) -> str:
    engine = stage / "engine"
    engine.mkdir(parents=True)
    for entry in ENGINE_COPY:
        source = REPO_ROOT / entry
        destination = engine / entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, ignore=IGNORE_DIRS)
        elif source.is_file():
            shutil.copy2(source, destination)
        else:
            raise SystemExit(f"[ERROR] expected repo entry missing: {entry}")
    # The engine's runtime requirements: the pinned CLI-only set (release/
    # engine-requirements.txt), NOT the repo-root requirements.txt, which is an
    # unrelated leftover and would break the chain on a clean machine.
    engine_requirements = RELEASE_ROOT / "engine-requirements.txt"
    shutil.copy2(engine_requirements, engine / "requirements.txt")
    digest = hashlib.sha256((engine / "requirements.txt").read_bytes()).hexdigest()
    stamp = {"version": version, "requirements_sha256": digest}
    (engine / "version.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return digest


def stage_expert(stage: Path, expert_dir: Path) -> None:
    destination = stage / "expert" / "hr-cv-screener"
    shutil.copytree(expert_dir, destination, ignore=IGNORE_DIRS)
    for name in EXPERT_EXCLUDE:
        doomed = destination / name
        if doomed.exists():
            doomed.unlink()


def sanity_checks(stage: Path) -> None:
    required = [
        stage / "scripts" / "setup_engine.py",
        stage / "scripts" / "update_engine.py",
        stage / "setup.bat",
        stage / "setup.command",
        stage / "update_engine.cmd",
        stage / "update_engine.command",
        stage / "START-HERE.txt",
        stage / "engine" / ".codex" / "skills" / "jas-import" / "scripts" / "run_jas_screening.py",
        stage / "engine" / "data" / "taxonomy" / "skill_taxonomy.yaml",
        stage / "engine" / "demo_mode.json",
        stage / "engine" / "requirements.txt",
        stage / "engine" / "version.json",
        stage / "expert" / "hr-cv-screener" / ".codebuddy-plugin" / "plugin.json",
        stage / "expert" / "hr-cv-screener" / "agents" / "hr-cv-screener.md",
        stage / "expert" / "hr-cv-screener" / "skills" / "hr-cv-screening" / "SKILL.md",
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        for path in missing:
            print(f"[ERROR] missing from payload: {path.relative_to(stage)}")
        raise SystemExit(1)
    # Private-file guard.
    for pattern in FORBIDDEN_IN_ZIP:
        hits = [p for p in stage.rglob(pattern) if p.is_file()]
        if hits:
            for hit in hits:
                print(f"[ERROR] private file must not ship: {hit.relative_to(stage)}")
            raise SystemExit(1)


def write_zip(stage: Path, output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
            mode = 0o755 if path.name in EXECUTABLE_NAMES else 0o644
            info.external_attr = (mode << 16) | 0o100000
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the CV screening release zip.")
    parser.add_argument("version", help="Release version, e.g. 1.0.0 (no leading v).")
    parser.add_argument("--expert-dir", type=Path, default=None, help="Expert source dir (default: the committed snapshot).")
    parser.add_argument("--sync-expert", action="store_true", help="Refresh the committed snapshot from the live WorkBuddy dir first.")
    parser.add_argument("--output", type=Path, default=None, help="Output zip path (default release/dist/CV-Screening-Setup.zip).")
    args = parser.parse_args()

    expert_dir = args.expert_dir
    if args.sync_expert or expert_dir is None:
        snapshot = RELEASE_ROOT / "expert" / "hr-cv-screener"
        if args.sync_expert:
            sync_expert(LIVE_EXPERT, snapshot)
        expert_dir = expert_dir or snapshot
    if not (expert_dir / ".codebuddy-plugin" / "plugin.json").is_file():
        raise SystemExit(f"[ERROR] expert not found at {expert_dir}")

    with tempfile.TemporaryDirectory(prefix="cvs-release-") as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        shutil.copytree(PAYLOAD, stage, dirs_exist_ok=True, ignore=IGNORE_DIRS)
        requirements_sha = stage_engine(stage, args.version)
        stage_expert(stage, expert_dir)
        sanity_checks(stage)
        output = args.output or (RELEASE_ROOT / "dist" / "CV-Screening-Setup.zip")
        digest = write_zip(stage, output)
        size_kb = output.stat().st_size / 1024
        entries = sum(1 for p in stage.rglob("*") if p.is_file())

    print("")
    print(f"[ok] built {output}")
    print(f"     version {args.version} | {entries} files | {size_kb:.0f} KB")
    print(f"     requirements sha256 {requirements_sha[:16]}...")
    print(f"     zip sha256 {digest}")
    print("Next: commit, tag vX.Y.Z and push - CI attaches this zip to the GitHub release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
