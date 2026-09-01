# Unit tests for the offline JAS screening orchestrator script.
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# backend/tests/unit/test_jas_screening.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCRIPT = SKILLS_DIR / "jas-import" / "scripts" / "run_jas_screening.py"

sys.path.insert(0, str(SCRIPT.parent))
_spec = importlib.util.spec_from_file_location("run_jas_screening", SCRIPT)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

JOB_HTML = """
<html><body>
<table id="f-list" class="listTable job-detail-table">
  <thead><tr><th>No.</th><th>Application no.</th><th>Form</th><th>Status</th><th>Title</th><th>Surname</th><th>Given</th><th>Chinese</th><th>HKID</th><th>Former</th><th>No.</th><th>Email</th><th>Phone</th><th>CV</th><th>Supp</th></tr></thead>
  <tbody><tr>
    <td class="f-data-1">1</td>
    <td class="f-data-1">123456</td>
    <td class="f-data-1"><a href="https://jobs.polyu.edu.hk/internal/record_detail.php?id=123456&amp;refno=190001010">form</a></td>
    <td class="f-data-1">TBC <a href="https://jobs.polyu.edu.hk/internal/records.php?appno=123456&amp;refno=190001010&amp;appstatus=P">P</a></td>
    <td class="f-data-1">**</td>
    <td class="f-data-1">**</td>
    <td class="f-data-1">**</td>
    <td class="f-data-1">**</td>
    <td class="f-data-1">**</td>
    <td class="f-data-1">No</td>
    <td class="f-data-1"></td>
    <td class="f-data-1">x@example.com</td>
    <td class="f-data-1">123</td>
    <td class="f-data-1"><a href="https://jobs.polyu.edu.hk/internal/file.php?t=cv&amp;id=123456&amp;refno=190001010">cv</a></td>
    <td class="f-data-1"></td>
  </tr></tbody>
</table>
<p>Job advertisement information</p>
<table id="f-list" style="margin:0px;">
  <tbody>
    <tr><td class="f-header">Reference number</td><td class="f-data-1">190001010</td></tr>
    <tr><td class="f-header">Job group</td><td class="f-data-1">Research / Project Posts</td></tr>
    <tr><td class="f-header">Unit</td><td class="f-data-1">Institute for Higher Education Research and Development</td></tr>
    <tr><td class="f-header">Post title</td><td class="f-data-1">Project Associate</td></tr>
    <tr><td class="f-header">Description</td><td class="f-data-1"><p>Design and implement data governance.</p></td></tr>
    <tr><td class="f-header">Posting date</td><td class="f-data-1">1900-01-01</td></tr>
  </tbody>
</table>
</body></html>
"""


