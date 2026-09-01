"""CLI: single WorkBuddy tool entry point that runs a skill and projects stdout through host-envelope.

WorkBuddy (or any chat host) must call this script instead of skill CLIs directly.
It runs the underlying skill, captures stdout, and projects it through the
host-envelope whitelist so only HostToolReturn JSON reaches the host LLM.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from host_envelope.project import project_host_return, rejected_envelope

REPO_ROOT = _bootstrap.REPO_ROOT
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PYTHON = sys.executable

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2


# Returns True when the target string looks like a URL rather than a local path.
def _looks_like_url(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith(("http://", "https://", "www.")) or "records.php" in text or "records.html" in text


# Returns the skill CLI script path for a given tool name.
def _skill_script(skill: str, script: str) -> Path:
    path = SKILLS_DIR / skill / "scripts" / script
    if not path.is_file():
        raise RuntimeError(f"skill script not found: {path}")
    return path


# Runs a subprocess, captures stdout JSON, and returns the parsed payload.
def _run_skill(cmd: list[str]) -> tuple[int, dict[str, Any]]:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    raw = proc.stdout.strip() or proc.stderr.strip()
    if not raw:
        return proc.returncode, {"status": "error", "error_message": "skill returned no output"}
    try:
        return proc.returncode, json.loads(raw)
    except json.JSONDecodeError:
        return proc.returncode, {"status": "error", "error_message": raw[:300]}


# Tries to read the pipeline manifest from the output directory for ranking data.
def _read_pipeline_manifest(skill_stdout: dict[str, Any]) -> dict[str, Any]:
    hr_files = skill_stdout.get("hr_files") or ""
    if not hr_files:
        return {}
    desktop = Path.home() / "Desktop"
    if hr_files.startswith("Desktop/"):
        manifest_path = desktop / hr_files[len("Desktop/"):] / "_pipeline" / "manifest.json"
    else:
        manifest_path = Path(hr_files) / "_pipeline" / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# Reports whether JAS access was available for a run: both the browser session
# (webbridge) and the cookie jar (http) count as granted, so the only reliable signal
# of a real problem is the skill asking for a JAS session itself.
def _jas_session(payload: dict[str, Any]) -> str:
    if payload.get("status") != "need_input":
        return "granted"
    ask = payload.get("ask") if isinstance(payload.get("ask"), dict) else {}
    missing = payload.get("missing") or ask.get("missing") or []
    return "missing" if "jas_session" in missing else "granted"


# Tries to read the JAS manifest for HR status mapping.
def _read_jas_manifest(skill_stdout: dict[str, Any]) -> dict[str, Any]:
    hr_files = skill_stdout.get("hr_files") or ""
    if not hr_files:
        return {}
    desktop = Path.home() / "Desktop"
    if hr_files.startswith("Desktop/"):
        manifest_path = desktop / hr_files[len("Desktop/"):] / "_pipeline" / "jas-manifest.json"
    else:
        manifest_path = Path(hr_files) / "_pipeline" / "jas-manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# Runs the screen_refno tool: webridge-collect for refno/URL, jas-import for folder.
def _run_screen_refno(args: argparse.Namespace) -> int:
    target = args.target or ""
    # URLs must be routed to WebBridge, never misdetected as folders (URLs contain /).
    is_url = _looks_like_url(target)
    looks_like_folder = not is_url and (("\\" in target or Path(target).exists()))
    if looks_like_folder and not args.refno:
        script = _skill_script("jas-import", "run_jas_import.py")
        cmd = [PYTHON, str(script), target]
    else:
        script = _skill_script("webridge-collect", "run_webridge_collect.py")
        cmd = [PYTHON, str(script), target or args.refno, "--driver", args.driver]
        if args.no_open:
            cmd.append("--no-open")
    exit_code, payload = _run_skill(cmd)
    pipeline_manifest = _read_pipeline_manifest(payload)
    jas_manifest = _read_jas_manifest(payload)
    # Prefer the pipeline manifest (has candidates[] with ranking) for projection;
    # fall back to the skill stdout when no manifest was found.
    projection_input = pipeline_manifest if pipeline_manifest.get("candidates") else payload
    envelope = project_host_return(
        tool="screen_refno",
        payload=projection_input,
        jas_manifest=jas_manifest or None,
        jas_session="granted" if looks_like_folder else _jas_session(payload),
        cookie_file_present=False,
    )
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    if envelope["status"] == "need_input":
        return EXIT_NEED_INPUT
    if envelope["status"] == "error":
        return EXIT_ERROR
    return EXIT_OK


# Runs the check_updates tool and projects the output.
def _run_check_updates(args: argparse.Namespace) -> int:
    script = _skill_script("jas-import", "check_updates.py")
    cmd = [PYTHON, str(script)]
    if args.target:
        cmd.append(args.target)
    if args.driver == "webbridge":
        cmd += ["--driver", "webbridge"]
    exit_code, payload = _run_skill(cmd)
    envelope = project_host_return(
        tool="check_updates",
        payload=payload,
        jas_session=_jas_session(payload),
    )
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    if envelope["status"] == "need_input":
        return EXIT_NEED_INPUT
    if envelope["status"] == "error":
        return EXIT_ERROR
    return EXIT_OK


# Returns the request_jas_access envelope without running any skill.
def _run_request_jas_access(args: argparse.Namespace) -> int:
    envelope = project_host_return(
        tool="request_jas_access",
        jas_session=args.jas_session or "missing",
        cookie_file_present=args.cookie_file_present,
    )
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return EXIT_NEED_INPUT if envelope["status"] == "need_input" else EXIT_OK


# Builds the argparse CLI for the WorkBuddy tool wrapper.
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Single WorkBuddy entry point: runs a skill and projects stdout through the host-envelope whitelist."
    )
    subparsers = parser.add_subparsers(dest="tool", required=True)

    screen_parser = subparsers.add_parser("screen_refno", help="Screen a job by refno, URL, or folder.")
    screen_parser.add_argument("target", nargs="?", default=None, help="Refno, records URL, or folder path.")
    screen_parser.add_argument("--refno", default=None, help="Job reference number.")
    screen_parser.add_argument(
        "--driver",
        choices=("webbridge", "http"),
        default="webbridge",
        help="Collection driver (default webbridge for visible human flow).",
    )
    screen_parser.add_argument("--no-open", action="store_true", help="Do not open ranking-overview.html.")
    screen_parser.set_defaults(func=_run_screen_refno)

    check_parser = subparsers.add_parser("check_updates", help="Check whether a job changed since the last screen.")
    check_parser.add_argument("target", nargs="?", default=None, help="Refno or records URL.")
    check_parser.add_argument(
        "--driver",
        choices=("webbridge", "http"),
        default="webbridge",
        help="Collection driver (default webbridge, same as screening).",
    )
    check_parser.set_defaults(func=_run_check_updates)

    access_parser = subparsers.add_parser("request_jas_access", help="Return the JAS session auth envelope.")
    access_parser.add_argument(
        "--jas-session",
        choices=("missing", "granted", "denied", "expired"),
        default="missing",
        help="Local JAS session state.",
    )
    access_parser.add_argument("--cookie-file-present", action="store_true", help="Set cookie_file_present true.")
    access_parser.set_defaults(func=_run_request_jas_access)

    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        envelope = rejected_envelope(args.tool, str(exc))
        print(json.dumps(envelope, ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
