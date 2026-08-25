# Tests L1 screening-agent loop behavior over pipeline JSON envelopes.
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCRIPT_PATH = SKILLS_DIR / "screening-agent" / "scripts" / "run_agent.py"


# Imports the screening-agent CLI module in-process.
def _import_script() -> Any:
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    spec = importlib.util.spec_from_file_location("skill_screening_agent", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Runs the CLI and returns exit code with captured stdout/stderr.
def _run_cli(
    module: Any,
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", [module.__file__] + argv)
    code = module.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# Creates a subprocess.CompletedProcess with JSON payload on stdout or stderr.
def _proc(code: int, payload: dict) -> subprocess.CompletedProcess:
    text = json.dumps(payload)
    if code in {0, 2}:
        return subprocess.CompletedProcess(["pipeline"], code, text, "")
    return subprocess.CompletedProcess(["pipeline"], code, "", text)


# Verifies need_input from pipeline is returned directly with exit code 2.
def test_agent_passthrough_need_input(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script()
    responses = [_proc(2, {"status": "need_input", "missing": ["jd"], "questions": ["Provide JD"], "ask": {"missing": ["jd"]}})]
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: responses.pop(0))
    code, out, _err = _run_cli(module, ["--output-dir", str(tmp_path)], monkeypatch, capsys)
    payload = json.loads(out)
    assert code == 2
    assert payload["status"] == "need_input"
    assert len(payload["runs"]) == 1
    assert payload["result"]["status"] == "need_input"


# Verifies a successful pipeline first round ends the orchestration loop.
def test_agent_success_first_round(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script()
    responses = [_proc(0, {"status": "success", "candidates": [{"name": "A"}], "failures": [], "ask": None})]
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: responses.pop(0))
    code, out, _err = _run_cli(
        module,
        ["--jd-json", str(tmp_path / "jd.json"), "--extracted", str(tmp_path / "cv.json"), "--skip-reports", "--output-dir", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["status"] == "success"
    assert len(payload["runs"]) == 1
    state = json.loads((tmp_path / "agent-state.json").read_text(encoding="utf-8"))
    assert state["retry_decision"]["action"] == "stop"
    assert state["retry_decision"]["reason"] == "all_candidates_succeeded"


# Verifies partial_success triggers a second resume round that can recover to success.
def test_agent_retries_partial_success_rounds(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script()
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return _proc(
                0,
                {
                    "status": "partial_success",
                    "candidates": [{"name": "A"}],
                    "failures": [{"source": "bad.pdf", "stage": "cv-parse", "attempts": 3, "error_message": "bad"}],
                    "ask": None,
                },
            )
        return _proc(0, {"status": "success", "candidates": [{"name": "A"}, {"name": "B"}], "failures": [], "ask": None})

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code, out, _err = _run_cli(
        module,
        [
            "--jd-json",
            str(tmp_path / "jd.json"),
            "--cv",
            str(tmp_path / "good.pdf"),
            "--cv",
            str(tmp_path / "bad.pdf"),
            "--skip-reports",
            "--max-rounds",
            "2",
            "--output-dir",
            str(tmp_path),
        ],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["status"] == "success"
    assert len(payload["runs"]) == 2
    assert "--resume" not in calls[0]
    assert "--resume" in calls[1]
    state = json.loads((tmp_path / "agent-state.json").read_text(encoding="utf-8"))
    assert state["retry_decision"]["action"] == "stop"
    assert state["retry_decision"]["reason"] == "all_candidates_succeeded"


# Verifies partial_success with no retryable stage ends immediately.
def test_agent_stops_when_partial_has_no_retryable_failures(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script()
    responses = [
        _proc(
            0,
            {
                "status": "partial_success",
                "candidates": [{"name": "A"}],
                "failures": [{"source": "x", "stage": "non-retryable", "attempts": 1, "error_message": "x"}],
                "ask": None,
            },
        )
    ]
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: responses.pop(0))
    code, out, _err = _run_cli(
        module,
        ["--jd-json", str(tmp_path / "jd.json"), "--extracted", str(tmp_path / "cv.json"), "--skip-reports", "--max-rounds", "3", "--output-dir", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["status"] == "partial_success"
    assert len(payload["runs"]) == 1


# Verifies known permanent errors do not trigger another orchestration round.
def test_agent_stops_when_failure_message_is_non_retryable(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script()
    calls: list[list[str]] = []
    responses = [
        _proc(
            0,
            {
                "status": "partial_success",
                "candidates": [{"name": "A"}],
                "failures": [
                    {
                        "source": "x.pdf",
                        "stage": "cv-parse",
                        "attempts": 3,
                        "error_message": "file not found: x.pdf",
                    }
                ],
                "ask": None,
            },
        )
    ]

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return responses.pop(0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code, out, _err = _run_cli(
        module,
        ["--jd-json", str(tmp_path / "jd.json"), "--cv", str(tmp_path / "x.pdf"), "--skip-reports", "--max-rounds", "3", "--output-dir", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["status"] == "partial_success"
    assert len(payload["runs"]) == 1
    assert len(calls) == 1
    state = json.loads((tmp_path / "agent-state.json").read_text(encoding="utf-8"))
    assert state["retry_decision"]["action"] == "stop"
    assert state["retry_decision"]["reason"] == "no_retryable_failures"


# Verifies known transient failures are retried in another round.
def test_agent_retries_when_failure_message_is_transient(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script()
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return _proc(
                0,
                {
                    "status": "partial_success",
                    "candidates": [{"name": "A"}],
                    "failures": [
                        {
                            "source": "x.pdf",
                            "stage": "cv-parse",
                            "attempts": 3,
                            "error_message": "gateway timeout while calling parser",
                        }
                    ],
                    "ask": None,
                },
            )
        return _proc(0, {"status": "success", "candidates": [{"name": "A"}, {"name": "B"}], "failures": [], "ask": None})

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code, out, _err = _run_cli(
        module,
        ["--jd-json", str(tmp_path / "jd.json"), "--cv", str(tmp_path / "x.pdf"), "--skip-reports", "--max-rounds", "2", "--output-dir", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["status"] == "success"
    assert len(payload["runs"]) == 2
    assert "--resume" in calls[1]
    state = json.loads((tmp_path / "agent-state.json").read_text(encoding="utf-8"))
    assert state["retry_decision"]["action"] == "stop"
    assert state["retry_decision"]["reason"] == "all_candidates_succeeded"


# Verifies hard errors bubble up with exit code 1 and stderr JSON.
def test_agent_surfaces_hard_error(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script()
    responses = [_proc(1, {"status": "error", "error_message": "config failed"})]
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: responses.pop(0))
    code, _out, err = _run_cli(
        module,
        ["--jd-json", str(tmp_path / "jd.json"), "--extracted", str(tmp_path / "cv.json"), "--skip-reports", "--output-dir", str(tmp_path)],
        monkeypatch,
        capsys,
    )
    payload = json.loads(err)
    assert code == 1
    assert payload["status"] == "error"
    assert payload["runs"][0]["status"] == "error"


# Verifies retry_decision marks partial success with transient failures as retry.
def test_retry_decision_reports_retry_action() -> None:
    module = _import_script()
    decision = module._retry_decision(  # noqa: SLF001 - unit test for orchestration policy
        "partial_success",
        1,
        3,
        {
            "failures": [
                {
                    "source": "a.pdf",
                    "stage": "cv-parse",
                    "attempts": 3,
                    "error_message": "gateway timeout",
                }
            ]
        },
    )
    assert decision["action"] == "retry"
    assert decision["reason"] == "retryable_failures_detected"
