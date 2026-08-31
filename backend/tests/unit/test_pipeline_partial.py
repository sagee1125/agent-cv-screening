"""Tests for L1 pipeline partial success, need_input, retries, and resume."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PIPELINE_SCRIPT = SKILLS_DIR / "pipeline" / "scripts" / "run_pipeline.py"


def _import_pipeline() -> Any:
    """Import the pipeline CLI module in-process."""
    sys.path.insert(0, str(PIPELINE_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("skill_pipeline_partial", PIPELINE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cli(module: Any, argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Run pipeline main() and return (exit_code, stdout, stderr)."""
    monkeypatch.setattr(sys, "argv", [module.__file__] + argv)
    exit_code = module.main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _flag(cmd: list[str], name: str) -> str:
    """Return the value following a CLI flag in a command list."""
    return cmd[cmd.index(name) + 1]


def _fake_skill_runner(parse_calls: list[str], fail_cv_names: set[str] | None = None, fail_until: dict[str, int] | None = None):
    """Build a _run mock that isolates cv-parser/scorer without calling real CLIs."""
    fail_cv_names = fail_cv_names or set()
    fail_until = fail_until or {}
    attempts_by_source: dict[str, int] = {}

    def fake_run(cmd: list[str]) -> subprocess.CompletedProcess:
        script = Path(cmd[1]).name
        if script == "run_cv_parse.py":
            source = _flag(cmd, "--file")
            parse_calls.append(source)
            attempts_by_source[source] = attempts_by_source.get(source, 0) + 1
            name = Path(source).name
            if name in fail_cv_names:
                raise RuntimeError("cv parse failed")
            if attempts_by_source[source] <= fail_until.get(name, 0):
                raise RuntimeError("transient cv parse failed")
            out = Path(_flag(cmd, "--output"))
            out.write_text(
                json.dumps({"structured_data": {"name": "Good Person", "skills": ["Python"]}}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        if script == "run_score.py" and cmd[2] == "build-config":
            Path(_flag(cmd, "--output")).write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        if script == "run_score.py" and cmd[2] == "score":
            Path(_flag(cmd, "--output")).write_text(
                json.dumps(
                    {
                        "total_score": 80,
                        "tier": "Tier 2",
                        "dimension_scores": {
                            "skill_match": 80,
                            "experience_match": 80,
                            "education_match": 80,
                            "research_quality": 80,
                        },
                        "interview_suggestions": [],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        raise RuntimeError(f"unexpected command: {cmd}")

    return fake_run


def test_pipeline_need_input_missing_jd(tmp_path, monkeypatch, capsys) -> None:
    """Missing JD source returns need_input without running candidate steps."""
    module = _import_pipeline()
    extracted = tmp_path / "alice.json"
    extracted.write_text(json.dumps({"name": "Alice"}), encoding="utf-8")
    exit_code, out, _err = _run_cli(
        module,
        ["--extracted", str(extracted), "--skip-reports", "--output-dir", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert exit_code == 2
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["jd"]
    assert payload["questions"]


def test_pipeline_need_input_missing_candidates(tmp_path, monkeypatch, capsys) -> None:
    """Missing CVs returns need_input instead of a hard error."""
    module = _import_pipeline()
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    exit_code, out, _err = _run_cli(
        module,
        ["--jd-json", str(jd), "--skip-reports"],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert exit_code == 2
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["candidates"]


def test_pipeline_need_input_missing_position(tmp_path, monkeypatch, capsys) -> None:
    """Reports require --position unless --skip-reports is set."""
    module = _import_pipeline()
    jd = tmp_path / "jd.json"
    extracted = tmp_path / "alice.json"
    jd.write_text("{}", encoding="utf-8")
    extracted.write_text(json.dumps({"name": "Alice"}), encoding="utf-8")
    exit_code, out, _err = _run_cli(
        module,
        ["--jd-json", str(jd), "--extracted", str(extracted), "--output-dir", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert exit_code == 2
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["position"]


def test_pipeline_partial_success_isolates_cv_failure(tmp_path, monkeypatch, capsys) -> None:
    """One failed CV does not block scoring and ranking the other candidate."""
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    good_cv = tmp_path / "good.pdf"
    bad_cv = tmp_path / "bad.pdf"
    good_cv.write_bytes(b"%PDF")
    bad_cv.write_bytes(b"not a pdf")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    parse_calls: list[str] = []
    monkeypatch.setattr(module, "_run", _fake_skill_runner(parse_calls, fail_cv_names={"bad.pdf"}))
    exit_code, out, _err = _run_cli(
        module,
        [
            "--jd-json",
            str(jd),
            "--cv",
            str(good_cv),
            "--cv",
            str(bad_cv),
            "--skip-reports",
            "--max-retries",
            "0",
            "--output-dir",
            str(out_dir),
        ],
        monkeypatch,
        capsys,
    )
    manifest = json.loads(out)
    assert exit_code == 0
    assert manifest["status"] == "partial_success"
    assert len(manifest["candidates"]) == 1
    assert manifest["candidates"][0]["appno"] == "good"
    assert "name" not in manifest["candidates"][0]
    assert Path(manifest["candidates"][0]["extracted_json"]).name == "extracted-good.json"
    assert len(manifest["failures"]) == 1
    assert manifest["failures"][0]["source"] == str(bad_cv)
    assert manifest["failures"][0]["stage"] == "cv-parse"
    assert manifest["failures"][0]["attempts"] == 1
    assert (out_dir / "manifest.json").is_file()


def test_pipeline_retries_then_succeeds(tmp_path, monkeypatch, capsys) -> None:
    """A transient CV parse error is retried up to --max-retries times."""
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    cv = tmp_path / "flaky.pdf"
    cv.write_bytes(b"%PDF")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    parse_calls: list[str] = []
    monkeypatch.setattr(module, "_run", _fake_skill_runner(parse_calls, fail_until={"flaky.pdf": 2}))
    exit_code, out, _err = _run_cli(
        module,
        [
            "--jd-json",
            str(jd),
            "--cv",
            str(cv),
            "--skip-reports",
            "--max-retries",
            "2",
            "--output-dir",
            str(out_dir),
        ],
        monkeypatch,
        capsys,
    )
    manifest = json.loads(out)
    assert exit_code == 0
    assert manifest["status"] == "success"
    assert len(parse_calls) == 3
    assert manifest["failures"] == []


def test_pipeline_resume_skips_existing_extracted(tmp_path, monkeypatch, capsys) -> None:
    """--resume reuses extracted-<slug>.json and does not call cv-parser again."""
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cv = tmp_path / "good.pdf"
    cv.write_bytes(b"%PDF")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    extracted = out_dir / "extracted-good.json"
    extracted.write_text(
        json.dumps({"structured_data": {"name": "Resumed", "skills": ["Python"]}}),
        encoding="utf-8",
    )
    parse_calls: list[str] = []
    monkeypatch.setattr(module, "_run", _fake_skill_runner(parse_calls, fail_cv_names={"good.pdf"}))
    exit_code, out, _err = _run_cli(
        module,
        [
            "--jd-json",
            str(jd),
            "--cv",
            str(cv),
            "--skip-reports",
            "--resume",
            "--output-dir",
            str(out_dir),
        ],
        monkeypatch,
        capsys,
    )
    manifest = json.loads(out)
    assert exit_code == 0
    assert manifest["status"] == "success"
    assert parse_calls == []
    assert manifest["candidates"][0]["appno"] == "good"
    assert "name" not in manifest["candidates"][0]


def test_pipeline_all_candidates_failed_is_error(tmp_path, monkeypatch, capsys) -> None:
    """When every candidate fails, the manifest status is error and exit code is 1."""
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    bad_cv = tmp_path / "bad.pdf"
    bad_cv.write_bytes(b"x")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    parse_calls: list[str] = []
    monkeypatch.setattr(module, "_run", _fake_skill_runner(parse_calls, fail_cv_names={"bad.pdf"}))
    exit_code, _out, err = _run_cli(
        module,
        [
            "--jd-json",
            str(jd),
            "--cv",
            str(bad_cv),
            "--skip-reports",
            "--max-retries",
            "0",
            "--output-dir",
            str(out_dir),
        ],
        monkeypatch,
        capsys,
    )
    manifest = json.loads(err)
    assert exit_code == 1
    assert manifest["status"] == "error"
    assert manifest["candidates"] == []
    assert manifest["failures"][0]["stage"] == "cv-parse"


# Unchanged score artifacts reuse existing PDFs instead of calling report-gen again.
def test_pipeline_skips_unchanged_candidate_reports(tmp_path, monkeypatch) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    report_dir = tmp_path / "hr"
    out_dir.mkdir()
    report_dir.mkdir()
    extracted = out_dir / "extracted-123456.json"
    score = out_dir / "score-123456.json"
    extracted.write_text("{}", encoding="utf-8")
    score.write_text('{"total_score": 80, "tier": "Tier 2"}', encoding="utf-8")
    calls: list[str] = []

    def fake_retries(cmd, max_retries):
        calls.append(cmd[2])
        output = Path(cmd[cmd.index("--output") + 1])
        output.write_bytes(b"%PDF-fake" if output.suffix == ".pdf" else b"<html></html>")
        return 1, None

    monkeypatch.setattr(module, "_run_with_retries", fake_retries)
    args = argparse.Namespace(
        skip_reports=False,
        position="Project Associate",
        engine="legacy",
        refno="260818001",
        max_retries=0,
        fail_fast=False,
        report_dir=str(report_dir),
    )
    row = {
        "rank": 1,
        "refno": "260818001",
        "appno": "123456",
        "display_label": "260818001/123456",
        "total_score": 80,
        "tier": "Tier 2",
        "_extracted": extracted,
        "_score": score,
        "_source": "123456.pdf",
    }
    failures: list = []
    first = module._generate_reports(args, out_dir, [dict(row)], failures)
    assert calls == ["candidate", "board", "match-html"]
    assert first["ranking_overview_html"]
    reused = dict(row)
    second = module._generate_reports(args, out_dir, [reused], failures)
    assert calls == ["candidate", "board", "match-html"]
    assert reused.get("_report_reused") is True
    assert second["ranking_overview_html"]


# Same JD/CV bytes plus --resume skip cv-parser on the second run.
def test_pipeline_resume_skips_when_input_fingerprint_matches(tmp_path, monkeypatch, capsys) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    cv = tmp_path / "good.pdf"
    cv.write_bytes(b"%PDF")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    parse_calls: list[str] = []
    monkeypatch.setattr(module, "_run", _fake_skill_runner(parse_calls))
    argv = [
        "--jd-json",
        str(jd),
        "--cv",
        str(cv),
        "--skip-reports",
        "--resume",
        "--output-dir",
        str(out_dir),
    ]
    _run_cli(module, argv, monkeypatch, capsys)
    first_count = len(parse_calls)
    assert first_count == 1
    _run_cli(module, argv, monkeypatch, capsys)
    assert len(parse_calls) == first_count


# A changed JD file disables --resume so candidates are parsed again.
def test_pipeline_resume_rebuilds_when_jd_changes(tmp_path, monkeypatch, capsys) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    cv = tmp_path / "good.pdf"
    cv.write_bytes(b"%PDF")
    jd = tmp_path / "jd.json"
    jd.write_text('{"must_skills":[]}', encoding="utf-8")
    parse_calls: list[str] = []
    monkeypatch.setattr(module, "_run", _fake_skill_runner(parse_calls))
    argv = [
        "--jd-json",
        str(jd),
        "--cv",
        str(cv),
        "--skip-reports",
        "--resume",
        "--output-dir",
        str(out_dir),
    ]
    _run_cli(module, argv, monkeypatch, capsys)
    jd.write_text('{"must_skills":["Python"]}', encoding="utf-8")
    _run_cli(module, argv, monkeypatch, capsys)
    assert len(parse_calls) == 2


# Replacing a CV file rebuilds that candidate even when --resume is set.
def test_pipeline_resume_rebuilds_replaced_cv(tmp_path, monkeypatch, capsys) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    cv = tmp_path / "good.pdf"
    cv.write_bytes(b"%PDF-one")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    parse_calls: list[str] = []
    monkeypatch.setattr(module, "_run", _fake_skill_runner(parse_calls))
    argv = [
        "--jd-json",
        str(jd),
        "--cv",
        str(cv),
        "--skip-reports",
        "--resume",
        "--output-dir",
        str(out_dir),
    ]
    _run_cli(module, argv, monkeypatch, capsys)
    cv.write_bytes(b"%PDF-two")
    _run_cli(module, argv, monkeypatch, capsys)
    assert len(parse_calls) == 2
