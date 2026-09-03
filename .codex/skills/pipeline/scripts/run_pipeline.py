"""CLI entry point for the pipeline skill (agent-facing).

Runs the full candidate screening pipeline in one command by chaining the
other skill CLIs: (optional PolyU import) -> jd-parser -> scorer build-config
-> cv-parser -> scorer score -> report-gen (PDF per candidate + Excel).

L1 phase 1: per-candidate isolation, retries, resume from output-dir, and a
need_input envelope when JD/CVs/position are missing.

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
import asyncio
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)
from screening_core.candidate_id import appno_from_filename, format_candidate_label, refno_from_url
from screening_core.board_tooltip import public_radar_dimensions
from screening_core.hr_output import RANKING_OVERVIEW_HTML, RESUME_LINKS_JSON, candidate_match_stem
from screening_core.input_policy import (
    ALLOWED_URL_HOSTS,
    extra_allowed_hosts_from_env,
    merge_allowed_hosts,
    validate_extracted_reference,
    validate_path,
    validate_reference,
)
from screening_core.job_state import load_job_state, save_job_state
from screening_core.report_fingerprint import (
    board_report_fingerprint,
    candidate_report_fingerprint,
    input_run_payload,
    jd_inputs_changed,
    load_fingerprints,
    save_fingerprints,
    sha256_file,
    sha256_text,
    stale_cv_slugs,
)
from jas_import.fetch import cv_filename_for_url, download_to_if_changed, fetch_jd_text

REPO_ROOT = _bootstrap.REPO_ROOT
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PYTHON = sys.executable

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2


# Raised when the run cannot start until the caller supplies missing inputs.
class NeedInputError(Exception):
    def __init__(self, missing: list[str], questions: list[str]) -> None:
        """Record which inputs are missing and the questions to ask the caller."""
        self.missing = missing
        self.questions = questions
        super().__init__(", ".join(missing))


# One per-candidate (or comparison-report) failure recorded in the manifest.
class Failure:
    def __init__(self, source: str, stage: str, attempts: int, error_message: str) -> None:
        """Store the failed source, pipeline stage, attempt count, and error text."""
        self.source = source
        self.stage = stage
        self.attempts = attempts
        self.error_message = error_message

    def to_dict(self) -> dict:
        """Return a JSON-serializable failure record."""
        return {
            "source": self.source,
            "stage": self.stage,
            "attempts": self.attempts,
            "error_message": self.error_message,
        }


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


def _run_with_retries(cmd: list[str], max_retries: int) -> tuple[int, str | None]:
    """Run a skill CLI up to 1 + max_retries times. Returns (attempts, error or None)."""
    attempts = 0
    last_error: str | None = None
    total = 1 + max(0, max_retries)
    for _ in range(total):
        attempts += 1
        try:
            _run(cmd)
            return attempts, None
        except RuntimeError as exc:
            last_error = str(exc)
    return attempts, last_error


def _load_json(path: Path) -> dict:
    """Load a JSON file tolerating a UTF-8 BOM."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _is_usable_json(path: Path) -> bool:
    """Return True when path exists and contains a JSON object."""
    if not path.is_file():
        return False
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict)


