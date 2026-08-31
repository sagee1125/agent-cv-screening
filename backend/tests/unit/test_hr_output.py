# Unit tests for the HR report pack path: Desktop/workbuddy-cv-screen/<refno>/.
from pathlib import Path

from screening_core.hr_output import (
    HR_PACK_FOLDER,
    RANKING_OVERVIEW_HTML,
    candidate_match_stem,
    default_hr_pack_root,
    is_internal_output_dir,
    pipeline_work_dir,
    resolve_hr_job_dir,
)


# Default pack is Desktop/workbuddy-cv-screen when HR does not pass --output-dir.
def test_default_hr_pack_uses_desktop(monkeypatch, tmp_path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr("screening_core.hr_output.user_desktop", lambda: desktop)
    assert default_hr_pack_root() == desktop / HR_PACK_FOLDER
    job = resolve_hr_job_dir(None, "260818001")
    assert job == desktop / HR_PACK_FOLDER / "260818001"
    assert job.is_dir()


# WorkBuddy chat folders are ignored; reports still go to Desktop/<pack>/<refno>/.
def test_workbuddy_session_dir_uses_desktop(monkeypatch, tmp_path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr("screening_core.hr_output.user_desktop", lambda: desktop)
    session = tmp_path / "WorkBuddy AI" / "2026-08-27-19-19-42"
    session.mkdir(parents=True)
    job = resolve_hr_job_dir(str(session), "2600827001")
    assert job == desktop / HR_PACK_FOLDER / "2600827001"


# Repo paths such as data/jas_out are host internals, not an HR save location.
def test_repo_data_dir_uses_desktop(monkeypatch, tmp_path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    repo = tmp_path / "agent-cv-screening"
    repo.mkdir()
    monkeypatch.setattr("screening_core.hr_output.user_desktop", lambda: desktop)
    assert is_internal_output_dir("data/jas_out", repo_root=repo)
    job = resolve_hr_job_dir("data/jas_out", "2600827001", repo_root=repo)
    assert job == desktop / HR_PACK_FOLDER / "2600827001"


# An exported JAS folder must not be used as the report output directory.
def test_jas_export_folder_as_output_dir_uses_desktop(monkeypatch, tmp_path) -> None:
    from screening_core.hr_output import looks_like_jas_export_dir

    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    export = tmp_path / "jasweb-mock"
    export.mkdir()
    (export / "records.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("screening_core.hr_output.user_desktop", lambda: desktop)
    assert looks_like_jas_export_dir(export)
    job = resolve_hr_job_dir(str(export), "2600827001")
    assert job == desktop / HR_PACK_FOLDER / "2600827001"


# An explicit non-internal folder still nests the job refno.
def test_explicit_output_dir_nests_refno(tmp_path) -> None:
    parent = tmp_path / "hr-out"
    job = resolve_hr_job_dir(str(parent), "260818001")
    assert job == parent / "260818001"
    assert pipeline_work_dir(job) == job / "_pipeline"


# If the path already ends with refno, do not nest twice.
def test_output_dir_already_named_refno(tmp_path) -> None:
    target = tmp_path / "260818001"
    job = resolve_hr_job_dir(str(target), "260818001")
    assert job == target


# Candidate files are named by application no. only.
def test_candidate_match_stem() -> None:
    assert candidate_match_stem("123456") == "123456"
    assert RANKING_OVERVIEW_HTML == "ranking-overview.html"


# Missing files are a no-op so screening can skip opening after a failed report write.
def test_open_hr_file_skips_missing(tmp_path) -> None:
    from screening_core.hr_output import open_hr_file

    open_hr_file(tmp_path / "missing.html")
