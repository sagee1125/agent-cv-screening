"""CLI for jas-import: HR screening by default; parse-list/parse-job/mock for developers.

Passing a folder, records URL, or refno screens the job and writes Desktop reports.
parse-job on an exported folder that already has CVs is also treated as screening,
so WorkBuddy does not stop at JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from jas_import.mock import generate_mock_jas_dir
from jas_import.skill import parse_job_skill, parse_list_skill
from screening_core.hr_output import looks_like_jas_export_dir

DEVELOPER_COMMANDS = {"parse-list", "parse-job", "mock"}
CV_SUFFIXES = {".pdf", ".doc", ".docx"}


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


# True when a folder already has applicant CV files (offline screening is possible).
def _folder_has_cvs(folder: Path) -> bool:
    for name in ("cvs", "uploads"):
        child = folder / name
        if not child.is_dir():
            continue
        if any(path.is_file() and path.suffix.lower() in CV_SUFFIXES for path in child.iterdir()):
            return True
    return False


# Read --html-file from parse-job argv without building a full parser.
def _html_file_arg(argv: list[str]) -> str | None:
    for index, token in enumerate(argv):
        if token == "--html-file" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--html-file="):
            return token.split("=", 1)[1]
    return None


# Screen the export folder instead of JSON-only parse-job when CVs are already there.
def _screening_target_from_parse_job(argv: list[str]) -> str | None:
    html = _html_file_arg(argv)
    if not html:
        return None
    folder = Path(html).expanduser().resolve().parent
    if looks_like_jas_export_dir(folder) and _folder_has_cvs(folder):
        return str(folder)
    return None


# Hand remaining argv to run_jas_screening.py (Desktop HTML/PDF).
def _forward_to_screening(argv: list[str]) -> int:
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import run_jas_screening

    saved = sys.argv
    try:
        sys.argv = [str(script_dir / "run_jas_screening.py"), *argv]
        return run_jas_screening.main()
    finally:
        sys.argv = saved


# Developer-only subcommands: parse-list, parse-job (JSON), mock.
def _developer_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Parse PolyU JAS records HTML files (developer).")
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

    args = parser.parse_args(argv)
    return args.func(args)


# HR default: a folder/URL/refno screens; developer subcommands stay available.
def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "parse-job":
        folder = _screening_target_from_parse_job(argv)
        if folder:
            return _forward_to_screening([folder])
    if argv and argv[0] in DEVELOPER_COMMANDS:
        return _developer_main(argv)
    return _forward_to_screening(argv)


if __name__ == "__main__":
    raise SystemExit(main())
