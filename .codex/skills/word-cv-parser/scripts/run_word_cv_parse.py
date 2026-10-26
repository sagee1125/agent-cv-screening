# CLI entry point for the Word CV Parser skill: convert locally, then run the
# shared cv-parser core so the output JSON is byte-for-byte the same format.
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (puts word-convert's src on sys.path)

from word_convert.converter import convert_to_pdf


# Locates a sibling skill's CLI script by walking up to the skills root.
def _find_skill_script(skill: str, script: str) -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".codex" / "skills" / skill / "scripts" / script
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"Could not locate skill script: {skill}/{script}")


# Converts the Word submission locally, then parses it with the cv-parser CLI.
def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a Word CV into structured candidate data.")
    parser.add_argument("--file", required=True, help="Path to the Word CV (any extension).")
    parser.add_argument("--output", required=True, help="Target JSON path (cv-parser format).")
    parser.add_argument("--jd-file", default=None, help="Optional JD context forwarded to the parser.")
    parser.add_argument("--jd-text", default=None, help="Optional inline JD text forwarded to the parser.")
    parser.add_argument(
        "--converted-pdf",
        default=None,
        help="Reuse this converted PDF when it exists instead of re-converting.",
    )
    args = parser.parse_args()

    source = Path(args.file)
    output = Path(args.output)
    reused = args.converted_pdf and Path(args.converted_pdf).is_file()
    if reused:
        pdf_path = Path(args.converted_pdf)
    else:
        pdf_path = Path(args.converted_pdf) if args.converted_pdf else output.with_name(
            f"{output.stem}-converted.pdf"
        )
        try:
            convert_to_pdf(source, pdf_path)
        except Exception as exc:
            print(
                json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False),
                file=sys.stderr,
            )
            return 1

    cmd = [sys.executable, str(_find_skill_script("cv-parser", "run_cv_parse.py")), "--file", str(pdf_path), "--output", str(output)]
    if args.jd_file:
        cmd += ["--jd-file", args.jd_file]
    if args.jd_text:
        cmd += ["--jd-text", args.jd_text]
    env_extra = {"PYTHONIOENCODING": "utf-8"}
    import os

    env = dict(os.environ, **env_extra)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
