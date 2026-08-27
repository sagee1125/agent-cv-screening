"""CLI entry point for the report-gen skill (agent-facing).

Subcommands:
    candidate    Generate a one-page PDF report for a scored candidate.
    comparison   Generate an Excel comparison report for ranked candidates.

Example (from repository root):
    python .codex/skills/report-gen/scripts/run_report.py candidate --extracted extracted.json --score score.json --position "Backend Engineer" --output report.pdf
    python .codex/skills/report-gen/scripts/run_report.py candidate --extracted extracted.json --detail detail.json --position "Assistant Facilities Officer" --output report.pdf
    python .codex/skills/report-gen/scripts/run_report.py comparison --position "Backend Engineer" --rows rows.json --output comparison.xlsx
    python .codex/skills/report-gen/scripts/run_report.py board --position "Backend Engineer" --rows rows.json --output screening-board.html
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from report_gen.skill import (
    generate_candidate_match_html_skill,
    generate_candidate_report_skill,
    generate_comparison_report_skill,
    generate_screening_board_skill,
)


# Load a JSON file (BOM-tolerant) into a dict or list.
def _read_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# Generate a one-page PDF report for one scored candidate (optionally with matching detail).
def _run_candidate(args: argparse.Namespace) -> int:
    try:
        if not args.score and not args.detail:
            raise ValueError("at least one of --score or --detail is required")
        extracted = _read_json(args.extracted)
        score = _read_json(args.score) if args.score else None
        detail = _read_json(args.detail) if args.detail else None
        result = generate_candidate_report_skill(
            extracted_data=extracted,
            score_result=score,
            position_name=args.position,
            candidate_name=None,
            refno=args.refno,
            appno=args.appno,
            rank=args.rank,
            output_path=args.output,
            detail_result=detail,
        )
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# Generate an Excel comparison report from ranked candidate rows.
def _run_comparison(args: argparse.Namespace) -> int:
    try:
        rows = _read_json(args.rows)
        if not isinstance(rows, list):
            raise ValueError("--rows must contain a JSON array of candidate rows")
        result = generate_comparison_report_skill(
            position_name=args.position,
            rows=rows,
            output_path=args.output,
        )
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# Generate a local HTML ranking + radar board for HR.
def _run_board(args: argparse.Namespace) -> int:
    try:
        rows = _read_json(args.rows)
        if not isinstance(rows, list):
            raise ValueError("--rows must contain a JSON array of candidate rows")
        result = generate_screening_board_skill(
            position_name=args.position,
            rows=rows,
            output_path=args.output,
            refno=args.refno,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# Generate one candidate HTML match page from a single-row JSON object or array.
def _run_match_html(args: argparse.Namespace) -> int:
    try:
        payload = _read_json(args.row)
        if isinstance(payload, list):
            if len(payload) != 1:
                raise ValueError("--row must be one candidate object or a one-item array")
            row = payload[0]
        elif isinstance(payload, dict):
            row = payload
        else:
            raise ValueError("--row must contain a JSON object")
        result = generate_candidate_match_html_skill(
            position_name=args.position,
            row=row,
            output_path=args.output,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# Build the argparse CLI with candidate and comparison subcommands.
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate candidate PDF or Excel comparison reports.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    candidate_parser = subparsers.add_parser("candidate", help="Generate a one-page PDF report for a scored candidate.")
    candidate_parser.add_argument("--extracted", required=True, help="Path to JSON file with CV Parser structured_data.")
    candidate_parser.add_argument("--score", default=None, help="Path to JSON file with scorer output (optional when --detail is given).")
    candidate_parser.add_argument("--detail", default=None, help="Optional path to matching detail JSON (radar_dimensions, interview_questions, eligibility).")
    candidate_parser.add_argument("--position", required=True, help="Job position name shown on the report.")
    candidate_parser.add_argument("--refno", default=None, help="Job reference number shown on the report (never a personal name).")
    candidate_parser.add_argument("--appno", default=None, help="Application number shown on the report (never a personal name).")
    candidate_parser.add_argument("--name", default=None, help="Ignored; reports never display candidate names.")
    candidate_parser.add_argument("--rank", type=int, default=0, help="Optional candidate rank shown on the report.")
    candidate_parser.add_argument("--output", required=True, help="Path to write the PDF report file.")
    candidate_parser.set_defaults(func=_run_candidate)

    comparison_parser = subparsers.add_parser("comparison", help="Generate an Excel comparison report for ranked candidates.")
    comparison_parser.add_argument("--position", required=True, help="Job position name shown on the report.")
    comparison_parser.add_argument("--rows", required=True, help="Path to JSON file with a list of candidate rows.")
    comparison_parser.add_argument("--output", required=True, help="Path to write the XLSX report file.")
    comparison_parser.set_defaults(func=_run_comparison)

    board_parser = subparsers.add_parser("board", help="Generate an HTML ranking + radar board for HR.")
    board_parser.add_argument("--position", required=True, help="Job position name shown on the board.")
    board_parser.add_argument("--rows", required=True, help="Path to JSON file with a list of candidate rows.")
    board_parser.add_argument("--refno", default=None, help="Optional job reference number shown in the heading.")
    board_parser.add_argument("--output", required=True, help="Path to write the HTML file.")
    board_parser.set_defaults(func=_run_board)

    match_html_parser = subparsers.add_parser("match-html", help="Generate one candidate HTML match page.")
    match_html_parser.add_argument("--position", required=True, help="Job position name shown on the page.")
    match_html_parser.add_argument("--row", required=True, help="JSON file with one candidate row object.")
    match_html_parser.add_argument("--output", required=True, help="Path to write the HTML file (use <appno>.html).")
    match_html_parser.set_defaults(func=_run_match_html)
    return parser


# Parse argv and dispatch to the selected subcommand.
def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
