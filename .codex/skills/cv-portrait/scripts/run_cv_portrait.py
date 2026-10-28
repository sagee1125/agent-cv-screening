# CLI entry point for the CV Portrait skill (agent-facing).
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (puts this skill's and reused skills' src on sys.path)

from cv_portrait.service import PORTRAIT_CACHE_VERSION, build_portrait_service


# Builds one portrait and writes the JSON artifact (with resume stamp).
def main() -> int:
    parser = argparse.ArgumentParser(description="Build a JD-independent capability portrait for one CV.")
    parser.add_argument("--file", required=True, help="Path to the CV (PDF or Word, any extension).")
    parser.add_argument("--output", required=True, help="Target JSON path.")
    parser.add_argument(
        "--converted-pdf",
        default=None,
        help="Reuse this converted PDF when it exists instead of re-converting Word input.",
    )
    args = parser.parse_args()

    service = build_portrait_service()
    try:
        result = asyncio.run(service.build_portrait(args.file, converted_pdf=args.converted_pdf))
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    result["portrait_logic"] = PORTRAIT_CACHE_VERSION
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    Path(args.output).write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
