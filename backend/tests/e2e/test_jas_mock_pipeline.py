# End-to-end tests for the JAS mock data: generate, parse, and screen.
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# backend/tests/e2e/test_jas_mock_pipeline.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCREENING_SCRIPT = SKILLS_DIR / "jas-import" / "scripts" / "run_jas_screening.py"

from jas_import.mock import MOCK_REFNO, generate_mock_jas_dir  # noqa: E402
from jas_import.skill import parse_job_skill, parse_list_skill  # noqa: E402


def _import_screening_module():
    """Import the offline JAS screening CLI module in-process."""
    sys.path.insert(0, str(SCREENING_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_jas_screening", SCREENING_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _screening_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    """Build the screening orchestrator Namespace with defaults."""
    values = {
        "records_html": None,
        "cvs_dir": None,
        "cv": [],
        "output_dir": str(tmp_path / "out"),
        # A screening run records job state under the refno it screened. Left unset that defaults to
        # the repo's data/jas_state, so a test run overwrites the developer's real snapshot for
        # whatever refno the mock uses (found 2026-09-18: the real 260818001 snapshot was replaced by
        # mock applicants and 100 mock history entries). Every test gets its own state dir instead,
        # and test_mock_screening_never_writes_the_repo_state_dir holds that guarantee in place.
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


# The generator writes the full mock JAS folder.
def test_generate_mock_dir(tmp_path) -> None:
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    assert (jas_dir / "records.html").is_file()
    assert (jas_dir / "list.html").is_file()
    assert (jas_dir / "cvs" / "123456.pdf").is_file()
    assert (jas_dir / "cvs" / "654321.pdf").is_file()
    assert (jas_dir / "README.txt").is_file()


# The mock HTML parses into JD text and appno-keyed candidate references.
def test_parse_mock_list_and_job(tmp_path) -> None:
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")

    list_payload = parse_list_skill(jas_dir / "list.html")
    assert list_payload["status"] == "success"
    assert list_payload["items"][0]["refno"] == MOCK_REFNO
    assert list_payload["items"][0]["post_title"] == "Project Associate"

    job_payload = parse_job_skill(jas_dir / "records.html")
    assert job_payload["status"] == "success"
    assert job_payload["refno"] == MOCK_REFNO
    assert job_payload["job"]["post_title"] == "Project Associate"
    assert "Python" in job_payload["jd_text"]
    assert "SQL" in job_payload["jd_text"]

    candidates = job_payload["candidates"]
    assert [candidate["appno"] for candidate in candidates] == ["123456", "654321"]
    assert candidates[0]["status"] == "S"
    assert candidates[1]["status"] == "TBC"
    assert candidates[0]["cv_url"].endswith(f"file.php?t=cv&id=123456&refno={MOCK_REFNO}")


# The offline orchestrator delegates to the pipeline with CVs in appno order.
def test_screening_orchestration_ranks_mock(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    captured_cmd: list[list[str]] = []

    def fake_run_pipeline(cmd):
        captured_cmd.append(cmd)
        return 0, {
            "status": "success",
            "candidates": [
                {"rank": 1, "appno": "123456", "refno": MOCK_REFNO, "total_score": 45.31},
                {"rank": 2, "appno": "654321", "refno": MOCK_REFNO, "total_score": 0.0},
            ],
        }

    monkeypatch.setattr(module, "_run_pipeline", fake_run_pipeline)
    exit_code = module.run_jas_screening(jas_dir, _screening_args(tmp_path, engine="matching"))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert captured_cmd, "pipeline was not invoked"
    cmd = captured_cmd[0]
    assert "--position" in cmd and "Project Associate" in cmd
    assert any("123456.pdf" in token for token in cmd)
    assert any("654321.pdf" in token for token in cmd)

    out_dir = tmp_path / "out"
    manifest = json.loads(
        (out_dir / MOCK_REFNO / "_pipeline" / "jas-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["refno"] == MOCK_REFNO
    assert [candidate["appno"] for candidate in manifest["candidates"]] == ["123456", "654321"]
    assert manifest["candidates_without_cv"] == []


# Optional live end-to-end run (JD parse + CV parse via LLM + matching ranking).
@pytest.mark.skipif(
    "JAS_MOCK_E2E" not in os.environ,
    reason="set JAS_MOCK_E2E=1 to run the live-LLM end-to-end ranking test",
)
def test_real_e2e_ranking(tmp_path) -> None:
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCREENING_SCRIPT),
            "--jas-dir",
            str(jas_dir),
            "--output-dir",
            str(out_dir),
            "--engine",
            "matching",
            # Same reason as _screening_args: never let a test run write the repo's job state.
            "--state-dir",
            str(tmp_path / "state"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "success"
    ranks = payload["candidates"]
    assert len(ranks) == 2
    assert ranks[0]["appno"] == "123456"
    assert ranks[1]["appno"] == "654321"
    assert "name" not in ranks[0]
    assert ranks[0]["total_score"] > ranks[1]["total_score"]
    job_dir = out_dir / MOCK_REFNO
    assert (job_dir / "ranking-overview.html").is_file()
    assert (job_dir / "123456.html").is_file()
    assert (job_dir / "_pipeline" / "jas-manifest.json").is_file()


# A mock run must never write the repo's job-state directory.
#
# A state file is the baseline the update check diffs a real job against, so a mock run that writes
# under a real refno destroys it silently: the real 260818001 snapshot was replaced by the mock
# applicants and 100 mock history entries before this was found (2026-09-18). Two things now prevent
# that — MOCK_REFNO is a refno no real job can have, and every test passes its own state_dir — and
# this test holds both: it runs the mock flow the way the tests run it and then requires the repo
# state dir to be untouched, while still seeing the run record its state in the isolated dir.
def test_mock_screening_never_writes_the_repo_state_dir(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    repo_state = REPO_ROOT / "data" / "jas_state"
    before = {path.name: path.stat().st_mtime_ns for path in repo_state.glob("*.json")}

    monkeypatch.setattr(
        module,
        "_run_pipeline",
        lambda cmd: (
            0,
            {
                "status": "success",
                "candidates": [
                    {"rank": 1, "appno": "123456", "refno": MOCK_REFNO, "total_score": 45.31},
                    {"rank": 2, "appno": "654321", "refno": MOCK_REFNO, "total_score": 0.0},
                ],
            },
        ),
    )
    exit_code = module.run_jas_screening(jas_dir, _screening_args(tmp_path))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    after = {path.name: path.stat().st_mtime_ns for path in repo_state.glob("*.json")}
    assert after == before, "the mock run added or rewrote a file in the repo job-state dir"
    # Positive control: the run did record its state, just in the dir it was handed.
    assert (tmp_path / "state" / f"{MOCK_REFNO}.json").is_file(), "the run recorded no state at all"