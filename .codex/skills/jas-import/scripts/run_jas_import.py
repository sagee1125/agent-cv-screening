"""CLI entry point for the jas-import skill (agent-facing).

Subcommands:
    parse-list   Parse a JAS records list HTML file into a job catalog.
    parse-job    Parse a JAS records job-detail HTML file into JD text and candidate refs.

Example (from repository root):
    python .codex/skills/jas-import/scripts/run_jas_import.py parse-list --html-file list.html
    python .codex/skills/jas-import/scripts/run_jas_import.py parse-job --html-file records.html --output job.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from jas_import.skill import parse_job_skill, parse_list_skill
from jas_import.mock import generate_mock_jas_dir


# Write the JSON payload to --output or print it to stdout.
def _emit(payload: str, output: str | None) -> None:
    if output:
        Path(output).write_text(payload, encoding="utf-8")
    else:
        print(payload)


# Parse a JAS list HTML file and emit a catalog JSON payload.
def _run_parse_list(args: argparse.Namespace) -> int:
    try:
        result = parse_list_skill(args.html_file, base_url=args.base_url)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _emit(json.dumps(result, ensure_ascii=False, indent=2), args.output)
    return 0


# Parse a JAS job-detail HTML file and emit JD text plus candidate refs.
def _run_parse_job(args: argparse.Namespace) -> int:
    try:
        result = parse_job_skill(args.html_file, base_url=args.base_url)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _emit(json.dumps(result, ensure_ascii=False, indent=2), args.output)
    return 0


# Generate synthetic JAS mock data for end-to-end testing.
def _run_mock(args: argparse.Namespace) -> int:
    try:
        out_dir = generate_mock_jas_dir(args.output_dir)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    payload = json.dumps({"status": "success", "source": "jas-mock", "output_dir": str(out_dir)}, ensure_ascii=False, indent=2)
    _emit(payload, args.output)
    return 0


# Build the argparse CLI and dispatch subcommands.
def main() -> int:
    parser = argparse.ArgumentParser(description="Parse PolyU JAS records HTML files.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("parse-list", help="Parse the JAS records list page.")
    list_parser.add_argument("--html-file", required=True, help="Path to the saved records.php list HTML.")
    list_parser.add_argument("--base-url", default=None, help="Base URL for joining relative hrefs.")
    list_parser.add_argument("--output", default=None, help="Optional output JSON file.")
    list_parser.set_defaults(func=_run_parse_list)

    job_parser = sub.add_parser("parse-job", help="Parse a JAS records job-detail page.")
    job_parser.add_argument("--html-file", required=True, help="Path to the saved records.php?refno=... HTML.")
    job_parser.add_argument("--base-url", default=None, help="Base URL for joining relative hrefs.")
    job_parser.add_argument("--output", default=None, help="Optional output JSON file.")
    job_parser.set_defaults(func=_run_parse_job)

    mock_parser = sub.add_parser("mock", help="Generate synthetic JAS mock data for testing.")
    mock_parser.add_argument("--output-dir", required=True, help="Directory to write mock JAS data (records.html + cvs/).")
    mock_parser.add_argument("--output", default=None, help="Optional output JSON file.")
    mock_parser.set_defaults(func=_run_mock)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())