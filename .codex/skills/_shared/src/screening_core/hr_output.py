# Resolves the default HR report pack: Desktop/workbuddy-cv-screen/<refno>/.
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HR_PACK_FOLDER = "workbuddy-cv-screen"
PIPELINE_SUBDIR = "_pipeline"
RANKING_OVERVIEW_HTML = "ranking-overview.html"
RANKING_COMPARISON_XLSX = "ranking-comparison.xlsx"


# Keep folder and file names filesystem-safe (refno / appno).
def safe_pack_id(value: object, *, fallback: str = "job") -> str:
    text = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or "").strip())
    return text or fallback


# Locate the user's Desktop folder (Windows / OneDrive / Chinese folder names).
def user_desktop() -> Path:
    homes: list[Path] = []
    if sys.platform == "win32" and os.environ.get("USERPROFILE"):
        homes.append(Path(os.environ["USERPROFILE"]))
    homes.append(Path.home())
    seen: set[Path] = set()
    for home in homes:
        if home in seen:
            continue
        seen.add(home)
        for candidate in (
            home / "Desktop",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "桌面",
            home / "桌面",
        ):
            if candidate.is_dir():
                return candidate
    return homes[0] / "Desktop"


# Default parent folder when HR does not pick a save location.
def default_hr_pack_root() -> Path:
    return user_desktop() / HR_PACK_FOLDER


# WorkBuddy session folders are not an HR-chosen save location.
_HOST_SESSION_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")


# True when the path is a WorkBuddy chat workspace, not an HR output folder.
def is_host_session_dir(path: Path | str | None) -> bool:
    if not path:
        return False
    target = Path(path)
    lowered = [part.lower() for part in target.parts]
    if any(part in {"workbuddy ai", ".workbuddy-ai", "workbuddy"} for part in lowered):
        return True
    return bool(_HOST_SESSION_NAME.match(target.name))


# True when --output-dir is a repo/session path WorkBuddy should not use for HR files.
def is_internal_output_dir(path: Path | str | None, *, repo_root: Path | None = None) -> bool:
    if not path:
        return False
    if is_host_session_dir(path):
        return True
    target = Path(path)
    if repo_root is not None:
        root = Path(repo_root).resolve()
        resolved = target if target.is_absolute() else (root / target)
        try:
            resolved.resolve().relative_to(root)
            return True
        except ValueError:
            pass
    return False


# Job folder: <root>/<refno>. If output_dir already ends with refno, use it as-is.
def resolve_hr_job_dir(output_dir: str | None, refno: str | None, *, repo_root: Path | None = None) -> Path:
    job_id = safe_pack_id(refno, fallback="job")
    if output_dir and is_internal_output_dir(output_dir, repo_root=repo_root):
        output_dir = None
    if output_dir:
        base = Path(output_dir)
        if not base.is_absolute() and repo_root is not None:
            base = repo_root / base
        job = base if base.name == job_id else base / job_id
    else:
        job = default_hr_pack_root() / job_id
    job.mkdir(parents=True, exist_ok=True)
    return job


# Internal parse/score JSON lives under _pipeline so HR files stay at the job root.
def pipeline_work_dir(job_dir: Path) -> Path:
    path = job_dir / PIPELINE_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


# Per-candidate HTML/PDF filename is the application no. only.
def candidate_match_stem(appno: object) -> str:
    return safe_pack_id(appno, fallback="unknown")


# Open an HR file with the OS default app (browser for HTML).
def open_hr_file(path: Path | str) -> None:
    target = Path(path)
    if not target.is_file():
        return
    resolved = str(target.resolve())
    if sys.platform == "win32":
        os.startfile(resolved)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, resolved], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


__all__ = [
    "HR_PACK_FOLDER",
    "PIPELINE_SUBDIR",
    "RANKING_COMPARISON_XLSX",
    "RANKING_OVERVIEW_HTML",
    "candidate_match_stem",
    "default_hr_pack_root",
    "is_host_session_dir",
    "is_internal_output_dir",
    "open_hr_file",
    "pipeline_work_dir",
    "resolve_hr_job_dir",
    "safe_pack_id",
    "user_desktop",
]
