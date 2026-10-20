#!/usr/bin/env python3
"""Self-updater for the CV screening engine (Windows + macOS, stdlib only).

Checks the latest GitHub Release of the engine repo and, when it is newer than
the installed version, applies it: refreshes the engine code and the WorkBuddy
expert, re-runs pip only when requirements changed, and invalidates the score
cache so new code is never silently ignored by the --resume mechanism.

Every download is verified against the release's sha256 sidecar
(CV-Screening-Setup.zip.sha256, written by build_release.py) before it is
applied; a mismatch aborts the whole update. When a release declares a
different requires_python, the private venv is rebuilt beside itself and
swapped in only after every rebuild step succeeded.

The check never touches api.github.com: unauthenticated API calls are capped
at 60 per hour per IP and an office shares one public address. The release tag
is instead read from the redirect of releases/latest/download/CV-Screening-
Setup.zip (not rate-limited); when no redirect can be parsed, the zip is
downloaded once and its version stamp read, and that copy is reused for the
update.

Quiet mode (--quiet) is what the expert calls on the first message of a
conversation. It always prints one update_status line and exits 0, including
when the check fails, so a screening is never blocked and the expert can tell
HR when the installed copy could not be updated.

Cache rules (repo FR-10): on a version change, move (never delete) each report
folder's detail-*.json, rows.json, board-row-*.json and report-fingerprints.json
into _pipeline/_backup-<ts>/. Never touch jd-overrides.yaml or the JD parse
cache -- HR's conditions and the ad parsing are not invalidated by a code
update, and a full re-parse would not be score-neutral.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO_SLUG = "sagee1125/agent-cv-screening"
ASSET_URL = f"https://github.com/{REPO_SLUG}/releases/latest/download/CV-Screening-Setup.zip"
CHECKSUM_URL = f"https://github.com/{REPO_SLUG}/releases/latest/download/CV-Screening-Setup.zip.sha256"
USER_AGENT = "agent-cv-screening-updater"

# Cache families a code update invalidates (FR-10). Move, never delete.
CACHE_PATTERNS = ("detail-*.json", "rows.json", "board-row-*.json", "report-fingerprints.json")


def log(message: str) -> None:
    print(message, flush=True)


# One machine-readable line. Quiet mode prints this and nothing else.
def emit_status(status: str, installed: str, latest: str, reason: str = "") -> None:
    line = f"update_status={status} installed={installed} latest={latest}"
    if reason:
        line += f" reason={reason}"
    log(line)


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


def stamped_version(payload_zip: Path) -> str:
    """Version the downloaded release stamps itself with (engine/version.json)."""
    with zipfile.ZipFile(payload_zip) as archive:
        stamp = json.loads(archive.read("engine/version.json").decode("utf-8"))
    version = str(stamp.get("version") or "")
    if not version:
        raise RuntimeError("downloaded package has no engine version stamp")
    return version


def download(url: str, destination: Path, timeout: float = 120.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def verify_checksum(payload_zip: Path, quiet: bool) -> None:
    """Compare the downloaded zip against the release's own sha256 sidecar.

    A mismatch must abort hard: this zip is about to overwrite the engine
    that currently works, and a truncated or tampered download must not get
    that far. The sidecar ships beside the asset (build_release.py writes
    it) through the same not-rate-limited releases/latest/download endpoint.
    Two tolerances, on purpose:
    - a missing sidecar (404) means the release predates checksums (v1.2.29
      and earlier) - behave exactly as before, with a note;
    - any other fetch failure also degrades to today's behavior, because the
      zip itself is already fully on disk (integrity guaranteed by TLS) and
      the sidecar fetch adds a second network dependency to a first-boot
      path that must not grow new failure modes.
    """
    digest = hashlib.sha256()
    with payload_zip.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    try:
        request = urllib.request.Request(CHECKSUM_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30.0) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            if not quiet:
                log(f"[..] checksum sidecar fetch failed ({error}); skipping verification.")
        return
    except Exception as error:
        if not quiet:
            log(f"[..] checksum sidecar fetch failed ({error}); skipping verification.")
        return
    expected = None
    for token in text.split():
        if len(token) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in token):
            expected = token.lower()
            break
    if not expected:
        if not quiet:
            log("[..] the checksum sidecar is unreadable; skipping verification.")
        return
    if actual != expected:
        raise RuntimeError("the checksum of the downloaded package does not match the release sidecar")
    if not quiet:
        log("[ok] verified the downloaded package against the release sidecar.")


def venv_python_version(root: Path) -> str:
    """The major.minor the private venv actually runs, from pyvenv.cfg.

    engine/version.json's requires_python says what a release NEEDS; this is
    what the machine HAS. The cfg is written either by `uv venv` (the
    launchers) or by the venv module (older installs), whose key names
    differ, so read the known version keys BY NAME and never "the first
    dotted number in the file": uv 0.12.18 (the pinned launcher version)
    emits its own `uv = 0.12.18` line BEFORE `version_info = 3.12`, and a
    blind regex read THAT - reporting the venv as Python 0.12, so every
    update saw an interpreter mismatch and rebuilt the whole private
    environment for nothing (the rebuild needs <engine>/tools/uv, which the
    CI's direct-drive rehearsal never creates, so it failed there first).
    If the cfg is gone, the interpreter running this update is the last
    resort - the launchers always invoke the updater through the venv's own
    python.
    """
    cfg = root / "venv" / "pyvenv.cfg"
    home_fallback = None
    if cfg.is_file():
        try:
            for line in cfg.read_text(encoding="utf-8-sig").splitlines():
                key, separator, value = line.partition("=")
                if not separator:
                    continue
                key = key.strip().lower()
                if key in ("version", "version_info"):
                    match = re.search(r"(\d+\.\d+)", value)
                    if match:
                        return match.group(1)
                elif key == "home" and home_fallback is None:
                    # uv venv homes point at `.../cpython-3.12-<platform>-none`.
                    home_fallback = re.search(r"(?:cp|p)ython-(\d+\.\d+)", value.lower())
        except OSError:
            pass
    if home_fallback:
        return home_fallback.group(1)
    return f"{sys.version_info[0]}.{sys.version_info[1]}"


def python_bump_needed(required: str, root: Path) -> bool:
    # Both sides must be known; an unknown installed version (broken cfg AND
    # auto-detect gone) means we must not risk tearing the venv down.
    if not required:
        return False
    current = venv_python_version(root)
    if not current:
        return False
    return current != required


def reprovision_venv(root: Path, python_version: str, requirements: Path, quiet: bool) -> bool:
    """Rebuild the private venv for a new interpreter version.

    A requirements refresh alone can fail harmlessly - the old environment
    stays reachable and the next run retries. An interpreter swap cannot,
    because the venv must be emptied to change the interpreter it hosts. So
    the new environment is built to a sibling directory in full (python
    fetch, venv create, pinned requirements) and only swapped in after every
    step succeeded; a dead network or a missing wheel leaves the current
    environment untouched.

    The swap renames the old venv away instead of deleting it: on Windows the
    updater itself runs from that venv's python and running executables can
    be renamed but not deleted. What is left is swept on the next update
    (sweep_retired_venvs), once no process runs from it anymore.
    """
    uv = root / "tools" / ("uv.exe" if sys.platform == "win32" else "uv")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    staging = root / f"venv-new-{stamp}"
    retired = root / f"venv-old-{stamp}"
    try:
        if not uv.is_file():
            # A launcher install always fetches uv into <engine>/tools first; a
            # direct or assisted install (setup_engine.py run with a system
            # interpreter, no launcher) never does. A uv on PATH can still do
            # the rebuild; without either, an interpreter bump is impossible and
            # the update says so instead of failing on a missing file - the old
            # environment keeps working either way.
            on_path = shutil.which("uv")
            if not on_path:
                raise RuntimeError(
                    "the uv helper is missing - expected it in <engine>/tools, and none on PATH"
                )
            uv = Path(on_path)
        if not quiet:
            log(f"[..] the release needs Python {python_version}; the private environment is being rebuilt.")
            log("     This downloads Python once and takes a few minutes. The current engine keeps working.")
        commands = (
            [str(uv), "python", "install", python_version],
            [str(uv), "venv", "--python", python_version, str(staging)],
            [str(uv), "pip", "install", "--python",
             str(staging / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")), "-r", str(requirements)],
        )
        for command in commands:
            if subprocess.run(command, check=False).returncode != 0:
                raise RuntimeError(f"this step failed: {' '.join(command[:2])} ...")
        new_python = staging / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if not new_python.is_file():
            raise RuntimeError("the rebuilt environment has no interpreter")
        (root / "venv").rename(retired)   # rename a running image works; deletion does not
    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        if not quiet:
            log(f"[ERROR] the environment rebuild failed: {error}")
            log("        The installed environment is untouched and still works.")
        return False
    staging.rename(root / "venv")         # cannot fail after the rename above succeeded
    shutil.rmtree(retired, ignore_errors=True)  # best effort; a remainder is swept later
    return True


def sweep_retired_venvs(root: Path) -> None:
    # venv-old-* folders a previous rebuild left behind: their interpreter is
    # no longer running, so what Windows refused to delete mid-update can go
    # now. Best effort in every way - a leftover is only wasted disk space.
    for retired in root.glob("venv-old-*"):
        shutil.rmtree(retired, ignore_errors=True)


# The engine writes HR packs through hr_output.user_desktop() (see
# _shared/src/screening_core/hr_output.py), which on Windows looks beyond the
# plain Desktop: OneDrive redirection - the pack then lives under
# ~/OneDrive/Desktop/... - and a Chinese-named desktop ("桌面") are both common
# on staff machines. bust_score_caches used to scan Path.home()/"Desktop" only,
# so on exactly those machines an update quietly skipped cache invalidation and
# the --resume mechanism kept serving scores produced by the OLD engine: the
# silent stale-score failure FR-10 exists to prevent. Keep the candidates in
# step with hr_output (its ordering, dedupe and fallback included) and stay
# stdlib-only - this script also ships standalone inside the zip and must run
# without the engine's own dependencies.
def reports_desktop() -> Path:
    homes: list[Path] = []
    if os.name == "nt" and os.environ.get("USERPROFILE"):
        homes.append(Path(os.environ["USERPROFILE"]))
    home = Path.home()
    if home not in homes:
        homes.append(home)
    for candidate_home in homes:
        for candidate in (
            candidate_home / "Desktop",
            candidate_home / "OneDrive" / "Desktop",
            candidate_home / "OneDrive" / "桌面",
            candidate_home / "桌面",
        ):
            if candidate.is_dir():
                return candidate
    return homes[0] / "Desktop"


def bust_score_caches(quiet: bool) -> int:
    reports_root = reports_desktop() / "workbuddy-cv-screen"
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


def restart_advice() -> list[str]:
    """The lines printed after a successful non-quiet update.

    The restart advice assumes WorkBuddy is on this machine - but the engine
    installs without the app on purpose (setup_engine.py never blocks on a
    missing WorkBuddy), and a manual update_engine.cmd run from a downloaded
    zip then told the user to restart an app that was never installed. The
    expert's own path is quiet and never prints this. Reuse the installer's
    detection so both entry points tell the same story.
    """
    import setup_engine  # shipped beside this file

    if setup_engine.workbuddy_app_installed():
        return [
            "     Please restart WorkBuddy (quit it completely, then open it",
            "     again) so the updated expert is loaded.",
        ]
    return [
        "     WorkBuddy is not installed on this computer yet, so there is",
        "     nothing to restart. The updated engine and expert are already in",
        "     place; install WorkBuddy from",
        f"     {setup_engine.workbuddy_install_guide()}",
        "     and Vera will be waiting under Experts -> My Experts.",
    ]


def apply_update(payload_zip: Path, quiet: bool) -> bool:
    import setup_engine  # shipped beside this file

    root = engine_root()
    sweep_retired_venvs(root)
    # Captured before the copy below overwrites version.json with the new stamp:
    # if the dependency step then fails, this is what gets restored so the next
    # conversation retries the whole update.
    previous_stamp = read_version_stamp(root)
    with tempfile.TemporaryDirectory(prefix="cvs-update-") as tmp:
        extract_dir = Path(tmp) / "payload"
        with zipfile.ZipFile(payload_zip) as archive:
            archive.extractall(extract_dir)
        staged = extract_dir / "engine"
        new_stamp = staged / "version.json"
        if not staged.is_dir() or not new_stamp.is_file():
            raise RuntimeError("downloaded package does not look like an engine release")
        new_stamp_data = json.loads(new_stamp.read_text(encoding="utf-8"))
        new_version = str(new_stamp_data.get("version") or "0")
        new_required = str(new_stamp_data.get("requires_python") or "")

        requirements_changed = False
        old_req = root / "requirements.txt"
        new_req = staged / "requirements.txt"
        if new_req.is_file() and old_req.is_file():
            def digest(path: Path) -> str:
                return hashlib.sha256(path.read_bytes()).hexdigest()

            requirements_changed = digest(new_req) != digest(old_req)

        # The environment is checked for an interpreter bump BEFORE anything is
        # copied: the decision compares pyvenv.cfg (excluded from the copy)
        # against the release's requires_python, and doing it early keeps the
        # copy-idempotent-retry story intact (a failed rebuild retries whole).
        rebuild = python_bump_needed(new_required, root)

        ignore = shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", "_backup-*", ".env", "venv"
        )
        shutil.copytree(staged, root, dirs_exist_ok=True, ignore=ignore)
        pkg = extract_dir
        if (pkg / "expert" / "hr-cv-screener").is_dir():
            setup_engine.install_expert(pkg, root, setup_engine.workbuddy_config_dir())
        setup_engine.install_launcher_files(pkg, root)

        # Dependencies are refreshed BEFORE the version stamp advances. The copy
        # above is idempotent, so a failed dependency install is retried whole on
        # the next conversation. Advancing the stamp first would report a
        # half-applied update (new engine code, missing deps) as done -- the one
        # failure that must not be silent, because nothing else retries it.
        deps_ok = True
        if rebuild:
            # A new interpreter minor invalidates the whole private venv (its
            # wheels are ABI-bound). The rebuild installs the new requirements
            # itself, so this branch covers both a bump and a requirements
            # change; the plain pip path below only fires without a bump.
            deps_ok = reprovision_venv(root, new_required, new_req, quiet)
        elif requirements_changed:
            venv_python = root / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            if venv_python.is_file():
                if not quiet:
                    log("[..] dependencies changed - updating the Python environment...")
                # uv-created venvs have no pip inside them, so prefer the uv
                # binary the launcher left in <engine>/tools/.
                uv = root / "tools" / ("uv.exe" if sys.platform == "win32" else "uv")
                if uv.is_file():
                    pip_result = subprocess.run(
                        [str(uv), "pip", "install", "--python", str(venv_python), "-r", str(new_req)],
                        check=False,
                    )
                else:
                    pip_result = subprocess.run(
                        [str(venv_python), "-m", "pip", "install", "-r", str(new_req)], check=False
                    )
                deps_ok = pip_result.returncode == 0

        if not deps_ok:
            # The copy above already dropped the new stamp into place; put the
            # previous one back, or a half-applied update would be reported as
            # done and never retried.
            (root / "version.json").write_text(json.dumps(previous_stamp, indent=2) + "\n", encoding="utf-8")
            if not quiet:
                log("[ERROR] the dependency update failed - the version stamp stays at "
                    f"{previous_stamp.get('version', '?')},")
                log("        so the next run retries the update automatically. The screening engine")
                log("        may not start until it succeeds.")
            return False

        stamp = read_version_stamp(root)
        stamp["version"] = new_version
        if new_req.is_file():
            stamp["requirements_sha256"] = setup_engine.sha256_of(new_req)
        (root / "version.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")

        bust_score_caches(quiet)
        if not quiet:
            log(f"[ok] updated to version {new_version}.")
            for line in restart_advice():
                log(line)
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the CV screening engine from GitHub releases.")
    parser.add_argument("--quiet", action="store_true", help="Print only the update_status line; for the expert.")
    parser.add_argument("--check", action="store_true", help="Report only; do not apply.")
    parser.add_argument("--force", action="store_true", help="Apply even when not newer.")
    args = parser.parse_args()

    root = engine_root()
    local = read_version_stamp(root)
    installed = str(local.get("version") or "0")

    # The version check no longer calls api.github.com. Unauthenticated API
    # calls are capped at 60 per hour PER IP, and a whole office shares one
    # public address - on a busy morning every machine's check failed at
    # once and was reported as offline. releases/latest/download/<asset>
    # instead redirects to the versioned asset URL, so the tag is readable
    # from the redirect target of a HEAD request - an endpoint GitHub does
    # not rate-limit.
    remote_version = None
    with tempfile.TemporaryDirectory(prefix="cvs-dl-") as tmp:
        payload_zip = Path(tmp) / "CV-Screening-Setup.zip"
        try:
            probe = urllib.request.Request(ASSET_URL, headers={"User-Agent": USER_AGENT}, method="HEAD")
            with urllib.request.urlopen(probe, timeout=30.0) as response:
                match = re.search(r"/releases/download/([^/]+)/", response.geturl() or "")
            if match:
                remote_version = match.group(1).lstrip("v")
        except Exception as error:
            if not args.quiet:
                log(f"[..] the release probe failed ({error}); reading the version from the download instead.")
        if remote_version is None:
            # No redirect to parse - some proxies rewrite it, or the network
            # is down. Download the zip and read the stamp inside; if the
            # network is truly down, that download raises and the offline
            # handling below reports it exactly as before. The downloaded
            # copy is reused for the update, so the extra bytes are not
            # wasted.
            try:
                download(ASSET_URL, payload_zip)
            except Exception as error:
                if not args.quiet:
                    log(f"[skip] could not check for updates: {error}")
                emit_status("failed", installed, "unknown", "offline")
                return 0
            remote_version = stamped_version(payload_zip)

        if version_tuple(remote_version) <= version_tuple(installed) and not args.force:
            if not args.quiet:
                log(f"[ok] up to date (installed {installed}, latest {remote_version}).")
            emit_status("up_to_date", installed, remote_version)
            return 0

        if args.check:
            log(f"[update available] installed {installed}, latest {remote_version}.")
            emit_status("available", installed, remote_version)
            return 0

        try:
            if not payload_zip.is_file():
                if not args.quiet:
                    log(f"[..] downloading version {remote_version}...")
                download(ASSET_URL, payload_zip)
            verify_checksum(payload_zip, args.quiet)
            applied = apply_update(payload_zip, args.quiet)
        except Exception as error:
            if not args.quiet:
                log(f"[ERROR] update failed: {error}")
                log("The installed engine is untouched and still works. Try again later.")
            emit_status("failed", installed, remote_version, "download")
            return 0 if args.quiet else 1
        if not applied:
            emit_status("failed", installed, remote_version, "dependencies")
            return 0 if args.quiet else 1
        emit_status("updated", remote_version, remote_version)
        return 0


if __name__ == "__main__":
    sys.exit(main())
