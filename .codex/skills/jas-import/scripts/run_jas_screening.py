"""CLI: run JAS screening from an HR-exported folder or a records URL.

Folder mode expects:
    <jas-dir>/
        records.html            (saved records.php?refno=... page)
        cvs/123456.pdf          (CV PDFs named by Application no.)

URL mode (--records-url) fetches the records page, downloads each
candidate CV to a private scratch dir, and runs the same pipeline tail.

It parses the JD via jas-import, then delegates to the pipeline skill so
JD parse -> build-config -> cv parse -> score/rank -> reports stay unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from jas_import.fetch import download_to, fetch_job_payload
from jas_import.skill import parse_job_skill
from screening_core.input_policy import validate_path, validate_reference

REPO_ROOT = _bootstrap.REPO_ROOT
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PYTHON = sys.executable

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2

RECORDS_HTML_NAMES = ("records.html", "Job Application Recordsrecords.html", "records.php.html")
DEFAULT_CVS_DIR = "cvs"
CV_SUFFIXES = (".pdf", ".doc", ".docx")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


# Returns a path to a skill CLI script.
def _skill_script(skill: str, script: str) -> Path:
    path = SKILLS_DIR / skill / "scripts" / script
    if not path.is_file():
        raise RuntimeError(f"skill script not found: {path}")
    return path


# Resolves the records.html path from an explicit flag or the JAS folder.
def _resolve_records_html(jas_dir: Path, records_html: str | None) -> Path:
    if records_html:
        path = Path(records_html)
        if not path.is_absolute():
            path = jas_dir / path
        if not path.is_file():
            raise FileNotFoundError(f"records.html not found: {path}")
        return path
    for name in RECORDS_HTML_NAMES:
        candidate = jas_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"records.html not found under {jas_dir}")


# Maps one CV filename stem to an application no. (accepts <appno> or <refno>_<appno>).
def _appno_from_filename(stem: str, refno: str) -> str:
    name = stem
    prefix = f"{refno}_"
    if name.startswith(prefix):
        name = name[len(prefix):]
    match = re.fullmatch(r"(\d+)", name)
    return match.group(1) if match else name


# Discovers CV files in the cvs dir plus any extra --cv paths.
def _discover_cvs(jas_dir: Path, cvs_dir: str | None, extra_cvs: list[str], refno: str) -> list[tuple[str, Path]]:
    base = jas_dir / (cvs_dir or DEFAULT_CVS_DIR)
    found: list[tuple[str, Path]] = []
    if base.is_dir():
        for path in sorted(base.iterdir()):
            if path.is_file() and path.suffix.lower() in CV_SUFFIXES:
                found.append((_appno_from_filename(path.stem, refno), path))
    for item in extra_cvs:
        path = Path(item)
        if not path.is_absolute():
            path = jas_dir / path
        found.append((_appno_from_filename(path.stem, refno), path))
    return found


# Builds the pipeline command for one JAS job folder.
def _pipeline_cmd(
    jd_text_path: Path,
    cv_paths: list[Path],
    position: str,
    out_dir: Path,
    engine: str,
    max_retries: int,
    skip_reports: bool,
    resume: bool,
    fail_fast: bool,
) -> list[str]:
    cmd = [
        PYTHON,
        str(_skill_script("pipeline", "run_pipeline.py")),
        "--jd-file",
        str(jd_text_path),
        "--position",
        position,
        "--output-dir",
        str(out_dir),
        "--engine",
        engine,
        "--max-retries",
        str(max_retries),
    ]
    if skip_reports:
        cmd.append("--skip-reports")
    if resume:
        cmd.append("--resume")
    if fail_fast:
        cmd.append("--fail-fast")
    for path in cv_paths:
        cmd += ["--cv", str(path)]
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


# Resolves output-dir into an absolute path and ensures it exists.
def _resolve_output_dir(output_dir: str) -> Path:
    path = Path(output_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# Builds the PII-free JAS manifest for one folder.
def _build_manifest(
    job: dict,
    cvs: list[tuple[str, Path]],
    *,
    download_failures: list[dict] | None = None,
) -> dict:
    status_by_appno = {candidate["appno"]: candidate.get("status") for candidate in job.get("candidates", [])}
    known_appnos = {candidate["appno"] for candidate in job.get("candidates", [])}
    entries = [
        {"appno": appno, "status": status_by_appno.get(appno), "cv_path": str(path)}
        for appno, path in cvs
    ]
    missing_cv = sorted(known_appnos - {appno for appno, _ in cvs})
    manifest = {
        "source": "jas",
        "refno": job.get("refno", ""),
        "post_title": (job.get("job") or {}).get("post_title", ""),
        "candidates": entries,
        "candidates_without_cv": missing_cv,
    }
    if download_failures:
        manifest["download_failures"] = download_failures
    return manifest


# Runs the shared pipeline tail for a parsed job plus resolved CV paths.
def _run_screening(
    job: dict,
    cvs: list[tuple[str, Path]],
    args: argparse.Namespace,
    *,
    download_failures: list[dict] | None = None,
) -> int:
    position = (job.get("job") or {}).get("post_title") or ""
    out_dir = _resolve_output_dir(args.output_dir)
    jd_text_path = out_dir / "jd.txt"
    jd_text_path.write_text(job.get("jd_text", ""), encoding="utf-8")

    manifest = _build_manifest(job, cvs, download_failures=download_failures)
    (out_dir / "jas-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = _pipeline_cmd(
        jd_text_path,
        [path for _, path in cvs],
        position,
        out_dir,
        args.engine,
        args.max_retries,
        args.skip_reports,
        args.resume,
        args.fail_fast,
    )
    exit_code, payload = _run_pipeline(cmd)
    if download_failures:
        payload = dict(payload)
        payload["download_failures"] = download_failures
    if exit_code != 0:
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return exit_code


# Orchestrates one offline JAS job folder through the pipeline.
def run_jas_screening(jas_dir: Path, args: argparse.Namespace) -> int:
    if not jas_dir.is_absolute():
        jas_dir = REPO_ROOT / jas_dir

    try:
        records = _resolve_records_html(jas_dir, args.records_html)
        job = parse_job_skill(records)
    except FileNotFoundError as exc:
        print(
            json.dumps(
                {
                    "status": "need_input",
                    "missing": ["records_html"],
                    "questions": ["Place the HR-exported records.html inside the JAS folder."],
                    "detail": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return EXIT_NEED_INPUT

    refno = job.get("refno") or "job"
    cvs = _discover_cvs(jas_dir, args.cvs_dir, args.cv, refno)
    if not cvs:
        print(
            json.dumps(
                {
                    "status": "need_input",
                    "missing": ["cvs"],
                    "questions": ["Place candidate CV PDFs (named <appno>.pdf) in the cvs/ folder."],
                },
                ensure_ascii=False,
            )
        )
        return EXIT_NEED_INPUT
    return _run_screening(job, cvs, args)


# Resolves the private scratch root for downloaded CVs.
def _resolve_scratch_root(scratch_dir: str) -> Path:
    path = Path(scratch_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# Validates an identifier before using it in a scratch path.
def _safe_identifier(value: object, *, label: str) -> str:
    text = str(value or "")
    if not SAFE_IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"invalid {label} for scratch path")
    return text


# Deletes a downloaded CV scratch subdir, refusing anything outside the scratch root.
def _remove_scratch_dir(scratch_job: Path, scratch_root: Path) -> None:
    job = scratch_job.resolve()
    root = scratch_root.resolve()
    try:
        job.relative_to(root)
    except ValueError:
        return
    if job == root:
        return
    shutil.rmtree(job, ignore_errors=True)


# Orchestrates live JAS screening from a records URL (downloads CVs to scratch).
def run_url_screening(args: argparse.Namespace) -> int:
    try:
        validate_reference(args.records_url, flag="--records-url")
        if args.cookie_file:
            validate_path(args.cookie_file, flag="--cookie-file")
    except Exception as exc:
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    try:
        job = asyncio.run(fetch_job_payload(args.records_url, cookie_file=args.cookie_file))
    except Exception as exc:
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR

    try:
        refno = _safe_identifier(job.get("refno") or "job", label="reference number")
    except ValueError as exc:
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    scratch_root = _resolve_scratch_root(args.scratch_dir)
    scratch_job = scratch_root / refno
    scratch_job.mkdir(parents=True, exist_ok=True)

    try:
        cvs: list[tuple[str, Path]] = []
        download_failures: list[dict] = []
        for candidate in job.get("candidates", []):
            raw_appno = candidate.get("appno")
            cv_url = candidate.get("cv_url")
            if not raw_appno:
                continue
            try:
                appno = _safe_identifier(raw_appno, label="application number")
                validate_reference(cv_url, flag="candidate cv_url")
            except Exception as exc:
                download_failures.append({"appno": str(raw_appno), "error_message": str(exc)})
                continue
            dest = scratch_job / f"{appno}.pdf"
            if args.resume and dest.is_file():
                cvs.append((appno, dest))
                continue
            try:
                asyncio.run(download_to(cv_url, dest, cookie_file=args.cookie_file))
                cvs.append((appno, dest))
            except Exception as exc:
                download_failures.append({"appno": appno, "error_message": str(exc)})

        if not cvs:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error_message": "no candidate CVs could be downloaded",
                        "download_failures": download_failures,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return EXIT_ERROR
        return _run_screening(job, cvs, args, download_failures=download_failures or None)
    finally:
        if not args.keep_cvs:
            _remove_scratch_dir(scratch_job, scratch_root)


# Builds the argparse CLI for the offline JAS screening flow.
def main() -> int:
    parser = argparse.ArgumentParser(description="Run JAS screening from an HR-exported folder or a records URL.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--jas-dir", default=None, help="HR-exported JAS folder (records.html + cvs/).")
    source.add_argument("--records-url", default=None, help="JAS records page URL; CVs are downloaded automatically.")
    parser.add_argument("--records-html", default=None, help="Optional explicit path to records.html.")
    parser.add_argument("--cvs-dir", default=None, help="CV folder name inside jas-dir (default cvs).")
    parser.add_argument("--cv", action="append", default=[], metavar="FILE", help="Extra CV files outside the folder.")
    parser.add_argument("--cookie-file", default=None, help="Local Netscape cookies.txt for authenticated fetches.")
    parser.add_argument("--keep-cvs", action="store_true", help="Keep downloaded CVs in --scratch-dir after the run.")
    parser.add_argument("--scratch-dir", default="data/jas_scratch", help="Root directory for downloaded CVs.")
    parser.add_argument("--output-dir", default="data/jas_out", help="Output directory shared with pipeline.")
    parser.add_argument("--engine", choices=("legacy", "matching"), default="legacy", help="Scoring engine.")
    parser.add_argument("--skip-reports", action="store_true", help="Score/rank only; skip PDF/Excel.")
    parser.add_argument("--resume", action="store_true", help="Reuse usable artifacts already in --output-dir.")
    parser.add_argument("--fail-fast", action="store_true", help="Abort the batch on the first per-candidate failure.")
    parser.add_argument("--max-retries", type=int, default=2, help="Extra attempts per candidate step.")
    args = parser.parse_args()
    if args.records_url:
        return run_url_screening(args)
    return run_jas_screening(Path(args.jas_dir), args)


if __name__ == "__main__":
    raise SystemExit(main())