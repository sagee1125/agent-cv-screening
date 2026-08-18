"""CLI entry point for the Scorer skill (agent-facing).

Example (from repository root):
    python backend/scripts/skills/run_score.py --extracted extracted.json --config config.json
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from app.skills.score import rank_candidates_skill, score_candidate_skill


def _json_default(value: object) -> object:
    # Scorer returns Decimal for total_score; make it JSON-safe.
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score an extracted candidate profile against a scoring config.")
    parser.add_argument("--extracted", required=True, help="Path to JSON file with CV Parser structured_data.")
    parser.add_argument("--config", required=True, help="Path to JSON file with the scoring config.")
    parser.add_argument("--rank", action="store_true", help="Also rank multiple scored items (see --items).")
    parser.add_argument("--items", default=None, help="Optional JSON file with a list of scored items to rank.")
    parser.add_argument("--output", default=None, help="Optional path to write the JSON result (default: stdout).")
    args = parser.parse_args()

    extracted = json.loads(Path(args.extracted).read_text(encoding="utf-8-sig"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))

    try:
        result = score_candidate_skill(extracted_data=extracted, config=config)
        if args.rank:
            items = json.loads(Path(args.items).read_text(encoding="utf-8-sig")) if args.items else []
            result = {"score": result, "ranking": rank_candidates_skill(items)}
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    payload = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
