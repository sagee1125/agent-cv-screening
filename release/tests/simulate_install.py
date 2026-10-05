#!/usr/bin/env python3
"""Self-test for the release zip: simulates a clean HR computer locally.

Run this BEFORE tagging a release:

    python release/tests/simulate_install.py            # uses release/dist/CV-Screening-Setup.zip
    python release/tests/simulate_install.py --zip <path>
    python release/tests/simulate_install.py --setup-bat   # install by running the shipped setup.bat
    python release/tests/simulate_install.py --update   # also rehearses the live updater

By default the install steps are driven directly (uv, then setup_engine.py), which is fast and
keeps the product's own logic out of the way. `--setup-bat` instead runs the script HR actually
double-clicks, end to end, so the uv fetch and unpack are covered as well - those are the steps
that fail on a real machine and the direct path never executes. It is slower (it re-downloads uv)
and it needs Windows.

What it does, in a disposable sandbox (a fake HOME, nothing touches your real
profile or the live WorkBuddy config):
  1. extracts the release zip,
  2. fetches uv (cached in release/tests/.cache),
  3. provisions a private Python 3.12 with uv,
  4. creates the venv and installs the pinned requirements,
  5. runs the installer (env + expert + marketplace merge + path rewrite),
  6. runs a rule-mode JD parse as an engine smoke test,
  7. checks the version stamp, .env, expert paths and marketplace manifest.

Exit code 0 = every check passed. Requires internet (github.com + pypi.org).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).resolve().parent / ".cache"
UV_VERSION = "0.12.18"

UV_ASSETS = {
    ("windows", "AMD64"): "uv-x86_64-pc-windows-msvc.zip",
    ("windows", "ARM64"): "uv-aarch64-pc-windows-msvc.zip",
    ("darwin", "arm64"): "uv-aarch64-apple-darwin.tar.gz",
    ("darwin", "x86_64"): "uv-x86_64-apple-darwin.tar.gz",
    ("linux", "x86_64"): "uv-x86_64-unknown-linux-gnu.tar.gz",
    ("linux", "aarch64"): "uv-aarch64-unknown-linux-gnu.tar.gz",
}


def log(message: str) -> None:
    print(message, flush=True)


failures: list[str] = []


def check(name: str, ok: bool) -> bool:
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    if not ok:
        failures.append(name)
    return ok


def system_key() -> tuple[str, str]:
    system = "windows" if sys.platform == "win32" else platform.system().lower()
    machine = platform.machine().upper() if sys.platform == "win32" else platform.machine().lower()
    return system, machine


def uv_asset() -> str:
    system, machine = system_key()
    key = (system, "AMD64" if machine in ("AMD64", "X86_64") else "ARM64" if "ARM" in machine.upper() else machine)
    if key not in UV_ASSETS:
        raise SystemExit(f"[ERROR] no uv asset mapping for {key}")
    return UV_ASSETS[key]


def fetch(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "simulate-install"})
    with urllib.request.urlopen(request, timeout=600) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def prepare_uv(sandbox: Path) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    asset = uv_asset()
    archive = CACHE / asset
    if not archive.exists():
        log(f"[..] downloading {asset} (once, cached in release/tests/.cache)...")
        fetch(f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{asset}", archive)
    tools = sandbox / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    if asset.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extract("uv.exe", tools)
        return tools / "uv.exe"
    with tarfile.open(archive) as tar:
        member = next(m for m in tar.getmembers() if m.name.endswith("/uv"))
        member.name = "uv"
        tar.extract(member, tools)
    binary = tools / "uv"
    binary.chmod(0o755)
    return binary


def staged_requirements(sandbox: Path) -> Path:
    return sandbox / "engine" / "requirements.txt"


# The line in the shipped setup.bat that decides where the engine is installed.
SETUP_BAT_TARGET_LINE = "set TARGET=C:\\agent-cv-screening"


# A copy of the shipped setup.bat with exactly one line redirected into the sandbox.
#
# The rehearsal used to skip setup.bat entirely - it drove uv and setup_engine.py by hand - which
# meant the file HR actually double-clicks was never executed. Running it verbatim is not safe on a
# developer machine: it hard-codes TARGET=C:\agent-cv-screening, which is a real installation here,
# so it would overwrite it. Only that line is changed, and the one-line diff is asserted, so the
# rehearsal cannot quietly drift into testing a different script.
def stage_setup_bat(pkg: Path, target: Path) -> Path:
    source = pkg / "setup.bat"
    text = source.read_text(encoding="utf-8", errors="replace")
    if text.count(SETUP_BAT_TARGET_LINE) != 1:
        raise SystemExit(
            f"[ERROR] setup.bat no longer contains exactly one {SETUP_BAT_TARGET_LINE!r} line - "
            "update the rehearsal before trusting it."
        )
    staged = pkg / "setup.rehearsal.bat"
    staged.write_text(text.replace(SETUP_BAT_TARGET_LINE, f"set TARGET={target}", 1), encoding="utf-8")
    before, after = text.splitlines(), staged.read_text(encoding="utf-8").splitlines()
    diff = [(a, b) for a, b in zip(before, after) if a != b]
    if len(before) != len(after) or len(diff) != 1:
        raise SystemExit(f"[ERROR] staging setup.bat changed more than the TARGET line: {diff}")
    return staged


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate a clean HR computer and install the release zip.")
    parser.add_argument("--zip", type=Path, default=REPO / "release" / "dist" / "CV-Screening-Setup.zip")
    parser.add_argument("--update", action="store_true", help="After the install, rehearse the live updater.")
    parser.add_argument("--keep", action="store_true", help="Keep the sandbox for inspection.")
    parser.add_argument(
        "--setup-bat",
        action="store_true",
        help="Install by running the shipped setup.bat (the file HR double-clicks) instead of "
             "driving uv and setup_engine.py by hand. Slower, Windows-only, and it needs pypi to "
             "answer because it uses the script's own `uv pip install` with no local wheel cache.",
    )
    args = parser.parse_args()

    if not args.zip.exists():
        raise SystemExit(f"[ERROR] zip not found: {args.zip} - build it with release/build_release.py first.")

    import tempfile

    sandbox_root = Path(tempfile.mkdtemp(prefix="simulate-"))
    home = sandbox_root / "home"
    home.mkdir(parents=True)
    pkg = sandbox_root / "pkg"
    with zipfile.ZipFile(args.zip) as archive:
        archive.extractall(pkg)
    log(f"sandbox: {sandbox_root}")

    env = dict(os.environ)
    env.update({"USERPROFILE": str(home), "HOME": str(home)})
    # Keep uv's caches inside release/tests/.cache: repeat runs are fast and
    # nothing leaks into the developer's real profile.
    cache_root = Path(__file__).resolve().parent / ".cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    env.update({
        "UV_CACHE_DIR": str(cache_root / "uv-cache"),
        "UV_PYTHON_INSTALL_DIR": str(cache_root / "python"),
    })

    # setup.bat unpacks uv into %TEMP%\uvunpack. Point TEMP at the sandbox: the developer's real
    # %TEMP% must not be written to, and a stale directory there can make the installer hang.
    sandbox_temp = sandbox_root / "temp"
    sandbox_temp.mkdir(parents=True, exist_ok=True)
    setup_bat_env = dict(env)
    setup_bat_env.update({
        "TEMP": str(sandbox_temp),
        "TMP": str(sandbox_temp),
        # The shipped script calls plain `uv pip install`, so the wheel cache has to arrive
        # through the environment (see the note on antlr4 below).
        "UV_FIND_LINKS": str(Path(__file__).resolve().parent / "wheels"),
        # setup_engine.py reads this before it would prompt, so the rehearsal never blocks on
        # the interactive key prompt.
        "CVS_API_KEY": "simulate-test-key",
    })

    uv = prepare_uv(cache_root)
    venv_python = sandbox_root / "agent-cv-screening" / "venv" / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )

    def run(label: str, cmd: list[str], cwd: Path | None = None, timeout: int = 900,
            pass_marker: str | None = None, *, stdin_devnull: bool = False,
            env_override: dict | None = None) -> str:
        log(f"[..] {label}")
        # `setup.bat` ends with `pause`; without a closed stdin the rehearsal would sit there
        # waiting for a keypress that never comes.
        proc = subprocess.Popen(cmd, cwd=cwd, env=env_override or env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace",
                                stdin=subprocess.DEVNULL if stdin_devnull else None)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Dev-machine quirk (observed 2026-09-25): a step can complete all of
            # its work and still fail to exit - a flaky interpreter-shutdown race
            # on this machine's file-watcher setup. The work is verifiable from
            # the captured output: if the completion marker is present, kill the
            # lingering process tree and continue, so the rehearsal tests the
            # product rather than this machine. Without the marker it is a real
            # failure.
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True)
            else:
                proc.kill()
            out, err = proc.communicate()
            partial = out or ""
            if pass_marker and pass_marker in partial:
                log(f"[WARN] {label}: work completed but the process did not exit;"
                    " killed the lingering tree and continued (dev-machine shutdown race).")
                return partial
            log(partial[-2000:])
            log((err or "")[-2000:])
            check(label, False)
            raise SystemExit(1)
        if proc.returncode != 0:
            log((out or "")[-2000:])
            log((err or "")[-2000:])
            check(label, False)
            raise SystemExit(1)
        return out or ""

    try:
        stamp = json.loads((pkg / "engine" / "version.json").read_text(encoding="utf-8"))
        shipped_profiles = json.loads((pkg / "engine" / "site_profiles.json").read_text(encoding="utf-8"))
        check("zip ships prod as the site default", shipped_profiles.get("default") == "prod")

        if args.setup_bat:
            # The path HR actually takes: setup.bat downloads uv, unpacks it, builds the private
            # Python, installs the requirements, then calls setup_engine.py. This runs the shipped
            # script rather than reimplementing it, so the fetch/unpack steps are covered too -
            # they are the ones that fail on a real machine and the hand-rolled path below never
            # touches them.
            #
            # Two things to know before trusting a failure here. It is the one step that does a
            # real `uv pip install` with no local wheel cache, so it needs pypi to answer (the
            # direct path passes --find-links and can resolve offline). And a run on 2026-10-05
            # reached the venv and then sat in that install for 15 minutes with uv idle and its
            # cache frozen; the same install via the direct path finished in under two minutes.
            # That stall was never attributed - ad-hoc `uv` runs from the shell stalled the same
            # way even with the exact direct-path arguments, so they were not valid controls.
            # Treat a stall here as "retry on a quiet machine" until someone bisects it from
            # inside this rehearsal.
            if os.name != "nt":
                raise SystemExit("[ERROR] --setup-bat only applies to Windows; setup.bat is a .bat file.")
            staged = stage_setup_bat(pkg, sandbox_root / "agent-cv-screening")
            run("setup.bat (the HR installer, end to end)",
                ["cmd", "/c", str(staged)],
                cwd=pkg, timeout=1200, pass_marker="Install complete.",
                stdin_devnull=True, env_override=setup_bat_env)
        else:
            run("uv provisioning Python 3.12", [str(uv), "python", "install", "3.12"])
            run("uv creating the venv", [str(uv), "venv", "--python", "3.12", str(sandbox_root / "agent-cv-screening" / "venv")])
            # antlr4-python3-runtime 4.9.3 is sdist-only; on this development machine
            # its temporary-file cleanup can trip the session's file-protection
            # watcher. A prebuilt wheel shipped in release/tests/wheels makes the
            # simulation deterministic - real HR machines build it from the sdist
            # without issue, so the product flow is unchanged.
            find_links = Path(__file__).resolve().parent / "wheels"
            run("uv installing the pinned requirements",
                [str(uv), "pip", "install", "--python", str(venv_python),
                 "--find-links", str(find_links),
                 "-r", str(staged_requirements(pkg))])
            run("installer (env, expert, marketplace, path rewrite)",
                [str(venv_python), str(pkg / "scripts" / "setup_engine.py"),
                 "--engine-target", str(sandbox_root / "agent-cv-screening"), "--skip-venv",
                 "--api-key", "simulate-test-key", "--version", stamp.get("version", "0.0.0")],
                pass_marker="Install complete.")

        check("venv interpreter exists", venv_python.is_file())
        check("version stamp matches the zip", stamp.get("version") not in ("", "0.0.0"))
        env_text = (sandbox_root / "agent-cv-screening" / ".env").read_text(encoding="utf-8")
        check(".env has the supplied key", "ZAI_API_KEY=simulate-test-key" in env_text)
        check(".env disables the local NER model", "CV_LOCAL_NER_ENABLED=false" in env_text)
        check(".env enables the prod site mode", "JES_SITE_MODE=1" in env_text)
        expert_md = home / ".workbuddy-ai" / "plugins" / "marketplaces" / "my-experts" / "plugins" / "hr-cv-screener" / "agents" / "hr-cv-screener.md"
        check("expert installed for WorkBuddy", expert_md.is_file())
        skill_text = (expert_md.parent.parent / "skills" / "hr-cv-screening" / "SKILL.md").read_text(encoding="utf-8")
        check("expert skill paths rewritten to the engine dir", "C:/agent-cv-screening" not in skill_text)

        jd_output = run("engine smoke test (rule-mode JD parse)",
                        [str(venv_python), str(sandbox_root / "agent-cv-screening" / ".codex" / "skills" / "jd-parser" / "scripts" / "run_jd_parse.py"),
                         "--jd-text", "Requirements: Bachelor degree in Computer Science; programming experience in Python."],
                        cwd=str(sandbox_root / "agent-cv-screening"))
        check("JD parse produced a parse_path", '"parse_path"' in jd_output)

        if args.update:
            log("[..] rehearsing the live updater against github.com ...")
            version_file = sandbox_root / "agent-cv-screening" / "version.json"
            version_file.write_text(json.dumps({"version": "0.0.0", "requirements_sha256": ""}), encoding="utf-8")
            out = run("updater applies the latest release",
                      [str(venv_python), str(sandbox_root / "agent-cv-screening" / "scripts" / "update_engine.py")],
                      cwd=str(sandbox_root / "agent-cv-screening"),
                      pass_marker="updated to version")
            check("updater applied the latest release", "updated to version" in out)
            env_after = (sandbox_root / "agent-cv-screening" / ".env").read_text(encoding="utf-8")
            check("API key survived the update", "ZAI_API_KEY=simulate-test-key" in env_after)
            check("prod site mode survived the update", "JES_SITE_MODE=1" in env_after)
            new_stamp = json.loads(version_file.read_text(encoding="utf-8"))
            check("version stamp advanced to the live release", new_stamp.get("version") not in ("", "0.0.0"))
    except SystemExit:
        if not failures:
            failures.append("a step failed")
    finally:
        if not args.keep:
            shutil.rmtree(sandbox_root, ignore_errors=True)
        else:
            log(f"sandbox kept at: {sandbox_root}")

    print("")
    print("RESULT:", "ALL PASS" if not failures else f"FAILURES: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
