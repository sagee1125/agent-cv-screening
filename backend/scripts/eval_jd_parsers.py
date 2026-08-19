# Evaluates JD parser modes (rule / hybrid / qwen) over sample JDs and writes a comparison JSON.
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.skills.jd_parse import parse_jd_skill  # noqa: E402
from app.services.jd_parser.providers.qwen import QwenJDExtractorProvider  # noqa: E402

DEFAULT_SAMPLES = [
    BACKEND_DIR / "scripts" / "jd_samples" / "sample-jd.txt",
    BACKEND_DIR / "scripts" / "jd_samples" / "sample-jd-full.txt",
    BACKEND_DIR / "scripts" / "jd_samples" / "sample-jd-zh.txt",
]


def _summarize(result: dict) -> dict:
    """Build a compact comparison view of one parse result."""
    structured = result.get("structured_data") or {}
    return {
        "parse_path": result.get("parse_path"),
        "must_skills": [item.get("display_name") for item in structured.get("must_skills", [])],
        "preferred_skills": [item.get("display_name") for item in structured.get("preferred_skills", [])],
        "experience_years": (structured.get("experience_requirement") or {}).get("minimum_years"),
        "education": (structured.get("education_requirement") or {}).get("minimum_degree"),
        "visa": (structured.get("visa_requirement") or {}).get("requirement_type"),
        "jd_overview": structured.get("jd_overview"),
        "notes": result.get("raw_llm_response", {}).get("enrichment_notes"),
    }


async def _run_mode(jd_text: str, mode: str) -> dict:
    """Parse one JD text in a single mode and summarize the output."""
    result = await parse_jd_skill(jd_text=jd_text, mode=mode)
    return _summarize(result)


async def _main(args: argparse.Namespace) -> int:
    sample_files = args.jd_file or DEFAULT_SAMPLES
    modes = args.mode or ["rule", "qwen"]
    report: dict[str, dict] = {}
    for sample_path in sample_files:
        path = Path(sample_path)
        jd_text = path.read_text(encoding="utf-8-sig")
        entry: dict = {"file": str(path), "chars": len(jd_text)}
        for mode in modes:
            if mode == "qwen" and not QwenJDExtractorProvider.is_available():
                entry[mode] = {
                    "skipped": "torch/transformers not installed; install with: pip install torch transformers accelerate"
                }
                continue
            entry[mode] = await _run_mode(jd_text, mode)
        report[path.name] = entry

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"Comparison written to {args.output}")
    else:
        print(payload)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare JD parser modes on sample JDs.")
    parser.add_argument("--jd-file", action="append", default=None, help="JD text file to evaluate (repeatable).")
    parser.add_argument(
        "--mode",
        action="append",
        default=None,
        choices=["rule", "hybrid", "qwen"],
        help="Parser mode to evaluate (repeatable; default: rule + qwen).",
    )
    parser.add_argument("--output", default=None, help="Optional path to write the comparison JSON.")
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())