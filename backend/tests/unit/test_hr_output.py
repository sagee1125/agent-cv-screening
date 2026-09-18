# Unit tests for the HR report pack path: Desktop/workbuddy-cv-screen/<refno>/.
from pathlib import Path

from screening_core.hr_output import (
    HR_PACK_FOLDER,
    RANKING_OVERVIEW_HTML,
    candidate_match_stem,
    cv_link_for_appno,
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


# A CV file name that carries the candidate's name must never reach HR-facing HTML.
# Measured on the demo page: every CV link is .../uploads/CV_<Given>_<Surname>.pdf.
def test_cv_link_drops_a_file_name_that_carries_the_name() -> None:
    url = "https://jobs.polyu.edu.hk/uploads/CV_Hana_Ito.pdf"
    assert cv_link_for_appno(url, "260907004") == ""


# A file that names the appno *and* the candidate is refused too, so the gate cannot be
# walked around by a page that appends the number to a name.
def test_cv_link_drops_a_file_name_that_carries_both() -> None:
    assert cv_link_for_appno("https://host/uploads/CV_260907004_Hana_Ito.pdf", "260907004") == ""
    assert cv_link_for_appno("https://host/uploads/CV_Hana_Ito_260907004.pdf", "260907004") == ""


# An appno-named file is what the report may link, and it keeps working.
def test_cv_link_keeps_an_appno_named_file() -> None:
    for url in (
        "https://example.test/cvs/260901007.pdf",
        "https://host/uploads/260907004.pdf",
        "https://host/uploads/CV_260907004.pdf",
    ):
        appno = "260901007" if "260901007" in url else "260907004"
        assert cv_link_for_appno(url, appno) == url


# The real JAS shape identifies the CV by query value, and names nobody in the path.
def test_cv_link_keeps_a_query_identified_url() -> None:
    url = "https://jobs.polyu.edu.hk/file.php?t=cv&id=260907004&refno=260917001"
    assert cv_link_for_appno(url, "260907004") == url
    # A different applicant's link is not this row's link.
    assert cv_link_for_appno(url, "260907005") == ""


# The gate fails closed: an unrecognised but harmless file name loses the link rather than
# risk publishing a name, and an unusable URL or a missing appno yields no link at all.
def test_cv_link_fails_closed() -> None:
    assert cv_link_for_appno("https://host/uploads/scan_of_resume.pdf", "260907004") == ""
    assert cv_link_for_appno("https://host/uploads/260907004.pdf", "") == ""
    assert cv_link_for_appno("", "260907004") == ""
    assert cv_link_for_appno("javascript:alert(1)", "260907004") == ""
    assert cv_link_for_appno(None, "260907004") == ""
