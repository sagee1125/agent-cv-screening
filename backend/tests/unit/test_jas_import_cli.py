# Unit tests: jas-import CLI screens a folder by default instead of parse-only JSON.
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".codex" / "skills" / "jas-import" / "scripts" / "run_jas_import.py"

sys.path.insert(0, str(SCRIPT.parent))
_spec = importlib.util.spec_from_file_location("run_jas_import_cli", SCRIPT)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

JOB_HTML = """
<html><body>
<table id="f-list" class="listTable job-detail-table">
  <thead><tr><th>Application no.</th></tr></thead>
  <tbody><tr><td class="f-data-1">123456</td></tr></tbody>
</table>
<p>Job advertisement information</p>
<table id="f-list"><tbody>
<tr><td class="f-header">Reference number</td><td class="f-data-1">190001010</td></tr>
<tr><td class="f-header">Post title</td><td class="f-data-1">Project Associate</td></tr>
</tbody></table>
</body></html>
"""


# A bare folder argument is forwarded to screening, not parse-job.
def test_folder_argument_forwards_to_screening(tmp_path, monkeypatch) -> None:
    jas_dir = tmp_path / "jasweb-mock"
    (jas_dir / "uploads").mkdir(parents=True)
    (jas_dir / "records.html").write_text(JOB_HTML, encoding="utf-8")
    (jas_dir / "uploads" / "123456.pdf").write_bytes(b"%PDF")
    captured: list[list[str]] = []

    def fake_screen(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(module, "_forward_to_screening", fake_screen)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(jas_dir)])
    assert module.main() == 0
    assert captured == [[str(jas_dir)]]


# parse-job on an exported folder that already has CVs is upgraded to screening.
def test_parse_job_with_cvs_forwards_to_screening(tmp_path, monkeypatch) -> None:
    jas_dir = tmp_path / "jasweb-mock"
    (jas_dir / "uploads").mkdir(parents=True)
    html = jas_dir / "records.html"
    html.write_text(JOB_HTML, encoding="utf-8")
    (jas_dir / "uploads" / "123456.pdf").write_bytes(b"%PDF")
    captured: list[list[str]] = []

    def fake_screen(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(module, "_forward_to_screening", fake_screen)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "parse-job", "--html-file", str(html), "--output", str(tmp_path / "job.json")],
    )
    assert module.main() == 0
    assert captured and captured[0] == [str(html.resolve().parent)]


# parse-job stays JSON-only when the HTML is not next to CV files.
def test_parse_job_without_cvs_stays_json(tmp_path, monkeypatch, capsys) -> None:
    html = tmp_path / "records.html"
    html.write_text(JOB_HTML, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "parse-job", "--html-file", str(html)])
    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["refno"] == "190001010"
