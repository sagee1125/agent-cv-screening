"""CLI for webridge-collect: gather records.html + CVs, then run the JAS pipeline.

Input is a job reference number or a records URL. The WebBridge driver drives the
user's real browser (with its login session) like a human; the http driver fetches
public demo pages directly without a browser. Collected files are written to
<collect-dir>/<refno>/ and the existing jas-import pipeline turns them into
Desktop HTML/PDF reports.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from screening_core.candidate_id import is_jas_refno, refno_from_url
from screening_core.hr_output import HR_PACK_FOLDER
from screening_core.input_policy import ALLOWED_URL_HOSTS, extra_allowed_hosts_from_env, merge_allowed_hosts
from webridge_collect.client import WebBridgeClient, WebBridgeError
from webridge_collect.collect import COLLECT_ROOT_NAME, build_records_url, collect_job

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2

ASK_REFNO = (
    "Please send the job reference number, or paste the internal job records page link.",
    "請發送崗位參考編號，或貼上內部招聘記錄頁的連結。",
)
ASK_WEBRIDGE = (
    "Please start Kimi WebBridge (or rerun with --driver http for the public demo).",
    "請啟動 Kimi WebBridge（公開 demo 可直接改用 --driver http）。",
)


# Print a host-projectable need_input envelope and return exit code 2.
def _print_need_input(missing: list[str], questions: list[str], **extra: object) -> int:
    payload = {
        "status": "need_input",
        "missing": missing,
        "questions": questions,
        "ask": {"missing": missing, "questions": questions},
        **extra,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return EXIT_NEED_INPUT


# Print a PII-free envelope; errors go to stderr.
def _emit(payload: dict, *, to_stderr: bool = False) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    (sys.stderr if to_stderr else sys.stdout).write(text + "\n")
    return EXIT_ERROR if to_stderr else EXIT_OK


# Resolve the records URL from a refno, URL, or the demo --base-url.
def _resolve_records_url(refno: str | None, records_url: str | None, base_url: str | None) -> str | None:
    if records_url:
        return records_url
    if refno and is_jas_refno(refno):
        return build_records_url(refno, base_url)
    return None


# Run the existing jas-import pipeline on the collected folder.
def run_pipeline(folder: Path, *, report_dir: str | None, engine: str, no_open: bool, skip_reports: bool) -> tuple[int, dict]:
    script = _bootstrap.REPO_ROOT / ".codex" / "skills" / "jas-import" / "scripts" / "run_jas_import.py"
    cmd = [sys.executable, str(script), str(folder)]
    if report_dir:
        cmd += ["--output-dir", report_dir]
    if engine:
        cmd += ["--engine", engine]
    if no_open:
        cmd += ["--no-open"]
    if skip_reports:
        cmd += ["--skip-reports"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    raw = proc.stdout.strip() or proc.stderr.strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"status": "error", "error_message": raw[:300] if raw else "pipeline returned no output"}
    return proc.returncode, payload


# Build the argparse CLI for webridge-collect.
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect one JAS job (records.html + CVs) via WebBridge or HTTP, then run the screening pipeline."
    )
    parser.add_argument("target", nargs="?", default=None, help="Job refno or records URL.")
    parser.add_argument("--refno", default=None, help="Job reference number.")
    parser.add_argument("--records-url", default=None, help="JAS records page URL.")
    parser.add_argument("--driver", choices=("webbridge", "http"), default="webbridge", help="Collection driver (default webbridge).")
    parser.add_argument("--session", default="jes-demo-screen", help="WebBridge session (tab group) name.")
    parser.add_argument("--daemon-url", default="http://127.0.0.1:10086", help="WebBridge daemon URL.")
    parser.add_argument("--base-url", default=None, help="Base URL for CV links and refno URL building (public demo).")
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST", help="Extra allowlisted URL host (repeatable).")
    parser.add_argument("--cookie-file", default=None, help="Local Netscape cookies.txt for authenticated HTTP fetches.")
    parser.add_argument("--collect-dir", default=None, help="Parent folder for collected files (default repo data/jes_webridge).")
    parser.add_argument("--no-pipeline", action="store_true", help="Collect only; do not run the screening pipeline.")
    parser.add_argument("--report-dir", default=None, help="Pipeline output parent (default Desktop/workbuddy-cv-screen).")
    parser.add_argument("--engine", choices=("legacy", "matching"), default="matching", help="Scoring engine.")
    parser.add_argument("--no-open", action="store_true", help="Do not open ranking-overview.html after the run.")
    parser.add_argument("--skip-reports", action="store_true", help="Skip HTML/PDF/Excel generation (testing only).")
    parser.add_argument("--cleanup", action="store_true", help="Delete the collected folder after a successful pipeline run.")
    args = parser.parse_args()

    refno = args.refno
    records_url = args.records_url
    if args.target:
        if is_jas_refno(args.target):
            refno = args.target.strip()
        else:
            records_url = args.target
    if records_url and not refno:
        refno = refno_from_url(records_url)
    if not refno and not records_url:
        return _print_need_input(["refno"], list(ASK_REFNO))
    records_url = _resolve_records_url(refno, records_url, args.base_url)
    if not records_url:
        return _print_need_input(["refno"], list(ASK_REFNO))

    allowed_hosts = merge_allowed_hosts(ALLOWED_URL_HOSTS, extra_allowed_hosts_from_env(), tuple(args.allow_host))
    collect_root = Path(args.collect_dir) if args.collect_dir else (_bootstrap.REPO_ROOT / "data" / COLLECT_ROOT_NAME)
    folder = collect_root / (refno or "job")

    client = None
    if args.driver == "webbridge":
        client = WebBridgeClient(daemon_url=args.daemon_url, session=args.session)

    try:
        manifest = collect_job(
            records_url=records_url,
            folder=folder,
            driver=args.driver,
            base_url=args.base_url,
            allowed_hosts=allowed_hosts,
            cookie_file=args.cookie_file,
            client=client,
        )
    except WebBridgeError as exc:
        if exc.reason == "daemon-unreachable":
            return _print_need_input(["jas_session"], list(ASK_WEBRIDGE), detail=str(exc))
        return _emit({"status": "error", "error_message": str(exc)}, to_stderr=True)
    except Exception as exc:
        return _emit({"status": "error", "error_message": str(exc)}, to_stderr=True)

    result: dict = {
        "status": "success",
        "source": "webridge-collect",
        "driver": args.driver,
        "refno": manifest.get("refno", refno),
        "post_title": manifest.get("post_title"),
        "candidate_count": len(manifest.get("candidates", [])),
        "cv_downloaded": len(manifest.get("cv_downloaded", [])),
        "candidates_without_cv": manifest.get("candidates_without_cv", []),
        "folder": str(folder),
    }
    if manifest.get("download_failures"):
        result["download_failures"] = manifest["download_failures"]
        if not result["cv_downloaded"]:
            result["status"] = "error"
            return _emit(result, to_stderr=True)
        result["status"] = "partial_success"

    if not args.no_pipeline:
        exit_code, pipeline_payload = run_pipeline(
            folder,
            report_dir=args.report_dir,
            engine=args.engine,
            no_open=args.no_open,
            skip_reports=args.skip_reports,
        )
        result["pipeline_status"] = pipeline_payload.get("status")
        if "hr_files" in pipeline_payload:
            result["hr_files"] = pipeline_payload["hr_files"]
        elif args.report_dir:
            result["hr_files"] = str(Path(args.report_dir) / (refno or "job"))
        else:
            result["hr_files"] = f"Desktop/{HR_PACK_FOLDER}/{refno or 'job'}"
        if exit_code != 0:
            result["status"] = "error"
            result["error_message"] = pipeline_payload.get("error_message") or f"pipeline exited {exit_code}"
            return _emit(result, to_stderr=True)
        if args.cleanup and folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            result["folder"] = "(cleaned)"

    return _emit(result)


if __name__ == "__main__":
    raise SystemExit(main())
