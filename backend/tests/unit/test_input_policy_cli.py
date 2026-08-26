# CLI-level tests: pipeline and screening-agent entry points enforce the input policy.
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# backend/tests/unit/test_input_policy_cli.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"

BASE64_BLOB = (
    "SGVsbG8gV29ybGQhISAgIFRoaXMgaXMgYSBiYXNlNjQgYmxvYiB0aGF0IG11c3QgYmUgcmVqZWN0ZWQg"
    "YnkgdGhlIHBvbGljeSBndWFyZCAgICAg"
)


def _import_script(skill: str, script: str):
    """Import a skill CLI script module in-process (executes its _bootstrap)."""
    script_path = SKILLS_DIR / skill / "scripts" / script
    sys.path.insert(0, str(script_path.parent))
    spec = importlib.util.spec_from_file_location(f"skill_{skill.replace('-', '_')}", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_module(module, argv, monkeypatch, capsys):
    """Run a CLI module.main() with the given argv and capture stdout/stderr."""
    monkeypatch.setattr(sys, "argv", [module.__file__, *argv])
    exit_code = module.main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# Pipeline rejects a base64 blob passed as --cv.
def test_pipeline_rejects_base64_cv(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    jd = tmp_path / "jd.txt"
    jd.write_text("Requirements: Python", encoding="utf-8")
    exit_code, _out, err = _run_module(
        module,
        ["--jd-file", str(jd), "--cv", BASE64_BLOB, "--skip-reports"],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "inline content" in payload["error_message"]


# Pipeline rejects a data: URI passed as --jd-file.
def test_pipeline_rejects_data_uri_jd_file(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF")
    exit_code, _out, err = _run_module(
        module,
        ["--jd-file", "data:text/plain;base64,SGVsbG8=", "--cv", str(cv), "--skip-reports"],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "inline content" in payload["error_message"]


# Pipeline rejects a missing --jd-file path.
def test_pipeline_rejects_missing_jd_file(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF")
    exit_code, _out, err = _run_module(
        module,
        ["--jd-file", str(tmp_path / "nope.txt"), "--cv", str(cv), "--skip-reports"],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "not an existing file" in payload["error_message"]


# Pipeline rejects a non-allowlisted detail URL before any network call.
def test_pipeline_rejects_disallowed_url_host(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    exit_code, _out, err = _run_module(
        module,
        [
            "--polyu-ref",
            "260818008-IE",
            "--polyu-detail-url",
            "https://evil.example.com/x",
            "--skip-reports",
        ],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "not allowlisted" in payload["error_message"]


# Screening-agent rejects a base64 blob passed as --cv before running any loop.
def test_run_agent_rejects_base64_cv(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("screening-agent", "run_agent.py")
    jd = tmp_path / "jd.txt"
    jd.write_text("Requirements: Python", encoding="utf-8")
    exit_code, _out, err = _run_module(
        module,
        [
            "--jd-file",
            str(jd),
            "--cv",
            BASE64_BLOB,
            "--skip-reports",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "inline content" in payload["error_message"]


# Pipeline rejects an extracted profile outside --output-dir without trust.
def test_pipeline_rejects_extracted_outside_output_dir(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    extracted = tmp_path / "alice.json"
    extracted.write_text("{}", encoding="utf-8")
    exit_code, _out, err = _run_module(
        module,
        [
            "--jd-json",
            str(jd),
            "--extracted",
            str(extracted),
            "--skip-reports",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "--trust-extracted" in payload["error_message"]


# Screening-agent rejects an extracted profile outside --output-dir without trust.
def test_run_agent_rejects_extracted_outside_output_dir(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("screening-agent", "run_agent.py")
    jd = tmp_path / "jd.json"
    jd.write_text("{}", encoding="utf-8")
    extracted = tmp_path / "alice.json"
    extracted.write_text("{}", encoding="utf-8")
    exit_code, _out, err = _run_module(
        module,
        [
            "--jd-json",
            str(jd),
            "--extracted",
            str(extracted),
            "--skip-reports",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "--trust-extracted" in payload["error_message"]


# Screening-agent rejects a missing --jd-file path before the L1 loop.
def test_run_agent_rejects_missing_jd_file(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("screening-agent", "run_agent.py")
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF")
    exit_code, _out, err = _run_module(
        module,
        [
            "--jd-file",
            str(tmp_path / "nope.txt"),
            "--cv",
            str(cv),
            "--skip-reports",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert "not an existing file" in payload["error_message"]