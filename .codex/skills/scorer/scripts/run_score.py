"""CLI entry point for the Scorer skill (agent-facing).

Subcommands:
    score         Score an extracted candidate profile against a scoring config.
    build-config  Build a scoring config from JD parser structured_data.

Backward compatibility: a legacy flat invocation (--extracted/--config, no
subcommand) is treated as the `score` subcommand.

Example (from repository root):
    python .codex/skills/scorer/scripts/run_score.py score --extracted extracted.json --config config.json
    python .codex/skills/scorer/scripts/run_score.py build-config --jd-structured jd-out.json --output config.json
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from app.skills.score import build_scoring_config_from_jd, rank_candidates_skill, score_candidate_skill

_SUBCOMMANDS = ("score", "build-config")
# Requirement keys that make a JD structured_data payload usable for config building.
# CV profile keys that make an extracted payload usable for scoring.
_CV_FIELD_KEYS = ("name", "email", "phone", "skills", "education", "experience", "publications")
_JD_FIELD_KEYS = (
    "must_skills",
    "preferred_skills",
    "language_requirements",
    "education_requirement",
    "visa_requirement",
    "experience_requirement",
    "location",
)


def _json_default(value: object) -> object:
    # Scorer returns Decimal for total_score; make it JSON-safe.
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _read_json(path: str) -> dict:
    # Load a JSON file (BOM-tolerant) into a dict.
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _emit(payload: str, output: str | None) -> None:
    # Write the JSON payload to --output or print it to stdout.
    if output:
        Path(output).write_text(payload, encoding="utf-8")
    else:
        print(payload)


def _unwrap_config(config: dict) -> dict:
    # Unwrap a build-config envelope ({status: success, config: {...}}) into the inner config dict.
    if isinstance(config, dict) and config.get("status") == "success" and isinstance(config.get("config"), dict):
        return config["config"]
    return config


def _unwrap_extracted_data(raw: dict) -> dict:
    # Unwrap a CV parser envelope ({... structured_data: {...}}) into the inner profile dict.
    if not isinstance(raw, dict):
        raise ValueError("invalid extracted input: expected a JSON object")
    extracted = raw.get("structured_data")
    if isinstance(extracted, dict):
        pass
    elif any(key in raw for key in _CV_FIELD_KEYS):
        extracted = raw
    else:
        raise ValueError(
            "invalid extracted input: expected CV parser structured_data or envelope with structured_data"
        )
    if not any(key in extracted for key in _CV_FIELD_KEYS):
        raise ValueError("invalid extracted input: no usable candidate profile fields")
    return extracted


def _run_score(args: argparse.Namespace) -> int:
    # Score an extracted candidate profile against a scoring config.
    try:
        extracted = _unwrap_extracted_data(_read_json(args.extracted))
        config = _unwrap_config(_read_json(args.config))
        result = score_candidate_skill(extracted_data=extracted, config=config)
        if args.rank:
            items = _read_json(args.items) if args.items else []
            result = {"score": result, "ranking": rank_candidates_skill(items)}
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _emit(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default), args.output)
    return 0


def _load_jd_structured(path: str) -> dict:
    # Load JD structured_data, unwrapping jd_parse / structured_data envelopes, and fail fast on invalid input.
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("jd-structured must be a JSON object")
    layer = raw
    if isinstance(layer.get("jd_parse"), dict):
        layer = layer["jd_parse"]
    if "structured_data" in layer:
        structured_data = layer["structured_data"]
        if not isinstance(structured_data, dict):
            raise ValueError("invalid JD input: structured_data is null or not an object")
        layer = structured_data
    if not isinstance(layer, dict):
        raise ValueError("jd-structured must be a JSON object")
    if not any(layer.get(key) for key in _JD_FIELD_KEYS):
        raise ValueError("invalid JD input: no usable JD requirements (must_skills/preferred_skills/etc.)")
    return layer


def _run_build_config(args: argparse.Namespace) -> int:
    # Build a scoring config from JD structured_data; stdout prints the envelope, --output gets the raw config.
    try:
        jd_structured = _load_jd_structured(args.jd_structured)
        base_config = _read_json(args.base_config) if args.base_config else None
        config = build_scoring_config_from_jd(jd_structured, base_config=base_config)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "success", "config": config}, ensure_ascii=False, indent=2, default=_json_default))
    if args.output:
        Path(args.output).write_text(
            json.dumps(config, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    # Build the argparse CLI with the score and build-config subcommands.
    parser = argparse.ArgumentParser(description="Score candidates or build scoring configs from JD data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    score_parser = subparsers.add_parser("score", help="Score an extracted candidate profile against a scoring config.")
    score_parser.add_argument("--extracted", required=True, help="Path to JSON file with CV Parser structured_data.")
    score_parser.add_argument("--config", required=True, help="Path to JSON file with the scoring config.")
    score_parser.add_argument("--rank", action="store_true", help="Also rank multiple scored items (see --items).")
    score_parser.add_argument("--items", default=None, help="Optional JSON file with a list of scored items to rank.")
    score_parser.add_argument("--output", default=None, help="Optional path to write the JSON result (default: stdout).")
    score_parser.set_defaults(func=_run_score)

    build_parser = subparsers.add_parser("build-config", help="Build a scoring config from JD parser structured_data.")
    build_parser.add_argument("--jd-structured", required=True, help="Path to JD parser output or pure structured_data JSON.")
    build_parser.add_argument("--base-config", default=None, help="Optional base scoring config JSON to merge/override.")
    build_parser.add_argument("--output", default=None, help="Optional path to write the raw scoring config JSON.")
    build_parser.set_defaults(func=_run_build_config)
    return parser


def main() -> int:
    argv = list(sys.argv[1:])
    # Backward compatible: a flat invocation (--extracted/--config) defaults to the score subcommand.
    if argv and argv[0] not in _SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["score"] + argv
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
