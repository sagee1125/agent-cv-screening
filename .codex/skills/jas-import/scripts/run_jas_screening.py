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
from urllib.parse import unquote, urlparse

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from jas_import.fetch import download_to, fetch_job_payload
from jas_import.skill import parse_job_skill
from screening_core.candidate_id import appno_from_filename, is_jas_refno, records_url_for_refno, refno_from_url
from screening_core.hr_output import (
    HR_PACK_FOLDER,
    RANKING_OVERVIEW_HTML,
    open_hr_file,
    pipeline_work_dir,
    resolve_hr_job_dir,
    safe_pack_id,
)
from screening_core.report_fingerprint import FINGERPRINTS_NAME
from screening_core.input_policy import (
    ALLOWED_URL_HOSTS,
    extra_allowed_hosts_from_env,
    merge_allowed_hosts,
    validate_path,
    validate_reference,
)

REPO_ROOT = _bootstrap.REPO_ROOT
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PYTHON = sys.executable

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2

RECORDS_HTML_NAMES = ("records.html", "Job Application Recordsrecords.html", "records.php.html")
DEFAULT_CVS_DIR = "cvs"
CV_DIR_CANDIDATES = ("cvs", "uploads")
CV_SUFFIXES = (".pdf", ".doc", ".docx")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ASK_REFNO = (
    "Please send the job reference number, or paste the internal job records page link.",
    "請發送崗位參考編號，或貼上內部招聘記錄頁的連結。",
)
ASK_JAS_SESSION = (
    "Please allow access to the internal job records page so this screening can continue.",
    "請允許存取內部招聘記錄頁，以便繼續篩選。",
)
ASK_JD = (
    "Save the job records page as HTML in the folder, then try again.",
    "請將崗位記錄頁存成 HTML 放到該資料夾後再試。",
)
ASK_CANDIDATES = (
    "Add each applicant CV as a PDF named with the application number.",
    "請將每位申請人的 CV 存成以申請編號命名的 PDF。",
)


# Build the effective URL host allowlist: defaults + env + --allow-host flags.
def _effective_allowed_hosts(args: argparse.Namespace) -> tuple[str, ...]:
    extra = tuple(getattr(args, "allow_host", []) or [])
    return merge_allowed_hosts(ALLOWED_URL_HOSTS, extra_allowed_hosts_from_env(), extra)


# Build the records URL for a refno, honoring a demo --base-url.
def build_records_url_for_refno(refno: str, base_url: str | None) -> str:
    if base_url:
        return f"{base_url.rstrip('/')}/records.html?refno={refno.strip()}"
    return records_url_for_refno(refno)