# Build an argparse.Namespace with the orchestrator's default flags.
def _args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    values = {
        "records_html": None,
        "cvs_dir": None,
        "cv": [],
        "output_dir": str(tmp_path / "out"),
        "state_dir": str(tmp_path / "state"),
        "engine": "legacy",
        "max_retries": 2,
        "skip_reports": False,
        "no_open": True,
        "resume": False,
        "fail_fast": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


# Locate records.html by default names inside the JAS folder.
def test_resolve_records_html_finds_default_names(tmp_path) -> None:
    jas_dir = tmp_path / "job"
    jas_dir.mkdir()
    records = jas_dir / "records.html"
    records.write_text(JOB_HTML, encoding="utf-8")

    resolved = module._resolve_records_html(jas_dir, None)
    assert resolved == records
    assert module._resolve_records_html(jas_dir, str(records)) == records


# Raise a clear error when no records.html is present.
def test_resolve_records_html_missing_raises(tmp_path) -> None:
    jas_dir = tmp_path / "empty"
    jas_dir.mkdir()
    try:
        module._resolve_records_html(jas_dir, None)
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


# Strip a refno_ prefix and keep numeric appno stems.
def test_appno_from_filename() -> None:
    assert module._appno_from_filename("123456", "190001010") == "123456"
    assert module._appno_from_filename("190001010_654321", "190001010") == "654321"
    assert module._appno_from_filename("cv-abc", "190001010") == "cv-abc"


# Discover CV files and ignore non-CV extensions.
def test_discover_cvs_maps_appno(tmp_path) -> None:
    jas_dir = tmp_path / "job"
    cvs = jas_dir / "cvs"
    cvs.mkdir(parents=True)
    (cvs / "123456.pdf").write_bytes(b"%PDF")
    (cvs / "190001010_654321.pdf").write_bytes(b"%PDF")
    (cvs / "notes.txt").write_text("ignore", encoding="utf-8")

    found = module._discover_cvs(jas_dir, None, [], "190001010")
    assert [(appno, path.name) for appno, path in found] == [("123456", "123456.pdf"), ("654321", "190001010_654321.pdf")]


# Build the pipeline command with JD file, position, and CVs.
def test_pipeline_cmd_shape(tmp_path) -> None:
    cmd = module._pipeline_cmd(
        tmp_path / "jd.txt",
        [tmp_path / "123456.pdf"],
        "Project Associate",
        tmp_path / "out",
        "matching",
        2,
        False,
        False,
        False,
    )
    assert "--jd-file" in cmd
    assert "--position" in cmd and "Project Associate" in cmd
    assert "--engine" in cmd and "matching" in cmd
    assert "--cv" in cmd and str(tmp_path / "123456.pdf") in cmd


# Return need_input when the folder has no CV files.
def test_run_jas_screening_need_input_when_no_cvs(tmp_path, capsys) -> None:
    jas_dir = tmp_path / "job"
    jas_dir.mkdir()
    (jas_dir / "records.html").write_text(JOB_HTML, encoding="utf-8")

    exit_code = module.run_jas_screening(jas_dir, _args(tmp_path))
    captured = capsys.readouterr()
    assert exit_code == module.EXIT_NEED_INPUT
    payload = json.loads(captured.out)
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["candidates"]
    assert payload["ask"]["missing"] == ["candidates"]


# Run the full offline flow and delegate to the pipeline with the right args.
def test_run_jas_screening_runs_pipeline(tmp_path, monkeypatch, capsys) -> None:
    jas_dir = tmp_path / "job"
    cvs = jas_dir / "cvs"
    cvs.mkdir(parents=True)
    (jas_dir / "records.html").write_text(JOB_HTML, encoding="utf-8")
    cv_path = cvs / "123456.pdf"
    cv_path.write_bytes(b"%PDF")

    captured_cmd: list[list[str]] = []

    def fake_run_pipeline(cmd):
        captured_cmd.append(cmd)
        return 0, {"status": "success", "candidates": [], "reports": {"comparison_xlsx": "x"}}

    monkeypatch.setattr(module, "_run_pipeline", fake_run_pipeline)

    exit_code = module.run_jas_screening(jas_dir, _args(tmp_path))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert captured_cmd, "pipeline was not invoked"
    cmd = captured_cmd[0]
    assert "--jd-file" in cmd
    assert "--position" in cmd and "Project Associate" in cmd
    assert "--refno" in cmd and "190001010" in cmd
    assert "--report-dir" in cmd
    assert "--cv" in cmd
    assert any(Path(token).name == "123456.pdf" for token in cmd)

    job_dir = tmp_path / "out" / "190001010"
    work_dir = job_dir / "_pipeline"
    jd_text = (work_dir / "jd.txt").read_text(encoding="utf-8")
    assert "Post title: Project Associate" in jd_text

    manifest = json.loads((work_dir / "jas-manifest.json").read_text(encoding="utf-8"))
    assert manifest["refno"] == "190001010"
    assert manifest["candidates"][0]["appno"] == "123456"
    assert Path(manifest["candidates"][0]["cv_path"]).name == "123456.pdf"
    assert manifest["candidates_without_cv"] == []


# WorkBuddy --output-dir data/jas_out --skip-reports still writes the Desktop HR pack.
def test_internal_output_dir_and_skip_reports_redirect_to_desktop(tmp_path, monkeypatch, capsys) -> None:
    jas_dir = tmp_path / "job"
    cvs = jas_dir / "cvs"
    cvs.mkdir(parents=True)
    (jas_dir / "records.html").write_text(JOB_HTML, encoding="utf-8")
    (cvs / "123456.pdf").write_bytes(b"%PDF")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    captured_cmd: list[list[str]] = []

    def fake_run_pipeline(cmd):
        captured_cmd.append(cmd)
        return 0, {"status": "success", "candidates": []}

    monkeypatch.setattr(module, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("screening_core.hr_output.user_desktop", lambda: desktop)

    args = _args(tmp_path, output_dir=str(jas_dir), skip_reports=True, no_open=True)
    exit_code = module.run_jas_screening(jas_dir, args)
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert captured_cmd and "--skip-reports" not in captured_cmd[0]
    job_dir = desktop / "workbuddy-cv-screen" / "190001010"
    assert (job_dir / "_pipeline" / "jas-manifest.json").is_file()
    assert "--report-dir" in captured_cmd[0]
    assert str(job_dir) in captured_cmd[0]


# Folder vs URL: www. and records.php look like URLs; Windows paths do not.
def test_looks_like_records_url() -> None:
    assert module._looks_like_records_url("https://jobs.polyu.edu.hk/internal/records.php?refno=1")
    assert module._looks_like_records_url("www.jobs.polyu.edu.hk/internal/records.php?refno=1")
    assert not module._looks_like_records_url(r"C:\Users\User\Desktop\jasweb\mock")
    assert module._normalize_records_url("www.jobs.polyu.edu.hk/x").startswith("https://")


# No folder/URL/refno returns a host-projectable need_input envelope.
def test_main_need_input_when_refno_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert module.main() == module.EXIT_NEED_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["refno"]
    questions = payload["ask"]["questions"]
    assert any("reference number" in q.lower() for q in questions)
    assert any("參考編號" in q or "崗位" in q for q in questions)


# Live URL/refno without a cookie jar asks for JAS session access.
def test_main_need_input_when_jas_session_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "260818001"])
    assert module.main() == module.EXIT_NEED_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing"] == ["jas_session"]


