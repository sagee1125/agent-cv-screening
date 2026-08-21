"""CLI entry point for the CV Parser skill (agent-facing).

Example (from repository root):
    python .codex/skills/cv-parser/scripts/run_cv_parse.py --file data/resume.pdf --jd-file jd.txt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from app.skills.cv_parse import parse_cv_skill


async def _run(file_path: str, jd_text: str | None) -> dict:
    return await parse_cv_skill(file_path=file_path, jd_text=jd_text)


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