# Prints a host-projectable need_input envelope and returns exit code 2.
def _print_need_input(missing: list[str], questions: list[str], **extra: object) -> int:
    payload = {
        "status": "need_input",
        "missing": missing,
        "questions": questions,
        "ask": {"missing": missing, "questions": questions},
        **extra,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return EXIT_NEED_INPUT


# True when a live fetch failed because the JAS session is missing or expired.
def _is_auth_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "401" in text or "403" in text or "unauthorized" in text or "forbidden" in text:
        return True
    status = getattr(exc, "response", None)
    code = getattr(status, "status_code", None)
    return code in {401, 403}


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
    return appno_from_filename(stem, refno)


# Map local CV filenames in records.html (e.g. CV_Name.pdf) back to application no.
def _appno_by_cv_filename(job: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for candidate in job.get("candidates") or []:
        appno = str(candidate.get("appno") or "").strip()
        url = str(candidate.get("cv_url") or "").strip()
        if not appno or not url:
            continue
        name = Path(unquote(urlparse(url).path)).name.lower()
        if name:
            mapping[name] = appno
    return mapping


# Prefer cvs/, then uploads/, when HR did not pass --cvs-dir.
def _resolve_cvs_dir(jas_dir: Path, cvs_dir: str | None) -> Path:
    if cvs_dir:
        return jas_dir / cvs_dir
    for name in CV_DIR_CANDIDATES:
        candidate = jas_dir / name
        if not candidate.is_dir():
            continue
        if any(path.is_file() and path.suffix.lower() in CV_SUFFIXES for path in candidate.iterdir()):
            return candidate
    return jas_dir / DEFAULT_CVS_DIR


# Discovers CV files in the cvs/uploads dir plus any extra --cv paths.
def _discover_cvs(
    jas_dir: Path,
    cvs_dir: str | None,
    extra_cvs: list[str],
    refno: str,
    job: dict | None = None,
) -> list[tuple[str, Path]]:
    url_map = _appno_by_cv_filename(job or {})
    base = _resolve_cvs_dir(jas_dir, cvs_dir)
    found: list[tuple[str, Path]] = []
    if base.is_dir():
        for path in sorted(base.iterdir()):
            if path.is_file() and path.suffix.lower() in CV_SUFFIXES:
                appno = url_map.get(path.name.lower()) or _appno_from_filename(path.stem, refno)
                found.append((appno, path))
    for item in extra_cvs:
        path = Path(item)
        if not path.is_absolute():
            path = jas_dir / path
        appno = url_map.get(path.name.lower()) or _appno_from_filename(path.stem, refno)
        found.append((appno, path))
    return found


# Copy CVs to <appno>.pdf so reports never inherit personal-name filenames.
def _stage_cvs_by_appno(work_dir: Path, cvs: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    staged_dir = work_dir / "staged_cvs"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[str, Path]] = []
    for appno, src in cvs:
        stem = safe_pack_id(appno, fallback="unknown")
        dest = staged_dir / f"{stem}{src.suffix.lower() or '.pdf'}"
        shutil.copy2(src, dest)
        staged.append((stem, dest))
    return staged


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
    refno: str | None = None,
    report_dir: Path | None = None,
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
    if report_dir is not None:
        cmd += ["--report-dir", str(report_dir)]
    if refno:
        cmd += ["--refno", str(refno)]
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
    refno = str(job.get("refno") or "") or None
    skip_reports = False
    job_dir = resolve_hr_job_dir(args.output_dir, refno, repo_root=REPO_ROOT)
    work_dir = pipeline_work_dir(job_dir)
    # Reuse parse/score JSON on a later run of the same job folder.
    if (work_dir / FINGERPRINTS_NAME).is_file() or (work_dir / "manifest.json").is_file() or (work_dir / "jas-manifest.json").is_file():
        args.resume = True
    jd_text_path = work_dir / "jd.txt"
    jd_text_path.write_text(job.get("jd_text", ""), encoding="utf-8")

    staged = _stage_cvs_by_appno(work_dir, cvs)
    manifest = _build_manifest(job, staged, download_failures=download_failures)
    (work_dir / "jas-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = _pipeline_cmd(
        jd_text_path,
        [path for _, path in staged],
        position,
        work_dir,
        args.engine,
        args.max_retries,
        skip_reports,
        args.resume,
        args.fail_fast,
        refno=refno,
        report_dir=job_dir,
    )
    exit_code, payload = _run_pipeline(cmd)
    hr_files = (
        f"Desktop/{HR_PACK_FOLDER}/{job_dir.name}"
        if job_dir.parent.name == HR_PACK_FOLDER
        else str(job_dir)
    )
    payload = dict(payload)
    payload["hr_files"] = hr_files
    if download_failures:
        payload["download_failures"] = download_failures
    if exit_code != 0:
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        print(json.dumps(payload, ensure_ascii=False))
    if exit_code == 0 and not skip_reports and not getattr(args, "no_open", False):
        overview = job_dir / RANKING_OVERVIEW_HTML
        open_hr_file(overview)
    return exit_code


# Orchestrates one offline JAS job folder through the pipeline.
def run_jas_screening(jas_dir: Path, args: argparse.Namespace) -> int:
    if not jas_dir.is_absolute():
        jas_dir = REPO_ROOT / jas_dir

    try:
        records = _resolve_records_html(jas_dir, args.records_html)
        job = parse_job_skill(records)
    except FileNotFoundError as exc:
        return _print_need_input(["jd"], list(ASK_JD), detail=str(exc))

    refno = job.get("refno") or "job"
    cvs = _discover_cvs(jas_dir, args.cvs_dir, args.cv, refno, job)
    if not cvs:
        return _print_need_input(["candidates"], list(ASK_CANDIDATES))
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
    allowed_hosts = _effective_allowed_hosts(args)
    base_url = getattr(args, "base_url", None)
    try:
        validate_reference(args.records_url, flag="--records-url", allowed_hosts=allowed_hosts)
        if args.cookie_file:
            validate_path(args.cookie_file, flag="--cookie-file")
    except Exception as exc:
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    try:
        job = asyncio.run(
            fetch_job_payload(args.records_url, cookie_file=args.cookie_file, base_url=base_url, allowed_hosts=allowed_hosts)
        )
    except Exception as exc:
        if _is_auth_failure(exc):
            return _print_need_input(["jas_session"], list(ASK_JAS_SESSION))
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
                validate_reference(cv_url, flag="candidate cv_url", allowed_hosts=allowed_hosts)
            except Exception as exc:
                download_failures.append({"appno": str(raw_appno), "error_message": str(exc)})
                continue
            dest = scratch_job / f"{appno}.pdf"
            if args.resume and dest.is_file():
                cvs.append((appno, dest))
                continue
            try:
                asyncio.run(download_to(cv_url, dest, cookie_file=args.cookie_file, allowed_hosts=allowed_hosts))
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


# Returns True when the value is a records URL rather than a local folder.
def _looks_like_records_url(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith(("http://", "https://", "www.")) or "jobs.polyu.edu.hk" in text or "records.php" in text


# Add https:// when the HR pasted www... without a scheme.
def _normalize_records_url(value: str) -> str:
    text = value.strip()
    if text.lower().startswith(("http://", "https://")):
        return text
    return "https://" + text.lstrip("/")


# Builds the argparse CLI for the offline JAS screening flow.
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Screen a JAS folder or records URL. Writes HTML/PDF and opens ranking-overview.html."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Exported JAS folder or records URL. Same as --jas-dir / --records-url.",
    )
    parser.add_argument("--jas-dir", default=None, help="HR-exported JAS folder (records.html + cvs/).")
    parser.add_argument("--records-url", default=None, help="JAS records page URL; CVs are downloaded automatically.")
    parser.add_argument(
        "--refno",
        default=None,
        help="Job reference number. Builds the internal records URL when no folder or URL is given.",
    )
    parser.add_argument("--records-html", default=None, help="Optional explicit path to records.html.")
    parser.add_argument("--cvs-dir", default=None, help="CV folder name inside jas-dir (default cvs).")
    parser.add_argument("--cv", action="append", default=[], metavar="FILE", help="Extra CV files outside the folder.")
    parser.add_argument("--cookie-file", default=None, help="Local Netscape cookies.txt for authenticated fetches.")
    parser.add_argument("--no-cookie", action="store_true", help="Allow unauthenticated --records-url fetches for public demo hosts.")
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
        help="Base URL for CV link resolution and refno URL building (public demo).",
    )
    parser.add_argument("--keep-cvs", action="store_true", help="Keep downloaded CVs in --scratch-dir after the run.")
    parser.add_argument("--scratch-dir", default="data/jas_scratch", help="Root directory for downloaded CVs.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Parent folder for the HR pack. Default: Desktop/workbuddy-cv-screen/<refno>/",
    )
    parser.add_argument(
        "--engine",
        choices=("legacy", "matching"),
        default="matching",
        help="Scoring engine (default matching: Candidate Match PDF with radar).",
    )
    parser.add_argument(
        "--skip-reports",
        action="store_true",
        help="Score/rank only; skip HTML/PDF/Excel. Do not use for HR.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open ranking-overview.html after a successful run.",
    )
    parser.add_argument("--resume", action="store_true", help="Reuse usable artifacts already in --output-dir.")
    parser.add_argument("--fail-fast", action="store_true", help="Abort the batch on the first per-candidate failure.")
    parser.add_argument("--max-retries", type=int, default=2, help="Extra attempts per candidate step.")
    args = parser.parse_args()
    if args.target:
        if args.jas_dir or args.records_url:
            parser.error("use either a positional folder/URL or --jas-dir/--records-url, not both")
        if _looks_like_records_url(args.target):
            args.records_url = _normalize_records_url(args.target)
        elif is_jas_refno(args.target):
            args.refno = args.target.strip()
        else:
            args.jas_dir = args.target
    if args.refno and not is_jas_refno(str(args.refno)):
        print(json.dumps({"status": "error", "error_message": "invalid job reference number"}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    if args.records_url and not args.refno:
        args.refno = refno_from_url(args.records_url)
    if args.refno and not args.records_url and not args.jas_dir:
        args.records_url = build_records_url_for_refno(str(args.refno), args.base_url)
    if args.records_url:
        if not args.cookie_file and not args.no_cookie:
            return _print_need_input(["jas_session"], list(ASK_JAS_SESSION))
        return run_url_screening(args)
    if args.jas_dir:
        return run_jas_screening(Path(args.jas_dir), args)
    return _print_need_input(["refno"], list(ASK_REFNO))


if __name__ == "__main__":
    raise SystemExit(main())