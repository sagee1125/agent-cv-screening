# CLI entry point for the CV Parser skill (agent-facing).
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before skill imports)

from cv_parser.skill import parse_cv_skill


# Runs parse_cv_skill for one file and optional JD context.
async def _run(file_path: str, jd_text: str | None) -> dict:
    return await parse_cv_skill(file_path=file_path, jd_text=jd_text)


# Parses CLI flags, runs the skill, and writes JSON to a file or stdout.
def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a CV PDF into structured candidate data.")
    parser.add_argument("--file", required=True, help="Path to the CV PDF file.")
    parser.add_argument("--jd-file", default=None, help="Optional path to a JD text file used as parse context.")
    parser.add_argument("--jd-text", default=None, help="Optional inline JD text used as parse context.")
    parser.add_argument("--output", default=None, help="Optional path to write the JSON result (default: stdout).")
    args = parser.parse_args()

    jd_text = args.jd_text
    if args.jd_file:
        jd_text = Path(args.jd_file).read_text(encoding="utf-8-sig")

    try:
        result = asyncio.run(_run(args.file, jd_text))
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
