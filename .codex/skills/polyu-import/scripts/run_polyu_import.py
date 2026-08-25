"""CLI entry point for the polyu-import skill (agent-facing).

Subcommands:
    catalog           Fetch the PolyU job catalog.
    fetch             Fetch one PolyU job detail page as JD text.
    fetch-and-parse   Fetch one PolyU job and parse its JD.

Example (from repository root):
    python .codex/skills/polyu-import/scripts/run_polyu_import.py catalog --output catalog.json
    python .codex/skills/polyu-import/scripts/run_polyu_import.py fetch --external-ref 260818008-IE --output job.json
    python .codex/skills/polyu-import/scripts/run_polyu_import.py fetch-and-parse --external-ref 260818008-IE --output result.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from polyu_import.skill import (
    fetch_and_parse_polyu_job_skill,
    fetch_polyu_job_skill,
    list_polyu_catalog_skill,
)


# Write the JSON payload to --output or print it to stdout.
def _emit(payload: str, output: str | None) -> None:
    if output:
        Path(output).write_text(payload, encoding="utf-8")
    else:
        print(payload)


# Fetch the PolyU job catalog and emit the JSON-serializable result.
def _run_catalog(args: argparse.Namespace) -> int:
    try:
        result = asyncio.run(list_polyu_catalog_skill())
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _emit(json.dumps(result, ensure_ascii=False, indent=2), args.output)
    return 0


# Fetch one PolyU job detail page and emit JD text plus metadata.
def _run_fetch(args: argparse.Namespace) -> int:
    try:
        if not args.external_ref and not args.detail_url:
            raise ValueError("missing input: provide --external-ref or --detail-url")
        result = asyncio.run(
            fetch_polyu_job_skill(
                external_ref=args.external_ref,
                detail_url=args.detail_url,
                job_code=args.job_code,
                title=args.title,
                department=args.department,
            )
        )
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _emit(json.dumps(result, ensure_ascii=False, indent=2), args.output)
    return 0


# Fetch one PolyU job and parse its JD, then emit the combined result.
def _run_fetch_and_parse(args: argparse.Namespace) -> int:
    try:
        result = asyncio.run(
            fetch_and_parse_polyu_job_skill(
                external_ref=args.external_ref,
                detail_url=args.detail_url,
                mode=args.mode,
            )
        )
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _emit(json.dumps(result, ensure_ascii=False, indent=2), args.output)
    return 0


# Build the argparse CLI with catalog, fetch, and fetch-and-parse subcommands.
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch PolyU job listings and detail pages as JD text.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog_parser = subparsers.add_parser("catalog", help="Fetch the PolyU job catalog.")
    catalog_parser.add_argument("--output", default=None, help="Optional path to write the JSON result (default: stdout).")
    catalog_parser.set_defaults(func=_run_catalog)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch one PolyU job detail page as JD text.")
    fetch_parser.add_argument("--external-ref", default=None, help="PolyU Ref. No. to look up in the catalog.")
    fetch_parser.add_argument("--detail-url", default=None, help="Direct job_detail.php URL (fallback when external-ref is not in the catalog).")
    fetch_parser.add_argument("--job-code", default=None, help="Optional job code for a minimal listing built from --detail-url.")
    fetch_parser.add_argument("--title", default="", help="Optional title for a minimal listing built from --detail-url.")
    fetch_parser.add_argument("--department", default="", help="Optional department for a minimal listing built from --detail-url.")
    fetch_parser.add_argument("--output", default=None, help="Optional path to write the JSON result (default: stdout).")
    fetch_parser.set_defaults(func=_run_fetch)

    parse_parser = subparsers.add_parser("fetch-and-parse", help="Fetch one PolyU job and parse its JD.")
    ref_group = parse_parser.add_mutually_exclusive_group(required=True)
    ref_group.add_argument("--external-ref", default=None, help="PolyU Ref. No. to look up in the catalog.")
    ref_group.add_argument("--detail-url", default=None, help="Direct job_detail.php URL.")
    parse_parser.add_argument("--mode", choices=["rule", "hybrid", "qwen"], default="rule", help="JD parse mode. The skill CLI always uses rule; hybrid/qwen are REST-only.")
    parse_parser.add_argument("--output", default=None, help="Optional path to write the JSON result (default: stdout).")
    parse_parser.set_defaults(func=_run_fetch_and_parse)
    return parser


# Parse argv and dispatch to the selected subcommand.
def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
