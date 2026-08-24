"""CLI runner for the screen-job orchestrator workflow.

Executes the pipeline defined in workflows/screen-job.yaml by invoking the
existing skill CLIs under .codex/skills/ and performing agent-side aggregation
(rank-items, comparison-rows, workspace state, audit log).

Example (from repository root):
    python .codex/agents/cv-screening-agent/scripts/run_screen_job.py \\
      --workspace data/agent-workspaces/demo \\
      --job-source jd_file \\
      --jd-file .codex/skills/jd-parser/examples/sample-jd.txt \\
      --cv .codex/skills/cv-parser/examples/sample-cv.pdf \\
      --position-title "Backend Engineer" \\
      --yes --export
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  (repo root cwd + backend on sys.path)

REPO_ROOT = _bootstrap.REPO_ROOT
AGENT_ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "polyu-import": REPO_ROOT / ".codex/skills/polyu-import/scripts/run_polyu_import.py",
    "jd-parser": REPO_ROOT / ".codex/skills/jd-parser/scripts/run_jd_parse.py",
    "scorer": REPO_ROOT / ".codex/skills/scorer/scripts/run_score.py",
    "cv-parser": REPO_ROOT / ".codex/skills/cv-parser/scripts/run_cv_parse.py",
    "report-gen": REPO_ROOT / ".codex/skills/report-gen/scripts/run_report.py",
}


# Serialize Decimal and other non-JSON-native values for workspace files.
def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


# Return an ISO-8601 UTC timestamp for audit and state files.
def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# Read a JSON file tolerating a UTF-8 BOM.
def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


# Write JSON with stable indentation for workspace artifacts.
def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


# Derive a workspace stem from a CV filename (lowercase, underscores, no .pdf).
def cv_stem(cv_path: Path) -> str:
    name = cv_path.stem.lower()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^a-z0-9_\-]", "_", name)
    return name.strip("_") or "candidate"


# Load workspace.state.json or return a fresh default document.
def load_state(workspace: Path, workspace_id: str) -> dict[str, Any]:
    state_path = workspace / "workspace.state.json"
    if state_path.exists():
        return _read_json(state_path)
    return {
        "workspace_id": workspace_id,
        "state": "idle",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "job": {},
        "artifacts": {},
        "checkpoints": {
            "jd_review": {"status": "pending", "confirmed_at": None},
            "config_review": {"status": "pending", "confirmed_at": None},
            "export_review": {"status": "pending", "confirmed_at": None},
        },
        "cv_batch": {"total": 0, "parsed": 0, "failed": 0, "failures": []},
        "score_version": 1,
        "pending_intent": None,
    }


# Persist workspace.state.json after mutating the in-memory state dict.
def save_state(workspace: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _write_json(workspace / "workspace.state.json", state)


# Append one JSON line to agent.audit.jsonl for traceability.
def append_audit(workspace: Path, entry: dict[str, Any]) -> None:
    log_path = workspace / "agent.audit.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _utc_now(), **entry}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=_json_default) + "\n")


# Run a subprocess command from the repository root and capture stdout/stderr.
def run_cli(argv: list[str], *, step_id: str, workspace: Path, state: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    print(f"[{step_id}] $ {' '.join(argv)}", flush=True)
    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    append_audit(
        workspace,
        {
            "actor": "runner",
            "action": "skill_invoke",
            "step_id": step_id,
            "argv": argv,
            "exit_code": result.returncode,
            "stderr": result.stderr.strip()[:500] if result.stderr else None,
        },
    )
    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr, flush=True)
    state_before = state.get("state")
    return result


# Print a checkpoint summary and optionally wait for HR confirmation on stdin.
def checkpoint(
    *,
    title: str,
    summary: dict[str, Any],
    auto_confirm: bool,
) -> None:
    print(f"\n=== CHECKPOINT: {title} ===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), flush=True)
    if auto_confirm:
        print("(auto-confirmed via --yes)\n", flush=True)
        return
    try:
        answer = input("Confirm and continue? [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in {"y", "yes"}:
        raise SystemExit(f"Stopped at checkpoint '{title}'. Re-run with --yes to skip prompts.")


# Summarize parsed JD fields for the jd_review checkpoint.
def jd_review_summary(jd_structured_path: Path) -> dict[str, Any]:
    raw = _read_json(jd_structured_path)
    structured = raw.get("structured_data")
    if not isinstance(structured, dict) and isinstance(raw.get("jd_parse"), dict):
        structured = raw["jd_parse"].get("structured_data")
    if not isinstance(structured, dict):
        structured = raw
    must = structured.get("must_skills") or []
    preferred = structured.get("preferred_skills") or []
    return {
        "must_skills": [item.get("display_name") or item.get("canonical_skill") for item in must[:20]],
        "preferred_skills": [item.get("display_name") or item.get("canonical_skill") for item in preferred[:20]],
        "language_requirements": structured.get("language_requirements"),
        "experience_requirement": structured.get("experience_requirement"),
    }


# Summarize scoring config fields for the config_review checkpoint.
def config_review_summary(config_path: Path) -> dict[str, Any]:
    config = _read_json(config_path)
    return {
        "required_skills": config.get("required_skills"),
        "preferred_skills": config.get("preferred_skills"),
        "weights": config.get("weights"),
        "hard_filters": config.get("hard_filters"),
        "tiers": config.get("tiers"),
    }


# Create workspace directories and initial state file (screen-job step init_workspace).
def step_init_workspace(workspace: Path, workspace_id: str) -> dict[str, Any]:
    for sub in ("cvs", "scores", "reports"):
        (workspace / sub).mkdir(parents=True, exist_ok=True)
    state = load_state(workspace, workspace_id)
    state["state"] = "idle"
    save_state(workspace, state)
    append_audit(workspace, {"actor": "runner", "action": "init_workspace", "workspace_id": workspace_id})
    return state


# Fetch and parse a PolyU job into jd.structured.json (step source_jd_polyu).
def step_source_jd_polyu(
    workspace: Path,
    state: dict[str, Any],
    *,
    polyu_ref: str,
) -> None:
    out = workspace / "jd.structured.json"
    result = run_cli(
        [
            sys.executable,
            str(SKILLS["polyu-import"]),
            "fetch-and-parse",
            "--external-ref",
            polyu_ref,
            "--output",
            str(out),
        ],
        step_id="source_jd_polyu",
        workspace=workspace,
        state=state,
    )
    if result.returncode != 0:
        raise SystemExit(
            "PolyU fetch failed. Paste JD text and re-run with --job-source jd_text or --job-source jd_file."
        )
    payload = _read_json(out)
    jd_text = payload.get("jd_text") or ""
    (workspace / "jd.raw.txt").write_text(jd_text, encoding="utf-8")
    state["state"] = "jd_parsed"
    state.setdefault("job", {})
    state["job"].update(
        {
            "title": payload.get("title"),
            "source": "polyu",
            "external_ref": polyu_ref,
            "position_title": payload.get("title"),
        }
    )
    save_state(workspace, state)


# Write or copy raw JD text into the workspace (steps source_jd_text / source_jd_file).
def step_source_jd_text(workspace: Path, *, jd_text: str) -> None:
    (workspace / "jd.raw.txt").write_text(jd_text, encoding="utf-8")


# Copy an external JD file into the workspace as jd.raw.txt.
def step_source_jd_file(workspace: Path, *, jd_file: Path) -> None:
    src = jd_file if jd_file.is_absolute() else REPO_ROOT / jd_file
    (workspace / "jd.raw.txt").write_text(src.read_text(encoding="utf-8-sig"), encoding="utf-8")


# Parse jd.raw.txt with the jd-parser skill (step parse_jd).
def step_parse_jd(workspace: Path, state: dict[str, Any]) -> None:
    out = workspace / "jd.structured.json"
    result = run_cli(
        [
            sys.executable,
            str(SKILLS["jd-parser"]),
            "--jd-file",
            str(workspace / "jd.raw.txt"),
            "--output",
            str(out),
        ],
        step_id="parse_jd",
        workspace=workspace,
        state=state,
    )
    if result.returncode != 0:
        raise SystemExit("JD parse failed.")
    state["state"] = "jd_parsed"
    save_state(workspace, state)


# Build scoring.config.json from jd.structured.json (step build_scoring_config).
def step_build_scoring_config(workspace: Path, state: dict[str, Any]) -> None:
    out = workspace / "scoring.config.json"
    result = run_cli(
        [
            sys.executable,
            str(SKILLS["scorer"]),
            "build-config",
            "--jd-structured",
            str(workspace / "jd.structured.json"),
            "--output",
            str(out),
        ],
        step_id="build_scoring_config",
        workspace=workspace,
        state=state,
    )
    if result.returncode != 0:
        raise SystemExit("build-config failed: invalid JD structured input.")
    state["state"] = "config_ready"
    state.setdefault("artifacts", {})["scoring_config"] = "scoring.config.json"
    save_state(workspace, state)


# Batch-parse CV PDFs; record per-file failures without stopping the batch.
def step_parse_cvs_batch(
    workspace: Path,
    state: dict[str, Any],
    *,
    cv_paths: list[Path],
) -> list[Path]:
    extracted_files: list[Path] = []
    failures: list[dict[str, str]] = []
    jd_raw = workspace / "jd.raw.txt"
    for cv_path in cv_paths:
        resolved = cv_path if cv_path.is_absolute() else REPO_ROOT / cv_path
        stem = cv_stem(resolved)
        out = workspace / "cvs" / f"{stem}.extracted.json"
        argv = [
            sys.executable,
            str(SKILLS["cv-parser"]),
            "--file",
            str(resolved),
        ]
        if jd_raw.exists():
            argv.extend(["--jd-file", str(jd_raw)])
        argv.extend(["--output", str(out)])
        result = run_cli(argv, step_id="parse_cvs_batch", workspace=workspace, state=state)
        if result.returncode != 0:
            err_msg = result.stderr.strip() or "cv-parser failed"
            failures.append({"file": str(resolved), "error_message": err_msg})
            continue
        extracted_files.append(out)
    failures_path = workspace / "cvs" / "parse-failures.json"
    if failures:
        _write_json(failures_path, failures)
    state["state"] = "cvs_ingesting"
    state["cv_batch"] = {
        "total": len(cv_paths),
        "parsed": len(extracted_files),
        "failed": len(failures),
        "failures": [item["file"] for item in failures],
    }
    save_state(workspace, state)
    return extracted_files


# Score each extracted profile against scoring.config.json.
def step_score_each_cv(workspace: Path, state: dict[str, Any], *, extracted_files: list[Path]) -> list[Path]:
    score_files: list[Path] = []
    config = workspace / "scoring.config.json"
    for extracted in extracted_files:
        stem = extracted.stem.replace(".extracted", "")
        out = workspace / "scores" / f"{stem}.score.json"
        result = run_cli(
            [
                sys.executable,
                str(SKILLS["scorer"]),
                "score",
                "--extracted",
                str(extracted),
                "--config",
                str(config),
                "--output",
                str(out),
            ],
            step_id="score_each_cv",
            workspace=workspace,
            state=state,
        )
        if result.returncode != 0:
            continue
        score_files.append(out)
    return score_files


# Aggregate score files into rank-items.json (step build_rank_items).
def build_rank_items(score_files: list[Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for score_path in score_files:
        score = _read_json(score_path)
        stem = score_path.name.replace(".score.json", "")
        total = score.get("total_score", 0)
        if isinstance(total, Decimal):
            total = float(total)
        items.append({"candidate_id": stem, "total_score": total})
    return items


# Write rank-items.json from scored candidates.
def step_build_rank_items(workspace: Path, score_files: list[Path]) -> Path:
    items = build_rank_items(score_files)
    if not items:
        raise SystemExit("No score files available to build rank-items.json.")
    out = workspace / "scores" / "rank-items.json"
    _write_json(out, items)
    return out


# Rank candidates using scorer --rank --items (step rank_candidates).
def step_rank_candidates(
    workspace: Path,
    state: dict[str, Any],
    *,
    rank_items_path: Path,
    first_extracted: Path,
) -> Path:
    out = workspace / "scores" / "ranking.json"
    result = run_cli(
        [
            sys.executable,
            str(SKILLS["scorer"]),
            "score",
            "--extracted",
            str(first_extracted),
            "--config",
            str(workspace / "scoring.config.json"),
            "--rank",
            "--items",
            str(rank_items_path),
            "--output",
            str(out),
        ],
        step_id="rank_candidates",
        workspace=workspace,
        state=state,
    )
    if result.returncode != 0:
        raise SystemExit("Ranking failed.")
    state["state"] = "ranked"
    state.setdefault("artifacts", {})["ranking"] = "scores/ranking.json"
    save_state(workspace, state)
    return out


# Build a suggestion_summary string from interview_suggestions on a score object.
def _suggestion_summary(score: dict[str, Any]) -> str:
    snapshot = score.get("full_snapshot") or {}
    suggestions = snapshot.get("interview_suggestions") or score.get("interview_suggestions") or []
    parts: list[str] = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("rule_id", "UNKNOWN")
        severity = item.get("severity", "info")
        parts.append(f"{rule_id}:{severity}")
    return "; ".join(parts)


# Build comparison-rows.json for report-gen (step build_comparison_rows).
def build_comparison_rows(
    *,
    ranking_path: Path,
    workspace: Path,
) -> list[dict[str, Any]]:
    ranked = _read_json(ranking_path)
    ranking_list = ranked.get("ranking") if isinstance(ranked, dict) else None
    if not isinstance(ranking_list, list):
        raise SystemExit("ranking.json missing 'ranking' array.")

    rows: list[dict[str, Any]] = []
    for item in ranking_list:
        candidate_id = str(item.get("candidate_id", ""))
        score_path = workspace / "scores" / f"{candidate_id}.score.json"
        extracted_path = workspace / "cvs" / f"{candidate_id}.extracted.json"
        if not score_path.exists():
            continue
        score = _read_json(score_path)
        name = candidate_id
        if extracted_path.exists():
            extracted = _read_json(extracted_path)
            profile = extracted.get("structured_data") if isinstance(extracted.get("structured_data"), dict) else extracted
            if isinstance(profile, dict) and profile.get("name"):
                name = str(profile["name"])
        dims = score.get("dimension_scores") or {}
        rows.append(
            {
                "rank": item.get("rank"),
                "name": name,
                "total_score": float(score.get("total_score", 0)),
                "skill_match": float(dims.get("skill_match", 0)),
                "experience_match": float(dims.get("experience_match", 0)),
                "education_match": float(dims.get("education_match", 0)),
                "research_quality": float(dims.get("research_quality", 0)),
                "tier": score.get("tier", ""),
                "suggestion_summary": _suggestion_summary(score),
            }
        )
    return rows


# Write comparison-rows.json from ranking and per-candidate score files.
def step_build_comparison_rows(workspace: Path, ranking_path: Path) -> Path:
    rows = build_comparison_rows(ranking_path=ranking_path, workspace=workspace)
    out = workspace / "scores" / "comparison-rows.json"
    _write_json(out, rows)
    return out


# Export the Excel shortlist report (step export_comparison_excel).
def step_export_comparison_excel(
    workspace: Path,
    state: dict[str, Any],
    *,
    position_title: str,
    rows_path: Path,
) -> Path:
    out = workspace / "reports" / "shortlist.xlsx"
    result = run_cli(
        [
            sys.executable,
            str(SKILLS["report-gen"]),
            "comparison",
            "--position",
            position_title,
            "--rows",
            str(rows_path),
            "--output",
            str(out),
        ],
        step_id="export_comparison_excel",
        workspace=workspace,
        state=state,
    )
    if result.returncode != 0:
        raise SystemExit("Excel export failed.")
    state["state"] = "exported"
    state.setdefault("artifacts", {})["shortlist_report"] = "reports/shortlist.xlsx"
    save_state(workspace, state)
    return out


# Export PDF one-pagers for the top N ranked candidates.
def step_export_top_pdf(
    workspace: Path,
    state: dict[str, Any],
    *,
    position_title: str,
    rows_path: Path,
    top_n: int,
) -> list[Path]:
    rows = _read_json(rows_path)
    if not isinstance(rows, list):
        raise SystemExit("comparison-rows.json must be a JSON array.")
    outputs: list[Path] = []
    for row in rows[:top_n]:
        rank = int(row.get("rank") or 0)
        name = str(row.get("name") or "")
        candidate_stem = None
        for extracted in (workspace / "cvs").glob("*.extracted.json"):
            payload = _read_json(extracted)
            profile = payload.get("structured_data") if isinstance(payload.get("structured_data"), dict) else payload
            if isinstance(profile, dict) and profile.get("name") == name:
                candidate_stem = extracted.stem.replace(".extracted", "")
                break
        if candidate_stem is None:
            # Fall back to rank order file glob
            score_files = sorted((workspace / "scores").glob("*.score.json"))
            if rank - 1 < len(score_files):
                candidate_stem = score_files[rank - 1].stem.replace(".score", "")
        if candidate_stem is None:
            continue
        out = workspace / "reports" / f"{candidate_stem}.report.pdf"
        result = run_cli(
            [
                sys.executable,
                str(SKILLS["report-gen"]),
                "candidate",
                "--extracted",
                str(workspace / "cvs" / f"{candidate_stem}.extracted.json"),
                "--score",
                str(workspace / "scores" / f"{candidate_stem}.score.json"),
                "--position",
                position_title,
                "--rank",
                str(rank),
                "--output",
                str(out),
            ],
            step_id="export_top_pdf",
            workspace=workspace,
            state=state,
        )
        if result.returncode == 0:
            outputs.append(out)
    return outputs


# Resolve position title from CLI flag, workspace state, or JD structured output.
def resolve_position_title(workspace: Path, state: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    job = state.get("job") or {}
    if job.get("position_title"):
        return str(job["position_title"])
    if job.get("title"):
        return str(job["title"])
    jd_path = workspace / "jd.structured.json"
    if jd_path.exists():
        payload = _read_json(jd_path)
        if payload.get("title"):
            return str(payload["title"])
    return "Job Position"


# Parse CLI arguments for the screen-job runner.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CV screening screen-job workflow.")
    parser.add_argument("--workspace", required=True, help="Workspace directory under data/agent-workspaces/")
    parser.add_argument(
        "--job-source",
        required=True,
        choices=["polyu_ref", "jd_text", "jd_file", "existing_workspace"],
        help="How the JD is supplied for this run.",
    )
    parser.add_argument("--polyu-ref", default=None, help="PolyU external ref (job_source=polyu_ref).")
    parser.add_argument("--jd-text", default=None, help="Inline JD text (job_source=jd_text).")
    parser.add_argument("--jd-file", default=None, help="Path to JD text file (job_source=jd_file).")
    parser.add_argument("--cv", action="append", default=[], help="CV PDF path; repeat for batch.")
    parser.add_argument("--position-title", default=None, help="Job title shown on reports.")
    parser.add_argument("--yes", action="store_true", help="Auto-confirm HR checkpoints.")
    parser.add_argument("--export", action="store_true", help="Generate Excel shortlist after ranking.")
    parser.add_argument("--export-pdf", type=int, default=0, metavar="N", help="Generate PDF reports for top N.")
    parser.add_argument(
        "--jd-only",
        action="store_true",
        help="Stop after build-config (no CV parse/score); useful for JD validation.",
    )
    return parser


# Execute the full screen-job workflow according to CLI flags.
def main() -> int:
    args = build_parser().parse_args()
    workspace = Path(args.workspace)
    if not workspace.is_absolute():
        workspace = REPO_ROOT / workspace
    workspace_id = workspace.name

    state = step_init_workspace(workspace, workspace_id)

    if args.job_source == "polyu_ref":
        if not args.polyu_ref:
            raise SystemExit("--polyu-ref is required when --job-source polyu_ref")
        step_source_jd_polyu(workspace, state, polyu_ref=args.polyu_ref)
    elif args.job_source == "jd_text":
        if not args.jd_text:
            raise SystemExit("--jd-text is required when --job-source jd_text")
        step_source_jd_text(workspace, jd_text=args.jd_text)
        step_parse_jd(workspace, state)
    elif args.job_source == "jd_file":
        if not args.jd_file:
            raise SystemExit("--jd-file is required when --job-source jd_file")
        step_source_jd_file(workspace, jd_file=Path(args.jd_file))
        step_parse_jd(workspace, state)
    elif args.job_source == "existing_workspace":
        if not (workspace / "jd.structured.json").exists():
            raise SystemExit("existing_workspace requires jd.structured.json in the workspace.")
        state["state"] = "jd_parsed"
        save_state(workspace, state)

    if not (workspace / "jd.structured.json").exists():
        raise SystemExit("jd.structured.json missing after JD sourcing.")

    checkpoint(
        title="jd_review",
        summary=jd_review_summary(workspace / "jd.structured.json"),
        auto_confirm=args.yes,
    )
    state["checkpoints"]["jd_review"] = {"status": "confirmed", "confirmed_at": _utc_now()}
    save_state(workspace, state)

    step_build_scoring_config(workspace, state)

    checkpoint(
        title="config_review",
        summary=config_review_summary(workspace / "scoring.config.json"),
        auto_confirm=args.yes,
    )
    state["checkpoints"]["config_review"] = {"status": "confirmed", "confirmed_at": _utc_now()}
    save_state(workspace, state)

    if args.jd_only:
        print(json.dumps({"status": "success", "workspace": str(workspace), "state": state["state"]}, indent=2))
        return 0

    cv_paths = [Path(p) for p in args.cv]
    if not cv_paths:
        print("No --cv files provided; stopping after config build. Add --cv to continue screening.")
        print(json.dumps({"status": "success", "workspace": str(workspace), "state": state["state"]}, indent=2))
        return 0

    extracted_files = step_parse_cvs_batch(workspace, state, cv_paths=cv_paths)
    if not extracted_files:
        raise SystemExit("All CV parses failed; see cvs/parse-failures.json")

    score_files = step_score_each_cv(workspace, state, extracted_files=extracted_files)
    if not score_files:
        raise SystemExit("All scoring steps failed.")

    rank_items_path = step_build_rank_items(workspace, score_files)
    step_rank_candidates(
        workspace,
        state,
        rank_items_path=rank_items_path,
        first_extracted=extracted_files[0],
    )
    rows_path = step_build_comparison_rows(workspace, workspace / "scores" / "ranking.json")

    position_title = resolve_position_title(workspace, state, args.position_title)
    report_paths: list[str] = [str(rows_path)]

    if args.export:
        xlsx = step_export_comparison_excel(workspace, state, position_title=position_title, rows_path=rows_path)
        report_paths.append(str(xlsx))

    if args.export_pdf > 0:
        pdfs = step_export_top_pdf(
            workspace,
            state,
            position_title=position_title,
            rows_path=rows_path,
            top_n=args.export_pdf,
        )
        report_paths.extend(str(p) for p in pdfs)

    print(
        json.dumps(
            {
                "status": "success",
                "workspace": str(workspace),
                "state": state["state"],
                "ranking": str(workspace / "scores" / "ranking.json"),
                "comparison_rows": str(rows_path),
                "reports": report_paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