# A bare refno is turned into the allowlisted records URL before live fetch.
def test_main_refno_builds_records_url(tmp_path, monkeypatch, capsys) -> None:
    captured: list[argparse.Namespace] = []

    def fake_url(args: argparse.Namespace) -> int:
        captured.append(args)
        return 0

    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(module, "run_url_screening", fake_url)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--refno", "260818001", "--cookie-file", str(jar)])
    assert module.main() == 0
    capsys.readouterr()
    assert captured
    assert "refno=260818001" in captured[0].records_url


# Missing records.html asks for the JD source, not an internal filename code.
def test_run_jas_screening_need_input_when_no_records(tmp_path, capsys) -> None:
    jas_dir = tmp_path / "empty"
    jas_dir.mkdir()
    exit_code = module.run_jas_screening(jas_dir, _args(tmp_path))
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == module.EXIT_NEED_INPUT
    assert payload["missing"] == ["jd"]


# Successful runs open ranking-overview.html unless --no-open.
def test_opens_ranking_overview_after_success(tmp_path, monkeypatch) -> None:
    jas_dir = tmp_path / "jas"
    (jas_dir / "cvs").mkdir(parents=True)
    (jas_dir / "records.html").write_text(JOB_HTML, encoding="utf-8")
    (jas_dir / "cvs" / "123456.pdf").write_bytes(b"%PDF-1.4")
    opened: list[Path] = []
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))
    monkeypatch.setattr(module, "open_hr_file", lambda path: opened.append(Path(path)))
    args = _args(tmp_path, no_open=False)
    assert module.run_jas_screening(jas_dir, args) == module.EXIT_OK
    assert opened and opened[0].name == "ranking-overview.html"


# uploads/ plus CV_Name.pdf still maps to application no. from records.html.
def test_discover_uploads_maps_cv_url_to_appno(tmp_path) -> None:
    jas_dir = tmp_path / "job"
    uploads = jas_dir / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "CV_Daniel_Nguyen.pdf").write_bytes(b"%PDF")
    job = {
        "candidates": [
            {"appno": "2600827001", "cv_url": "./uploads/CV_Daniel_Nguyen.pdf"},
        ]
    }
    found = module._discover_cvs(jas_dir, None, [], "2600827001", job)
    assert found == [("2600827001", uploads / "CV_Daniel_Nguyen.pdf")]

# A second screening of the same job folder enables --resume without HR flags.
def test_second_run_auto_enables_resume(tmp_path, monkeypatch, capsys) -> None:
    jas_dir = tmp_path / "job"
    cvs = jas_dir / "cvs"
    cvs.mkdir(parents=True)
    (jas_dir / "records.html").write_text(JOB_HTML, encoding="utf-8")
    (cvs / "123456.pdf").write_bytes(b"%PDF")
    captured_cmd: list[list[str]] = []

    def fake_run_pipeline(cmd):
        captured_cmd.append(cmd)
        return 0, {"status": "success", "candidates": []}

    monkeypatch.setattr(module, "_run_pipeline", fake_run_pipeline)
    module.run_jas_screening(jas_dir, _args(tmp_path, resume=False, no_open=True))
    module.run_jas_screening(jas_dir, _args(tmp_path, resume=False, no_open=True))
    capsys.readouterr()
    assert "--resume" not in captured_cmd[0]
    assert "--resume" in captured_cmd[1]