def _safe_name(name: str) -> str:
    """Return a filesystem-safe token derived from a candidate name."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_")
    return cleaned or "candidate"


# Deletes cached parse/score JSON for one candidate slug so it is rebuilt.
def _clear_candidate_artifacts(out_dir: Path, slug: str) -> None:
    """Remove extracted/score/detail JSON for a slug that must be parsed again."""
    for prefix in ("extracted-", "score-", "detail-"):
        (out_dir / f"{prefix}{slug}.json").unlink(missing_ok=True)


# Snapshot JD + CV bytes so --resume does not reuse stale parse/score JSON.
def _input_payload(args: argparse.Namespace) -> dict:
    """Hash the current JD files and CV/extracted files for resume invalidation."""
    jd_paths: list[Path | str | None] = [getattr(args, "jd_file", None), getattr(args, "jd_json", None)]
    used: set[str] = set()
    cv_hashes: dict[str, str] = {}
    for source in list(args.cv or []) + list(args.extracted or []):
        slug = _unique_slug(str(source), used)
        cv_hashes[slug] = sha256_file(source)
    return input_run_payload(
        engine=getattr(args, "engine", None),
        position=getattr(args, "position", None),
        refno=getattr(args, "refno", None),
        jd_paths=jd_paths,
        cv_hashes=cv_hashes,
    )


# Turn off --resume or drop per-CV cache when JD text or a CV file changed.
def _sync_resume_with_inputs(args: argparse.Namespace, out_dir: Path) -> None:
    """Keep --resume only when JD/engine match; rebuild CVs whose bytes changed."""
    payload = _input_payload(args)
    args._input_payload = payload
    previous = load_fingerprints(out_dir).get("input")
    prior = previous if isinstance(previous, dict) else {}
    args._inputs_unchanged = bool(prior) and prior == payload
    if not args.resume:
        return
    if jd_inputs_changed(prior, payload):
        args.resume = False
        args._inputs_unchanged = False
        (out_dir / "jd-parse.json").unlink(missing_ok=True)
        (out_dir / "config.json").unlink(missing_ok=True)
        return
    for slug in stale_cv_slugs(prior, payload):
        _clear_candidate_artifacts(out_dir, slug)
        args._inputs_unchanged = False


# Merge report + input fingerprints and write report-fingerprints.json.
def _persist_fingerprints(out_dir: Path, args: argparse.Namespace, extra: dict | None = None) -> None:
    """Write input and optional report fingerprints next to pipeline JSON."""
    data = load_fingerprints(out_dir)
    if extra:
        data.update(extra)
    payload = getattr(args, "_input_payload", None)
    if isinstance(payload, dict):
        data["input"] = payload
    save_fingerprints(out_dir, data)


def _unique_slug(source: str, used: set[str]) -> str:
    """Return a stable artifact slug from the source filename, unique within the run."""
    stem = _safe_name(Path(source).stem)
    slug = stem
    n = 2
    while slug in used:
        slug = f"{stem}_{n}"
        n += 1
    used.add(slug)
    return slug


def _radar_dim_score(dims: dict, dimension_id: str) -> float:
    """Return a numeric radar dimension score, treating inactive (None) dimensions as 0."""
    value = dims.get(dimension_id)
    return float(value) if value is not None else 0.0


def _record_failure(args: argparse.Namespace, failures: list[Failure], failure: Failure) -> None:
    """Append a failure; abort the batch immediately when --fail-fast is set."""
    failures.append(failure)
    if args.fail_fast:
        raise RuntimeError(failure.error_message)


# Rejects inline content and non-allowlisted references at the entry point.
def _enforce_input_policy(args: argparse.Namespace, out_dir: Path) -> None:
    for flag, value in (("--jd-file", args.jd_file), ("--jd-json", args.jd_json)):
        if value:
            validate_reference(value, flag=flag)
    for value in args.cv:
        validate_reference(value, flag="--cv")
    for value in args.extracted:
        validate_extracted_reference(value, out_dir=out_dir, trusted=args.trust_extracted, flag="--extracted")
    if args.polyu_detail_url:
        validate_reference(args.polyu_detail_url, flag="--polyu-detail-url")
    allowed_hosts = _effective_allowed_hosts(args)
    if args.jd_url:
        validate_reference(args.jd_url, flag="--jd-url", allowed_hosts=allowed_hosts)
    for value in args.cv_url:
        validate_reference(value, flag="--cv-url", allowed_hosts=allowed_hosts)
    if args.cookie_file:
        validate_path(args.cookie_file, flag="--cookie-file")


def _collect_need_input(args: argparse.Namespace) -> None:
    """Raise NeedInputError when JD, candidates, or report position are missing."""
    missing: list[str] = []
    questions: list[str] = []
    if not args.jd_file and not args.jd_json and not args.polyu_ref and not args.jd_url:
        missing.append("jd")
        questions.append("Provide a JD via --jd-file, --jd-json, --polyu-ref, or --jd-url.")
    if not args.cv and not args.extracted and not args.cv_url:
        missing.append("candidates")
        questions.append("Provide at least one CV (--cv), CV URL (--cv-url), or extracted profile (--extracted).")
    if not args.skip_reports and not args.position:
        missing.append("position")
        questions.append("Provide --position for reports, or pass --skip-reports.")
    if missing:
        raise NeedInputError(missing, questions)


def _resolve_jd_source(args: argparse.Namespace, out_dir: Path) -> tuple[Path, str | None]:
    """Return (jd JSON path for build-config/match, optional JD text for CV context)."""
    if args.polyu_ref:
        polyu_out = out_dir / "polyu-parsed.json"
        if args.resume and _is_usable_json(polyu_out):
            data = _load_json(polyu_out)
            return polyu_out, data.get("jd_text")
        cmd = [
            PYTHON,
            str(_skill_script("polyu-import", "run_polyu_import.py")),
            "fetch-and-parse",
            "--output",
            str(polyu_out),
            "--external-ref",
            args.polyu_ref,
        ]
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
        if not (args.resume and _is_usable_json(jd_parse_out)):
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


def _parse_candidates(
    args: argparse.Namespace, out_dir: Path, jd_text: str | None, failures: list[Failure]
) -> list[dict]:
    """Parse each CV (cv-parser) or reuse provided extracted profiles."""
    jd_context = None
    if jd_text:
        jd_context = out_dir / "jd-context.txt"
        jd_context.write_text(jd_text, encoding="utf-8")
    used_slugs: set[str] = set()
    candidates: list[dict] = []
    for cv in args.cv:
        source = str(cv)
        slug = _unique_slug(source, used_slugs)
        extracted_out = out_dir / f"extracted-{slug}.json"
        if args.resume and _is_usable_json(extracted_out):
            candidates.append(_with_identity(args, extracted_out, source, slug))
            continue
        cmd = [
            PYTHON,
            str(_skill_script("cv-parser", "run_cv_parse.py")),
            "--file",
            source,
            "--output",
            str(extracted_out),
        ]
        if jd_context:
            cmd += ["--jd-file", str(jd_context)]
        attempts, error = _run_with_retries(cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=source, stage="cv-parse", attempts=attempts, error_message=error),
            )
            continue
        candidates.append(_with_identity(args, extracted_out, source, slug))
    for ext in args.extracted:
        source = str(ext)
        slug = _unique_slug(source, used_slugs)
        candidates.append(_with_identity(args, Path(ext), source, slug))
    return candidates


# Attach the composite JAS key (refno, appno) used for ranking and reports.
def _with_identity(args: argparse.Namespace, extracted: Path, source: str, slug: str) -> dict:
    refno = getattr(args, "refno", None) or None
    appno = appno_from_filename(Path(source).stem, refno)
    return {
        "extracted": extracted,
        "source": source,
        "slug": slug,
        "refno": refno,
        "appno": appno,
        "display_label": format_candidate_label(refno, appno),
    }


def _score_legacy_candidate(
    args: argparse.Namespace, cand: dict, config_out: Path, out_dir: Path, failures: list[Failure]
) -> bool:
    """Score one candidate with the legacy engine. Returns True on success."""
    score_out = out_dir / f"score-{cand['slug']}.json"
    if args.resume and _is_usable_json(score_out):
        cand["score"] = score_out
        return True
    cmd = [
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
    attempts, error = _run_with_retries(cmd, args.max_retries)
    if error:
        _record_failure(
            args,
            failures,
            Failure(source=cand["source"], stage="score", attempts=attempts, error_message=error),
        )
        return False
    cand["score"] = score_out
    return True


def _legacy_row(cand: dict) -> dict:
    """Build a comparison/ranking row from a successfully scored legacy candidate."""
    score = _load_json(cand["score"])
    dims = score.get("dimension_scores") or {}
    snapshot = score.get("full_snapshot") or {}
    suggestions = snapshot.get("interview_suggestions") or score.get("interview_suggestions") or []
    return {
        "refno": cand.get("refno"),
        "appno": cand.get("appno"),
        "display_label": cand.get("display_label") or format_candidate_label(cand.get("refno"), cand.get("appno")),
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
        "_slug": cand["slug"],
    }


def _run_legacy_engine(
    args: argparse.Namespace,
    out_dir: Path,
    jd_source: Path,
    candidates: list[dict],
    failures: list[Failure],
) -> int:
    """Run build-config + score + rank + reports with the legacy ScorerService."""
    config_out = out_dir / "config.json"
    if not (args.resume and _is_usable_json(config_out)):
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
    rows: list[dict] = []
    for cand in candidates:
        if _score_legacy_candidate(args, cand, config_out, out_dir, failures):
            rows.append(_legacy_row(cand))
    rows.sort(key=lambda r: r["total_score"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    reports = _generate_reports(args, out_dir, rows, failures)
    return _build_manifest(args, out_dir, jd_source, config_out, rows, reports, failures, engine="legacy")


def _match_candidate(
    args: argparse.Namespace,
    cand: dict,
    jd_source: Path,
    reference_date: str,
    out_dir: Path,
    failures: list[Failure],
) -> dict | None:
    """Match one candidate. Returns a ranking row or None on failure."""
    detail_out = out_dir / f"detail-{cand['slug']}.json"
    if not (args.resume and _is_usable_json(detail_out)):
        cmd = [
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
        attempts, error = _run_with_retries(cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=cand["source"], stage="match", attempts=attempts, error_message=error),
            )
            return None
    detail = _load_json(detail_out)
    dims = {
        (d.get("dimension_id") or ""): d.get("score")
        for d in (detail.get("radar_dimensions") or [])
        if isinstance(d, dict)
    }
    questions = detail.get("interview_questions") or []
    suggestion_summary = "; ".join(
        f"{q.get('priority', '')}:{q.get('template_id', '')}" for q in questions[:3]
    )
    return {
        "refno": cand.get("refno"),
        "appno": cand.get("appno"),
        "display_label": cand.get("display_label") or format_candidate_label(cand.get("refno"), cand.get("appno")),
        "total_score": float(detail.get("match_score", 0)),
        "tier": detail.get("fit_band") or "",
        "skill_match": _radar_dim_score(dims, "core_skill_match"),
        "experience_match": _radar_dim_score(dims, "relevant_experience"),
        "education_match": _radar_dim_score(dims, "education_certification"),
        "suggestion_summary": suggestion_summary,
        "_extracted": cand["extracted"],
        "_detail": detail_out,
        "_source": cand["source"],
        "_slug": cand["slug"],
    }


def _run_matching_engine(
    args: argparse.Namespace,
    out_dir: Path,
    jd_source: Path,
    candidates: list[dict],
    failures: list[Failure],
) -> int:
    """Run the matching engine per candidate and render modal-style radar/interview PDFs."""
    reference_date = args.reference_date or date.today().isoformat()
    rows: list[dict] = []
    for cand in candidates:
        row = _match_candidate(args, cand, jd_source, reference_date, out_dir, failures)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r["total_score"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    reports = _generate_reports(args, out_dir, rows, failures)
    return _build_manifest(args, out_dir, jd_source, None, rows, reports, failures, engine="matching")


# Loads the optional appno -> online resume URL map written by the collector.
def _load_resume_links(out_dir: Path) -> dict[str, str]:
    path = out_dir / RESUME_LINKS_JSON
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value}


# Public ranking fields plus radar tooltip/interview numbers from matching detail (allow-listed reasoning only, no raw CV text).
def _board_row(row: dict, resume_links: dict[str, str] | None = None) -> dict:
    public = {key: value for key, value in row.items() if not str(key).startswith("_")}
    if resume_links and row.get("appno"):
        resume_url = resume_links.get(str(row.get("appno")))
        if resume_url:
            public["resume_url"] = str(resume_url)
    detail_path = row.get("_detail")
    if not detail_path:
        return public
    path = Path(detail_path)
    if not path.is_file():
        return public
    try:
        detail = _load_json(path)
    except (OSError, json.JSONDecodeError, TypeError):
        return public
    axes = public_radar_dimensions(detail)
    if axes:
        public["radar_dimensions"] = axes

    questions = []
    for item in detail.get("interview_questions") or []:
        if not isinstance(item, dict) or not item.get("question"):
            continue
        questions.append(
            {
                "priority": item.get("priority"),
                "question": str(item.get("question"))[:240],
            }
        )
    if questions:
        public["interview_questions"] = questions[:8]
    return public


# HR-facing report folder (ranking HTML/XLSX and <appno>.html/.pdf).
def _report_dir(args: argparse.Namespace, out_dir: Path) -> Path:
    raw = getattr(args, "report_dir", None)
    if not raw:
        return out_dir
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# Stable fingerprint for one candidate's PDF/HTML inputs (score JSON + rank).
def _row_report_fingerprint(args: argparse.Namespace, row: dict) -> str:
    return candidate_report_fingerprint(
        engine=getattr(args, "engine", None),
        position=args.position,
        refno=row.get("refno") or getattr(args, "refno", None),
        appno=row.get("appno"),
        rank=row.get("rank"),
        total_score=row.get("total_score"),
        tier=row.get("tier"),
        artifact_paths=[row.get("_detail"), row.get("_score"), row.get("_extracted")],
    )


def _generate_reports(
    args: argparse.Namespace, out_dir: Path, rows: list[dict], failures: list[Failure]
) -> dict:
    """Generate per-candidate HTML/PDF and ranking overview (unless skipped)."""
    reports: dict = {}
    if args.skip_reports:
        return reports
    report_dir = _report_dir(args, out_dir)
    previous = load_fingerprints(out_dir)
    previous_candidates = previous.get("candidates") if isinstance(previous.get("candidates"), dict) else {}
    candidate_fps: dict[str, str] = {}
    for row in rows:
        stem = candidate_match_stem(row.get("appno") or row.get("display_label") or row["rank"])
        pdf_out = report_dir / f"{stem}.pdf"
        match_html = report_dir / f"{stem}.html"
        fingerprint = _row_report_fingerprint(args, row)
        candidate_fps[stem] = fingerprint
        reusable = (
            previous_candidates.get(stem) == fingerprint
            and pdf_out.is_file()
            and match_html.is_file()
        )
        if reusable:
            row["_pdf"] = pdf_out
            row["_report_reused"] = True
            continue
        cmd = [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "candidate",
            "--extracted",
            str(row["_extracted"]),
            "--position",
            args.position,
            "--rank",
            str(row["rank"]),
            "--output",
            str(pdf_out),
        ]
        if row.get("refno"):
            cmd += ["--refno", str(row["refno"])]
        if row.get("appno"):
            cmd += ["--appno", str(row["appno"])]
        if row.get("_detail"):
            cmd += ["--detail", str(row["_detail"])]
        else:
            cmd += ["--score", str(row["_score"])]
        attempts, error = _run_with_retries(cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=row["_source"], stage="report-gen", attempts=attempts, error_message=error),
            )
            continue
        row["_pdf"] = pdf_out
    if not rows:
        return reports
    resume_links = _load_resume_links(out_dir)
    comparison_rows = [_board_row(row, resume_links) for row in rows]
    html_out = report_dir / RANKING_OVERVIEW_HTML
    board_fp = board_report_fingerprint(
        position=args.position,
        refno=getattr(args, "refno", None),
        candidate_fingerprints=candidate_fps,
        resume_links_digest=sha256_text(json.dumps(resume_links, sort_keys=True, ensure_ascii=False)),
    )
    reuse_board = previous.get("board") == board_fp and html_out.is_file()
    if reuse_board:
        reports["ranking_overview_html"] = str(html_out)
        reports["screening_board_html"] = str(html_out)
    else:
        rows_out = out_dir / "rows.json"
        rows_out.write_text(json.dumps(comparison_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        html_cmd = [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "board",
            "--position",
            args.position,
            "--rows",
            str(rows_out),
            "--output",
            str(html_out),
        ]
        if getattr(args, "refno", None):
            html_cmd += ["--refno", str(args.refno)]
        attempts, error = _run_with_retries(html_cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=str(html_out), stage="report-gen", attempts=attempts, error_message=error),
            )
        else:
            reports["ranking_overview_html"] = str(html_out)
            reports["screening_board_html"] = str(html_out)
    for row, public in zip(rows, comparison_rows):
        if row.get("_report_reused"):
            continue
        stem = candidate_match_stem(row.get("appno") or public.get("appno") or row.get("rank"))
        match_html = report_dir / f"{stem}.html"
        row_path = out_dir / f"board-row-{stem}.json"
        row_path.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
        match_cmd = [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "match-html",
            "--position",
            args.position,
            "--row",
            str(row_path),
            "--output",
            str(match_html),
        ]
        attempts, error = _run_with_retries(match_cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=str(match_html), stage="report-gen", attempts=attempts, error_message=error),
            )
    reused = sum(1 for row in rows if row.get("_report_reused"))
    reports["reused_pdf_count"] = reused
    reports["generated_pdf_count"] = max(0, len(rows) - reused)
    reports["inputs_unchanged"] = bool(getattr(args, "_inputs_unchanged", False) and reuse_board and reused == len(rows))
    _persist_fingerprints(
        out_dir,
        args,
        {"candidates": candidate_fps, "board": board_fp},
    )
    return reports


def _build_manifest(
    args: argparse.Namespace,
    out_dir: Path,
    jd_source: Path,
    config_out: Path | None,
    rows: list[dict],
    reports: dict,
    failures: list[Failure],
    engine: str,
) -> int:
    """Print the pipeline result manifest to stdout and write manifest.json."""
    if rows and not failures:
        status = "success"
        exit_code = EXIT_OK
    elif rows and failures:
        status = "partial_success"
        exit_code = EXIT_OK
    else:
        status = "error"
        exit_code = EXIT_ERROR
    manifest_rows = []
    for row in rows:
        manifest_rows.append(
            {
                "rank": row["rank"],
                "refno": row.get("refno"),
                "appno": row.get("appno"),
                "display_label": row.get("display_label"),
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
        "status": status,
        "engine": engine,
        "refno": args.refno,
        "output_dir": str(out_dir),
        "jd_source": str(jd_source),
        "config_json": str(config_out) if config_out else None,
        "candidates": manifest_rows,
        "failures": [item.to_dict() for item in failures],
        "ask": None,
        "reports": reports,
        "inputs_unchanged": bool((reports or {}).get("inputs_unchanged")),
    }
    _persist_fingerprints(out_dir, args)
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    (out_dir / "manifest.json").write_text(text + "\n", encoding="utf-8")
    stream = sys.stdout if exit_code == EXIT_OK else sys.stderr
    print(text, file=stream)
    return exit_code


# Resolves a private scratch directory for downloaded files.
def _resolve_scratch_dir(scratch_dir: str) -> Path:
    path = Path(scratch_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# Fetches URL inputs into local files and returns downloaded CV paths.
# Build the effective URL host allowlist: defaults + env + --allow-host flags.
def _effective_allowed_hosts(args: argparse.Namespace) -> tuple[str, ...]:
    extra = tuple(getattr(args, "allow_host", []) or [])
    return merge_allowed_hosts(ALLOWED_URL_HOSTS, extra_allowed_hosts_from_env(), extra)


# Resolve the job-state directory (default repo data/jas_state).
def _resolve_state_dir(args: argparse.Namespace) -> Path:
    raw = getattr(args, "state_dir", None) or "data/jas_state"
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _resolve_url_inputs(args: argparse.Namespace, out_dir: Path) -> list[Path]:
    downloaded_cvs: list[Path] = []
    allowed_hosts = _effective_allowed_hosts(args)
    base_url = getattr(args, "base_url", None)
    if args.jd_url:
        jd_text = asyncio.run(
            fetch_jd_text(args.jd_url, cookie_file=args.cookie_file, base_url=base_url, allowed_hosts=allowed_hosts)
        )
        dest = out_dir / "jd-from-url.txt"
        dest.write_text(jd_text, encoding="utf-8")
        args.jd_file = str(dest)
    if args.cv_url:
        scratch = _resolve_scratch_dir(args.scratch_dir)
        refno = getattr(args, "refno", None) or "job"
        state_dir = _resolve_state_dir(args)
        prev_cv_meta = load_job_state(state_dir, refno).get("cv_meta") or {}
        cv_meta: dict[str, dict[str, str]] = {}
        for url in args.cv_url:
            dest = scratch / cv_filename_for_url(url)
            prev_meta = prev_cv_meta.get(url) or {}
            downloaded, new_meta = asyncio.run(
                download_to_if_changed(
                    url,
                    dest,
                    cookie_file=args.cookie_file,
                    allowed_hosts=allowed_hosts,
                    etag=prev_meta.get("etag") if dest.is_file() else None,
                    last_modified=prev_meta.get("last_modified") if dest.is_file() else None,
                )
            )
            cv_meta[url] = new_meta if downloaded else prev_meta
            args.cv.append(str(dest))
            downloaded_cvs.append(dest)
        state = load_job_state(state_dir, refno)
        state["cv_meta"] = cv_meta
        save_job_state(state_dir, refno, state)
    return downloaded_cvs


def _run_pipeline(args: argparse.Namespace) -> int:
    """Execute every pipeline step and print a result manifest to stdout."""
    if args.polyu_detail_url and not args.polyu_ref:
        raise RuntimeError("--polyu-detail-url is only valid together with --polyu-ref")

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    _enforce_input_policy(args, out_dir)
    if not args.refno:
        args.refno = refno_from_url(getattr(args, "jd_url", None)) or getattr(args, "polyu_ref", None)
    _collect_need_input(args)
    downloaded_cvs = _resolve_url_inputs(args, out_dir)
    _sync_resume_with_inputs(args, out_dir)
    try:
        failures: list[Failure] = []
        jd_source, jd_text = _resolve_jd_source(args, out_dir)
        candidates = _parse_candidates(args, out_dir, jd_text, failures)
        if args.engine == "matching":
            return _run_matching_engine(args, out_dir, jd_source, candidates, failures)
        return _run_legacy_engine(args, out_dir, jd_source, candidates, failures)
    finally:
        if getattr(args, "cleanup_cvs", False):
            for path in downloaded_cvs:
                path.unlink(missing_ok=True)


def _print_need_input(exc: NeedInputError) -> int:
    """Print a need_input envelope for the L1 agent and return exit code 2."""
    payload = {
        "status": "need_input",
        "missing": exc.missing,
        "questions": exc.questions,
        "ask": {"missing": exc.missing, "questions": exc.questions},
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_NEED_INPUT


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full candidate screening pipeline end-to-end.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--jd-file", default=None, help="JD text file; parsed with the jd-parser skill.")
    source.add_argument("--jd-json", default=None, help="Existing parsed JD JSON (jd-parser output, polyu-parsed output, or pure structured_data).")
    source.add_argument("--polyu-ref", default=None, help="PolyU external ref; fetched and parsed with the polyu-import skill.")
    source.add_argument("--jd-url", default=None, help="JAS records page URL to fetch and parse as JD text.")
    parser.add_argument("--polyu-detail-url", default=None, help="PolyU detail URL fallback used with --polyu-ref.")
    parser.add_argument("--engine", choices=("legacy", "matching"), default="legacy", help="Scoring engine: legacy scorer (default) or matching engine with radar/interview detail.")
    parser.add_argument("--reference-date", default=None, help="Reference date YYYY-MM-DD used by the matching engine (default: today).")
    parser.add_argument("--cv", action="append", default=[], metavar="FILE", help="CV PDF to parse and score; repeatable.")
    parser.add_argument("--cv-url", action="append", default=[], metavar="URL", help="JAS CV file URL to download (repeatable).")
    parser.add_argument("--extracted", action="append", default=[], metavar="FILE", help="Existing extracted candidate JSON; skips cv-parser; repeatable.")
    parser.add_argument("--trust-extracted", action="store_true", help="Allow --extracted profiles from outside --output-dir (trusted, pre-masked data only).")
    parser.add_argument("--cookie-file", default=None, help="Local Netscape cookies.txt used for authenticated JAS fetches.")
    parser.add_argument("--no-cookie", action="store_true", help="Allow unauthenticated JAS fetches for public demo hosts.")
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="Extra allowlisted URL host (repeatable; public demo hosts).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL for CV link resolution in fetched pages (public demo).",
    )
    parser.add_argument("--scratch-dir", default="data/jas_scratch", help="Directory for downloaded CV files.")
    parser.add_argument(
        "--cleanup-cvs",
        action="store_true",
        help="Delete CVs downloaded from --cv-url after the run (default keeps them for reuse).",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Directory for per-refno job state (CV hashes/metadata; default repo data/jas_state).",
    )
    parser.add_argument("--position", default=None, help="Job title shown on reports (required unless --skip-reports).")
    parser.add_argument("--refno", default=None, help="Job reference number; together with application no. identifies a candidate (names are never shown).")
    parser.add_argument("--output-dir", default="data/pipeline_out", help="Directory for intermediate JSONs (default data/pipeline_out).")
    parser.add_argument("--report-dir", default=None, help="HR-facing report folder for ranking-overview.html and <appno>.html/.pdf (default: same as --output-dir).")
    parser.add_argument("--skip-reports", action="store_true", help="Score/rank only; skip HTML/PDF/Excel (do not use for HR runs).")
    parser.add_argument("--max-retries", type=int, default=2, metavar="N", help="Retries per candidate step after the first attempt (default 2).")
    parser.add_argument("--resume", action="store_true", help="Skip JD/CV/score steps when usable artifacts already exist in --output-dir.")
    parser.add_argument("--fail-fast", action="store_true", help="Abort the batch on the first per-candidate failure (legacy behavior).")
    args = parser.parse_args()

    try:
        return _run_pipeline(args)
    except NeedInputError as exc:
        return _print_need_input(exc)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
