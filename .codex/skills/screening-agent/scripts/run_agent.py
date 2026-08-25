# Runs a deterministic L1 screening-agent loop on top of the pipeline skill.
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

REPO_ROOT = _bootstrap.REPO_ROOT
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PYTHON = sys.executable

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2

RETRYABLE_STAGES = {"cv-parse", "score", "match", "report-gen", "comparison"}
NON_RETRYABLE_ERROR_HINTS = (
    "no such file",
    "not found",
    "file not found",
    "permission denied",
    "access is denied",
    "invalid",
    "missing required",
    "missing argument",
    "certificate",
    "ssl",
    "tls",
    "authentication",
    "unauthorized",
    "forbidden",
    "api key",
)
TRANSIENT_ERROR_HINTS = (
    "timeout",
    "timed out",
    "temporary",
    "connection reset",
    "connection aborted",
    "connection refused",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "too many requests",
    "rate limit",
    "429",
    "500",
    "502",
    "503",
    "504",
)


# Stores one pipeline run snapshot for orchestration traceability.
class RunLog:
    # Creates a run log object for one pipeline invocation.
    def __init__(self, round_index: int, status: str, exit_code: int, payload: dict) -> None:
        self.round_index = round_index
        self.status = status
        self.exit_code = exit_code
        self.payload = payload

    # Converts the run log into JSON-friendly data.
    def to_dict(self) -> dict:
        return {
            "round": self.round_index,
            "status": self.status,
            "exit_code": self.exit_code,
            "candidates_count": len(self.payload.get("candidates") or []),
            "failures_count": len(self.payload.get("failures") or []),
            "payload": self.payload,
        }


# Returns a path to a skill CLI script.
def _skill_script(skill: str, script: str) -> Path:
    path = SKILLS_DIR / skill / "scripts" / script
    if not path.is_file():
        raise RuntimeError(f"skill script not found: {path}")
    return path


