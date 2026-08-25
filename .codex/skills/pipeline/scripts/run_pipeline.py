"""CLI entry point for the pipeline skill (agent-facing).

Runs the full candidate screening pipeline in one command by chaining the
other skill CLIs: (optional PolyU import) -> jd-parser -> scorer build-config
-> cv-parser -> scorer score -> report-gen (PDF per candidate + Excel).

Two scoring engines are supported:
- legacy (default): the deterministic ScorerService (dimension_scores + interview_suggestions).
- matching: the six-dimension candidate_matching engine, which emits the same
  radar/interview-question detail payload the frontend modal shows, and renders
  that content in the PDF reports.

Example (from repository root):
    python .codex/skills/pipeline/scripts/run_pipeline.py \
      --jd-file jd.txt --cv cv1.pdf --cv cv2.pdf \
      --position "Backend Engineer" --output-dir data/pipeline_out
    python .codex/skills/pipeline/scripts/run_pipeline.py \
      --jd-file jd.txt --cv cv1.pdf --engine matching \
      --position "Backend Engineer" --output-dir data/pipeline_out
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

REPO_ROOT = _bootstrap.REPO_ROOT
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PYTHON = sys.executable


def _skill_script(skill: str, script: str) -> Path:
    """Return the absolute path of a skill CLI script."""
    path = SKILLS_DIR / skill / "scripts" / script
    if not path.is_file():
        raise RuntimeError(f"skill script not found: {path}")
    return path


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Run a skill CLI subprocess and raise its JSON error envelope on failure."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(message)
    return proc


def _load_json(path: Path) -> dict:
    """Load a JSON file tolerating a UTF-8 BOM."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _safe_name(name: str) -> str:
    """Return a filesystem-safe token derived from a candidate name."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_")
    return cleaned or "candidate"


def _radar_dim_score(dims: dict, dimension_id: str) -> float:
    """Return a numeric radar dimension score, treating inactive (None) dimensions as 0."""
    value = dims.get(dimension_id)
    return float(value) if value is not None else 0.0


def _resolve_jd_source(args: argparse.Namespace, out_dir: Path) -> tuple[Path, str | None]:
    """Return (jd JSON path for build-config/match, optional JD text for CV context)."""
    if args.polyu_ref:
        polyu_out = out_dir / "polyu-parsed.json"
        cmd = [
            PYTHON,
            str(_skill_script("polyu-import", "run_polyu_import.py")),
            "fetch-and-parse",
            "--output",
            str(polyu_out),
        ]
        if args.polyu_ref:
            cmd += ["--external-ref", args.polyu_ref]
        if args.polyu_detail_url:
            cmd += ["--detail-url", args.polyu_detail_url]
        _run(cmd)
        data = _load_json(polyu_out)
        return polyu_out, data.get("jd_text")
    if args.jd_json:
        jd_path = Path(args.jd_json)
        data = _load_json(jd_path)
        return jd_path, data.get("jd_text")
    if args.jd_file:
        jd_text = Path(args.jd_file).read_text(encoding="utf-8-sig")
        jd_parse_out = out_dir / "jd-parse.json"
        _run(
            [
                PYTHON,
                str(_skill_script("jd-parser", "run_jd_parse.py")),
                "--jd-file",
                str(Path(args.jd_file)),
                "--output",
                str(jd_parse_out),
            ]
        )
        return jd_parse_out, jd_text
    raise RuntimeError("no JD source: provide --jd-file, --jd-json, or --polyu-ref/--polyu-detail-url")


def _parse_candidates(args: argparse.Namespace, out_dir: Path, jd_text: str | None) -> list[dict]:
    """Parse each CV (cv-parser) or reuse provided extracted profiles."""
    jd_context = None
    if jd_text:
        jd_context = out_dir / "jd-context.txt"
        jd_context.write_text(jd_text, encoding="utf-8")
    candidates: list[dict] = []
    for i, cv in enumerate(args.cv, start=1):
        extracted_out = out_dir / f"extracted-{i}.json"
        cmd = [
            PYTHON,
            str(_skill_script("cv-parser", "run_cv_parse.py")),
            "--file",
            str(cv),
            "--output",
            str(extracted_out),
        ]
        if jd_context:
            cmd += ["--jd-file", str(jd_context)]
        _run(cmd)
        candidates.append({"extracted": extracted_out, "source": str(cv)})
    for ext in args.extracted:
        candidates.append({"extracted": Path(ext), "source": str(ext)})
    return candidates


def _candidate_name(extracted_path: Path) -> str:
    """Read the candidate name from an extracted profile (envelope or flat dict)."""
    extracted = _load_json(extracted_path)
    structured = extracted.get("structured_data") or extracted
    return structured.get("name") or "Unknown"


def _run_legacy_engine(args: argparse.Namespace, out_dir: Path, jd_source: Path, candidates: list[dict]) -> int:
    """Run build-config + score + rank + reports with the legacy ScorerService."""
    config_out = out_dir / "config.json"
    _run(
        [
            PYTHON,
            str(_skill_script("scorer", "run_score.py")),
            "build-config",
            "--jd-structured",
            str(jd_source),
            "--output",
            str(config_out),
        ]
    )
    for i, cand in enumerate(candidates, start=1):
        score_out = out_dir / f"score-{i}.json"
        _run(
            [
                PYTHON,
                str(_skill_script("scorer", "run_score.py")),
                "score",
                "--extracted",
                str(cand["extracted"]),
                "--config",
                str(config_out),
                "--output",
                str(score_out),
            ]
        )
        cand["score"] = score_out

    rows: list[dict] = []
    for i, cand in enumerate(candidates, start=1):
        score = _load_json(cand["score"])
        extracted = _load_json(cand["extracted"])
        structured = extracted.get("structured_data") or extracted
        name = structured.get("name") or "Unknown"
        dims = score.get("dimension_scores") or {}
        snapshot = score.get("full_snapshot") or {}
        suggestions = snapshot.get("interview_suggestions") or score.get("interview_suggestions") or []
        rows.append(
            {
                "name": name,
                "total_score": score.get("total_score", 0),
                "tier": score.get("tier", ""),
                "skill_match": dims.get("skill_match", 0),
                "experience_match": dims.get("experience_match", 0),
                "education_match": dims.get("education_match", 0),
                "research_quality": dims.get("research_quality", 0),
                "suggestion_summary": " | ".join(s.get("text", "") for s in suggestions[:3]),
                "_extracted": cand["extracted"],
                "_score": cand["score"],
                "_source": cand["source"],
            }
        )
    rows.sort(key=lambda r: r["total_score"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    reports = _generate_reports(args, out_dir, rows)
    return _build_manifest(out_dir, jd_source, config_out, rows, reports, engine="legacy")


def _run_matching_engine(args: argparse.Namespace, out_dir: Path, jd_source: Path, candidates: list[dict]) -> int:
    """Run the matching engine per candidate and render modal-style radar/interview PDFs."""
    reference_date = args.reference_date or date.today().isoformat()
    rows: list[dict] = []
    for i, cand in enumerate(candidates, start=1):
        detail_out = out_dir / f"detail-{i}.json"
        _run(
            [
                PYTHON,
                str(_skill_script("scorer", "run_score.py")),
                "match",
                "--jd-structured",
                str(jd_source),
                "--cv-extracted",
                str(cand["extracted"]),
                "--reference-date",
                reference_date,
                "--output",
                str(detail_out),
            ]
        )
        detail = _load_json(detail_out)
        name = _candidate_name(cand["extracted"])
        dims = {
            (d.get("dimension_id") or ""): d.get("score")
            for d in (detail.get("radar_dimensions") or [])
            if isinstance(d, dict)
        }
        questions = detail.get("interview_questions") or []
        suggestion_summary = "; ".join(
            f"{q.get('priority', '')}:{q.get('template_id', '')}" for q in questions[:3]
        )
        rows.append(
            {
                "name": name,
                "total_score": float(detail.get("match_score", 0)),
                "tier": detail.get("fit_band") or "",
                "skill_match": _radar_dim_score(dims, "core_skill_match"),
                "experience_match": _radar_dim_score(dims, "relevant_experience"),
                "education_match": _radar_dim_score(dims, "education_certification"),
                "research_quality": _radar_dim_score(dims, "evidence_impact"),
                "suggestion_summary": suggestion_summary,
                "_extracted": cand["extracted"],
                "_detail": detail_out,
                "_source": cand["source"],
            }
        )
    rows.sort(key=lambda r: r["total_score"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    reports = _generate_reports(args, out_dir, rows)
    return _build_manifest(out_dir, jd_source, None, rows, reports, engine="matching")


def _generate_reports(args: argparse.Namespace, out_dir: Path, rows: list[dict]) -> dict:
    """Generate per-candidate PDFs and one Excel comparison (unless skipped)."""
    reports: dict = {}
    if args.skip_reports:
        return reports
    for row in rows:
        pdf_out = out_dir / f"report-{row['rank']}-{_safe_name(row['name'])}.pdf"
        cmd = [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "candidate",
            "--extracted",
            str(row["_extracted"]),
            "--position",
            args.position,
            "--name",
            row["name"],
            "--rank",
            str(row["rank"]),
            "--output",
            str(pdf_out),
        ]
        if row.get("_detail"):
            cmd += ["--detail", str(row["_detail"])]
        else:
            cmd += ["--score", str(row["_score"])]
        _run(cmd)
        row["_pdf"] = pdf_out
    comparison_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
    rows_out = out_dir / "rows.json"
    rows_out.write_text(json.dumps(comparison_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    xlsx_out = out_dir / "comparison.xlsx"
    _run(
        [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "comparison",
            "--position",
            args.position,
            "--rows",
            str(rows_out),
            "--output",
            str(xlsx_out),
        ]
    )
    reports["comparison_xlsx"] = str(xlsx_out)
    return reports


def _build_manifest(
    out_dir: Path,
    jd_source: Path,
    config_out: Path | None,
    rows: list[dict],
    reports: dict,
    engine: str,
) -> int:
    """Print the pipeline result manifest to stdout."""
    manifest_rows = []
    for row in rows:
        manifest_rows.append(
            {
                "rank": row["rank"],
                "name": row["name"],
                "source": row["_source"],
                "total_score": row["total_score"],
                "tier": row["tier"],
                "extracted_json": str(row["_extracted"]),
                "score_json": str(row["_score"]) if "_score" in row else None,
                "detail_json": str(row["_detail"]) if "_detail" in row else None,
                "report_pdf": str(row["_pdf"]) if "_pdf" in row else None,
            }
        )
    manifest = {
        "status": "success",
        "engine": engine,
        "output_dir": str(out_dir),
        "jd_source": str(jd_source),
        "config_json": str(config_out) if config_out else None,
        "candidates": manifest_rows,
        "reports": reports,
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _run_pipeline(args: argparse.Namespace) -> int:
    """Execute every pipeline step and print a result manifest to stdout."""
    if args.polyu_detail_url and not args.polyu_ref:
        raise RuntimeError("--polyu-detail-url is only valid together with --polyu-ref")
    if not args.cv and not args.extracted:
        raise RuntimeError("no candidates: provide at least one --cv or --extracted file")
    if not args.skip_reports and not args.position:
        raise RuntimeError("--position is required when generating reports (or pass --skip-reports)")

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    jd_source, jd_text = _resolve_jd_source(args, out_dir)
    candidates = _parse_candidates(args, out_dir, jd_text)
    if args.engine == "matching":
        return _run_matching_engine(args, out_dir, jd_source, candidates)
    return _run_legacy_engine(args, out_dir, jd_source, candidates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full candidate screening pipeline end-to-end.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--jd-file", default=None, help="JD text file; parsed with the jd-parser skill.")
    source.add_argument("--jd-json", default=None, help="Existing parsed JD JSON (jd-parser output, polyu-parsed output, or pure structured_data).")
    source.add_argument("--polyu-ref", default=None, help="PolyU external ref; fetched and parsed with the polyu-import skill.")
    parser.add_argument("--polyu-detail-url", default=None, help="PolyU detail URL fallback used with --polyu-ref.")
    parser.add_argument("--engine", choices=("legacy", "matching"), default="legacy", help="Scoring engine: legacy scorer (default) or matching engine with radar/interview detail.")
    parser.add_argument("--reference-date", default=None, help="Reference date YYYY-MM-DD used by the matching engine (default: today).")
    parser.add_argument("--cv", action="append", default=[], metavar="FILE", help="CV PDF to parse and score; repeatable.")
    parser.add_argument("--extracted", action="append", default=[], metavar="FILE", help="Existing extracted candidate JSON; skips cv-parser; repeatable.")
    parser.add_argument("--position", default=None, help="Job title shown on reports (required unless --skip-reports).")
    parser.add_argument("--output-dir", default="data/pipeline_out", help="Directory for intermediate JSONs and reports (default data/pipeline_out).")
    parser.add_argument("--skip-reports", action="store_true", help="Score/rank only; skip PDF and Excel generation.")
    args = parser.parse_args()

    try:
        return _run_pipeline(args)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())