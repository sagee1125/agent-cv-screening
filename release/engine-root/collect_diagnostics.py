"""Bundle a privacy-safe diagnostics zip for support.

Collects ONLY: the version stamp, the requirements list, the diagnostics
trail (versions/counts/failure reasons) and every job's last-error-*.txt.
Never the .env, never CVs, never reports, never log lines with model output.

Usage: double-click collect_diagnostics.bat (or run this file directly).
The zip lands on the Desktop as cv-diagnostics-<timestamp>.zip; HR sends
that one file to support.
"""
from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent
MAX_TEXT_BYTES = 100_000  # per file; every collected file is small text


def _desktop() -> Path:
    home = Path.home()
    for candidate in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return candidate
    return home


def _safe_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = _desktop() / f"cv-diagnostics-{stamp}.zip"

    entries: list[tuple[str, str]] = []
    for name in ("version.json", "requirements.txt"):
        text = _safe_text(ENGINE_ROOT / name)
        if text is not None:
            entries.append((name, text))
    trail = ENGINE_ROOT / "data" / "logs" / "diagnostics.jsonl"
    text = _safe_text(trail)
    if text is not None:
        entries.append(("diagnostics.jsonl", text))

    jobs_root = _desktop() / "workbuddy-cv-screen"
    job_count = 0
    error_count = 0
    if jobs_root.is_dir():
        for pipeline_dir in sorted(jobs_root.glob("*/_pipeline")):
            refno = pipeline_dir.parent.name
            job_count += 1
            for err_file in sorted(pipeline_dir.glob("last-error-*.txt")):
                body = _safe_text(err_file)
                if body is not None:
                    entries.append((f"jobs/{refno}/{err_file.name}", body))
                    error_count += 1

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries:
            archive.writestr(name, body)

    size_kb = target.stat().st_size / 1024
    print(f"[ok] diagnostics bundle: {target}")
    print(f"     {len(entries)} files ({size_kb:.0f} KB) - versions, event trail,")
    print(f"     last-errors for {error_count} failure(s) across {job_count} job folder(s).")
    print("     Contains NO CVs, reports or credentials. Send this zip to support.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
