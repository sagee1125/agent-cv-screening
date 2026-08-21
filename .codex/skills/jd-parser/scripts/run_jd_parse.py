"""CLI entry point for the JD Parser skill (agent-facing).

Example (from repository root):
    python .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-file jd.txt
    python .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-text "Requirements: Python, SQL"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from app.skills.jd_parse import parse_jd_skill


async def _run(jd_text: str) -> dict:
    return await parse_jd_skill(jd_text=jd_text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a JD into structured skill/requirement data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--jd-file", default=None, help="Path to a JD text file.")
    group.add_argument("--jd-text", default=None, help="Inline JD text.")
    parser.add_argument("--output", default=None, help="Optional path to write the JSON result (default: stdout).")
    args = parser.parse_args()

    jd_text = args.jd_text or Path(args.jd_file).read_text(encoding="utf-8-sig")

    try:
        result = asyncio.run(_run(jd_text))
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