# Resolves output-dir into an absolute path and ensures it exists.
def _resolve_output_dir(output_dir: str) -> Path:
    path = Path(output_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# Builds the pipeline command from screening-agent arguments.
def _pipeline_cmd(args: argparse.Namespace, out_dir: Path, resume: bool) -> list[str]:
    cmd = [
        PYTHON,
        str(_skill_script("pipeline", "run_pipeline.py")),
        "--engine",
        args.engine,
        "--output-dir",
        str(out_dir),
        "--max-retries",
        str(args.pipeline_max_retries),
    ]
    if resume:
        cmd.append("--resume")
    if args.fail_fast:
        cmd.append("--fail-fast")
    if args.skip_reports:
        cmd.append("--skip-reports")
    if args.reference_date:
        cmd += ["--reference-date", args.reference_date]
    if args.position:
        cmd += ["--position", args.position]
    if args.jd_file:
        cmd += ["--jd-file", args.jd_file]
    elif args.jd_json:
        cmd += ["--jd-json", args.jd_json]
    elif args.polyu_ref:
        cmd += ["--polyu-ref", args.polyu_ref]
        if args.polyu_detail_url:
            cmd += ["--polyu-detail-url", args.polyu_detail_url]
    for item in args.cv:
        cmd += ["--cv", item]
    for item in args.extracted:
        cmd += ["--extracted", item]
    return cmd


# Runs the pipeline command and parses its JSON payload.
def _run_pipeline(cmd: list[str]) -> tuple[int, dict]:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    raw = proc.stdout.strip() or proc.stderr.strip()
    if not raw:
        return proc.returncode, {"status": "error", "error_message": "pipeline returned no output"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"status": "error", "error_message": raw}
    return proc.returncode, payload


# Returns retry-eligible failure records from one pipeline manifest.
def _retryable_failures(payload: dict) -> list[dict]:
    failures = payload.get("failures") or []
    return [f for f in failures if isinstance(f, dict) and _is_retryable_failure(f)]


# Classifies one failure record as retryable or non-retryable.
def _is_retryable_failure(failure: dict) -> bool:
    stage = str(failure.get("stage") or "")
    if stage not in RETRYABLE_STAGES:
        return False
    message = str(failure.get("error_message") or "").lower()
    if any(hint in message for hint in NON_RETRYABLE_ERROR_HINTS):
        return False
    if any(hint in message for hint in TRANSIENT_ERROR_HINTS):
        return True
    return True


# Builds a human/audit readable retry decision for the current round.
def _retry_decision(
    status: str,
    round_index: int,
    max_rounds: int,
    payload: dict,
) -> dict:
    retryable = _retryable_failures(payload)
    failures = payload.get("failures") or []
    if status == "need_input":
        return {
            "action": "ask_user",
            "reason": "missing_required_input",
            "retryable_failures_count": 0,
            "total_failures_count": len(failures),
        }
    if status == "success":
        return {
            "action": "stop",
            "reason": "all_candidates_succeeded",
            "retryable_failures_count": 0,
            "total_failures_count": len(failures),
        }
    if status == "partial_success":
        if round_index >= max_rounds:
            return {
                "action": "stop",
                "reason": "max_rounds_reached",
                "retryable_failures_count": len(retryable),
                "total_failures_count": len(failures),
            }
        if not retryable:
            return {
                "action": "stop",
                "reason": "no_retryable_failures",
                "retryable_failures_count": 0,
                "total_failures_count": len(failures),
            }
        return {
            "action": "retry",
            "reason": "retryable_failures_detected",
            "retryable_failures_count": len(retryable),
            "total_failures_count": len(failures),
        }
    return {
        "action": "stop",
        "reason": "hard_error",
        "retryable_failures_count": len(retryable),
        "total_failures_count": len(failures),
    }


# Writes agent state snapshots for resumable orchestration runs.
def _write_state(out_dir: Path, state: dict) -> None:
    state_path = out_dir / "agent-state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# Builds the final screening-agent response envelope.
def _final_payload(status: str, out_dir: Path, runs: list[RunLog], final_result: dict) -> dict:
    return {
        "status": status,
        "output_dir": str(out_dir),
        "runs": [run.to_dict() for run in runs],
        "result": final_result,
        "ask": final_result.get("ask"),
    }


# Runs L1 orchestration loop: run pipeline, inspect status, and optionally retry.
def _run_loop(args: argparse.Namespace) -> tuple[int, dict]:
    out_dir = _resolve_output_dir(args.output_dir)
    runs: list[RunLog] = []

    for round_index in range(1, args.max_rounds + 1):
        cmd = _pipeline_cmd(args, out_dir, resume=(args.resume or round_index > 1))
        exit_code, payload = _run_pipeline(cmd)
        status = str(payload.get("status") or "error")
        decision = _retry_decision(status, round_index, args.max_rounds, payload)
        run = RunLog(round_index=round_index, status=status, exit_code=exit_code, payload=payload)
        runs.append(run)

        _write_state(
            out_dir,
            {
                "status": status,
                "round": round_index,
                "max_rounds": args.max_rounds,
                "pipeline_command": cmd,
                "retry_decision": decision,
                "runs": [item.to_dict() for item in runs],
            },
        )

        if status == "need_input":
            return EXIT_NEED_INPUT, _final_payload("need_input", out_dir, runs, payload)
        if status == "success":
            return EXIT_OK, _final_payload("success", out_dir, runs, payload)
        if status == "partial_success":
            if decision["action"] != "retry":
                return EXIT_OK, _final_payload("partial_success", out_dir, runs, payload)
            continue
        return EXIT_ERROR, _final_payload("error", out_dir, runs, payload)

    latest = runs[-1].payload if runs else {"status": "error", "error_message": "no runs executed"}
    return EXIT_ERROR, _final_payload("error", out_dir, runs, latest)


# Validates top-level argument relationships before loop execution.
def _validate_args(args: argparse.Namespace) -> None:
    if args.polyu_detail_url and not args.polyu_ref:
        raise RuntimeError("--polyu-detail-url is only valid together with --polyu-ref")
    if args.max_rounds < 1:
        raise RuntimeError("--max-rounds must be >= 1")


# Parses command-line arguments for the screening-agent loop.
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run L1 screening-agent loop on top of the pipeline skill.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--jd-file", default=None, help="JD text file for the pipeline.")
    source.add_argument("--jd-json", default=None, help="Parsed JD JSON file for the pipeline.")
    source.add_argument("--polyu-ref", default=None, help="PolyU external reference for JD fetch-and-parse.")
    parser.add_argument("--polyu-detail-url", default=None, help="PolyU detail URL fallback used with --polyu-ref.")
    parser.add_argument("--cv", action="append", default=[], metavar="FILE", help="Candidate CV file (repeatable).")
    parser.add_argument(
        "--extracted",
        action="append",
        default=[],
        metavar="FILE",
        help="Extracted candidate profile JSON (repeatable).",
    )
    parser.add_argument("--position", default=None, help="Job title shown on reports.")
    parser.add_argument("--engine", choices=("legacy", "matching"), default="legacy", help="Scoring engine for pipeline.")
    parser.add_argument("--reference-date", default=None, help="Reference date used by matching engine.")
    parser.add_argument("--output-dir", default="data/pipeline_out", help="Output directory shared with pipeline.")
    parser.add_argument("--skip-reports", action="store_true", help="Skip PDF/Excel generation.")
    parser.add_argument(
        "--pipeline-max-retries",
        type=int,
        default=2,
        metavar="N",
        help="Retries per candidate stage inside each pipeline run.",
    )
    parser.add_argument("--max-rounds", type=int, default=2, metavar="N", help="Max screening-agent rounds.")
    parser.add_argument("--resume", action="store_true", help="Start the first round with pipeline --resume enabled.")
    parser.add_argument("--fail-fast", action="store_true", help="Pass through to pipeline --fail-fast behavior.")
    return parser


# Entrypoint: runs the L1 screening-agent loop and prints JSON output.
def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        _validate_args(args)
        code, payload = _run_loop(args)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        stream = sys.stdout if code in {EXIT_OK, EXIT_NEED_INPUT} else sys.stderr
        print(text, file=stream)
        return code
    except Exception as exc:
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
