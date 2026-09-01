"""CLI: check whether a JAS job changed since the last check (no report generation)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)
import run_jas_screening as screening  # same-dir URL helpers

from jas_import.fetch import fetch_job_payload
from jas_import.skill import job_payload_from_html
from screening_core.candidate_id import is_jas_refno, refno_from_url
from screening_core.demo_mode import apply_demo_defaults
from screening_core.input_policy import ALLOWED_URL_HOSTS, extra_allowed_hosts_from_env, merge_allowed_hosts
from screening_core.job_state import (
    current_snapshot,
    diff_snapshots,
    has_changes,
    load_job_state,
    now_iso,
    record_check,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2

ASK_REFNO = (
    "Please send the job reference number, or paste the internal job records page link.",
    "請發送崗位參考編號，或貼上內部招聘記錄頁的連結。",
)
ASK_JAS_SESSION = (
    "Please allow access to the internal job records page so the update check can continue.",
    "請允許存取內部招聘記錄頁，以便檢查更新。",
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


# Fetch the job payload via the chosen driver (http or webbridge).
def _fetch_job(records_url: str, args: argparse.Namespace, allowed_hosts: tuple[str, ...]) -> dict:
    if getattr(args, "driver", "http") == "webbridge":
        from webridge_collect.client import WebBridgeClient, WebBridgeError

        browser = WebBridgeClient(
            daemon_url=getattr(args, "daemon_url", "http://127.0.0.1:10086"),
            session=getattr(args, "session", "jes-update-check"),
        )
        browser.navigate(records_url, new_tab=True, group_title="JES update check")
        html = browser.page_html()
        return job_payload_from_html(html, base_url=args.base_url)
    return asyncio.run(
        fetch_job_payload(
            records_url,
            cookie_file=args.cookie_file,
            base_url=args.base_url,
            allowed_hosts=allowed_hosts,
        )
    )


# Build the argparse CLI for the update checker.
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether a JAS job changed since the last check; does not generate reports."
    )
    parser.add_argument("target", nargs="?", default=None, help="Job refno or records URL.")
    parser.add_argument("--refno", default=None, help="Job reference number.")
    parser.add_argument("--records-url", default=None, help="JAS records page URL.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL for CV links and refno URL building (public demo).",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="Extra allowlisted URL host (repeatable).",
    )
    parser.add_argument("--cookie-file", default=None, help="Local Netscape cookies.txt for authenticated fetches.")
    parser.add_argument("--state-dir", default=None, help="Job-state directory (default repo data/jas_state).")
    parser.add_argument("--no-store", action="store_true", help="Report changes without updating stored state.")
    parser.add_argument(
        "--driver",
        choices=("webbridge", "http"),
        default="http",
        help="Collection driver: webbridge uses the live browser session; http fetches directly (default http).",
    )
    parser.add_argument("--session", default="jes-update-check", help="WebBridge session (tab group) name.")
    parser.add_argument("--daemon-url", default="http://127.0.0.1:10086", help="WebBridge daemon URL.")
    args = parser.parse_args()
    apply_demo_defaults(args, repo_root=_bootstrap.REPO_ROOT)

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
    if not records_url:
        records_url = screening.build_records_url_for_refno(refno, args.base_url)

    allowed_hosts = merge_allowed_hosts(ALLOWED_URL_HOSTS, extra_allowed_hosts_from_env(), tuple(args.allow_host))
    try:
        job = _fetch_job(records_url, args, allowed_hosts)
    except Exception as exc:
        if args.driver == "webbridge":
            from webridge_collect.client import WebBridgeError

            if isinstance(exc, WebBridgeError) and exc.reason == "daemon-unreachable":
                return _print_need_input(["jas_session"], list(ASK_WEBRIDGE), detail=str(exc))
        if screening._is_auth_failure(exc):
            return _print_need_input(["jas_session"], list(ASK_JAS_SESSION))
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR

    job_refno = str(job.get("refno") or refno or "job")
    state_dir = Path(args.state_dir) if args.state_dir else (_bootstrap.REPO_ROOT / "data" / "jas_state")
    state = load_job_state(state_dir, job_refno)
    # Prefer the last successful screen snapshot so a failed screening doesn't
    # mask still-pending changes; fall back to the last check when no screen ran.
    previous = state.get("last_screen") or state.get("last_check")
    snapshot = current_snapshot(job)
    first_check = previous is None
    changes = (
        diff_snapshots(previous, snapshot)
        if previous
        else {"jd_changed": False, "added": [], "removed": [], "status_changed": {}}
    )
    changed = has_changes(changes)
    checked_at = now_iso()
    if not args.no_store:
        record_check(
            state_dir,
            job_refno,
            job=job,
            result="changes_found" if changed else "no_change",
            changes=changes,
            at=checked_at,
        )

    payload = {
        "status": "success",
        "tool": "check_updates",
        "refno": job_refno,
        "post_title": (job.get("job") or {}).get("post_title"),
        "candidate_count": len(job.get("candidates", [])),
        "first_check": first_check,
        "checked_at": checked_at,
        "has_changes": changed,
        "last_check_at": (previous or {}).get("at"),
        "changes": changes,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
