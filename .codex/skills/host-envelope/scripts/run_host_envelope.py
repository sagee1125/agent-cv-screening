# Projects pipeline or screening-agent JSON onto the WorkBuddy host-visible whitelist.
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _bootstrap import REPO_ROOT  # noqa: F401

from host_envelope.project import project_host_return, rejected_envelope


# Loads a JSON object from a file path or stdin.
def _load_json(path: str | None) -> dict[str, Any]:
    if not path or path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


# Writes the host envelope to stdout (success/need_input) or stderr (error).
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Project skill stdout onto the WorkBuddy HostToolReturn whitelist."
    )
    parser.add_argument(
        "--tool",
        choices=("request_jas_access", "screen_refno", "get_run_status"),
        default="screen_refno",
        help="Host tool name stamped on the envelope.",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Skill stdout JSON file, or - for stdin. Optional for request_jas_access.",
    )
    parser.add_argument(
        "--jas-manifest",
        default=None,
        help="Optional jas-manifest.json (refno, post_title, appno, HR status).",
    )
    parser.add_argument("--run-id", default=None, help="Opaque run id for the UI file opener.")
    parser.add_argument(
        "--jas-session",
        choices=("missing", "granted", "denied", "expired"),
        default=None,
        help="Local JAS session state. Never pass cookie values.",
    )
    parser.add_argument(
        "--cookie-file-present",
        action="store_true",
        help="Set auth.cookie_file_present true (boolean only; no path).",
    )
    parser.add_argument(
        "--scratch-retained",
        action="store_true",
        help="Set scratch_retained true (downloaded CVs are kept by default).",
    )
    parser.add_argument("--post-title", default=None, help="Override post title (job metadata only).")
    args = parser.parse_args()

    try:
        payload = {} if args.tool == "request_jas_access" and not args.input else _load_json(args.input)
        jas = _load_json(args.jas_manifest) if args.jas_manifest else {}
        envelope = project_host_return(
            tool=args.tool,
            payload=payload,
            jas_manifest=jas,
            run_id=args.run_id,
            jas_session=args.jas_session,
            cookie_file_present=args.cookie_file_present,
            scratch_retained=args.scratch_retained if args.scratch_retained else None,
            post_title=args.post_title,
        )
    except Exception as exc:
        envelope = rejected_envelope(args.tool, str(exc))

    text = json.dumps(envelope, ensure_ascii=False, indent=2)
    status = envelope.get("status")
    if status == "error":
        print(text, file=sys.stderr)
        return 1
    print(text)
    return 0 if status != "need_input" else 2


if __name__ == "__main__":
    raise SystemExit(main())
