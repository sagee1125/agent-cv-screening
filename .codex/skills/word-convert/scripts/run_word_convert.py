# CLI entry point for the Word Convert skill (agent-facing).
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (puts this skill's src package on sys.path)

from word_convert.converter import convert_to_pdf


# Converts one Word file to PDF and reports the result as JSON.
def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a Word CV (.doc/.docx) into a local PDF.")
    parser.add_argument("--file", required=True, help="Path to the Word document (any extension).")
    parser.add_argument("--output", default=None, help="Target PDF path (default: beside the source).")
    args = parser.parse_args()

    source = Path(args.file)
    target = Path(args.output) if args.output else source.with_suffix(".pdf")
    try:
        output, backend = convert_to_pdf(source, target)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {"status": "success", "output": str(output), "backend": backend},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
