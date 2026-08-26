# Tests LLM planner tool selection over mocked L1 screening-agent envelopes.
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / ".codex" / "skills" / "screening-agent" / "scripts"
AGENT_PATH = SCRIPTS_DIR / "run_agent.py"
PLANNER_PATH = SCRIPTS_DIR / "planner.py"


# Imports the screening-agent CLI module in-process.
def _import_agent() -> Any:
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("skill_screening_agent", AGENT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Imports the planner module from the screening-agent scripts folder.
def _import_planner() -> Any:
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("skill_screening_planner", PLANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Builds argparse namespace used by the planner tests.
def _args(tmp_path: Path, **overrides: Any) -> argparse.Namespace:
    values = {
        "jd_file": None,
        "jd_json": str(tmp_path / "jd.json"),
        "polyu_ref": None,
        "polyu_detail_url": None,
        "cv": [],
        "extracted": [str(tmp_path / "cv.json")],
        "position": "Backend Engineer",
        "engine": "legacy",
        "reference_date": None,
        "output_dir": str(tmp_path),
        "skip_reports": True,
        "pipeline_max_retries": 2,
        "max_rounds": 2,
        "resume": False,
        "fail_fast": False,
        "planner": "llm",
        "planner_max_steps": 8,
        "goal": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


# Runs the CLI and returns exit code with captured streams.
def _run_cli(module: Any, argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", [module.__file__] + argv)
    code = module.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# Verifies a successful run_screening action stops the planner immediately.
def test_planner_run_screening_success(tmp_path) -> None:
    planner = _import_planner()
    calls: list[str] = []

    def run_loop(args: argparse.Namespace) -> tuple[int, dict]:
        calls.append("run")
        assert args.resume is False
        return 0, {"status": "success", "runs": [{"round": 1}], "result": {"candidates": [{"name": "A"}], "failures": []}, "ask": None}

    def complete_json(_system: str, _user: str) -> dict:
        return {"tool": "run_screening", "arguments": {}, "reason": "inputs complete"}

    code, payload = planner.run_llm_planner(
        _args(tmp_path),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert code == 0
    assert payload["status"] == "success"
    assert payload["planner"] == "llm"
    assert payload["planner_steps"][0]["tool"] == "run_screening"
    assert calls == ["run"]
    assert (tmp_path / "planner-state.json").is_file()


# Verifies missing-input planning stops with ask_user and exit code 2.
def test_planner_ask_user(tmp_path) -> None:
    planner = _import_planner()

    def run_loop(_args: argparse.Namespace) -> tuple[int, dict]:
        raise AssertionError("pipeline must not run when the planner asks the user")

    def complete_json(_system: str, _user: str) -> dict:
        return {"tool": "ask_user", "arguments": {"missing": ["jd"], "questions": ["Provide a JD."]}, "reason": "no jd"}

    code, payload = planner.run_llm_planner(
        _args(tmp_path, jd_json=None, extracted=[]),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert code == 2
    assert payload["status"] == "need_input"
    assert payload["ask"]["missing"] == ["jd"]


# Verifies partial_success can be followed by resume_run.
def test_planner_resume_after_partial(tmp_path) -> None:
    planner = _import_planner()
    resumes: list[bool] = []
    actions = [
        {"tool": "run_screening", "arguments": {}, "reason": "start"},
        {"tool": "resume_run", "arguments": {}, "reason": "retry"},
    ]

    def run_loop(args: argparse.Namespace) -> tuple[int, dict]:
        resumes.append(bool(args.resume))
        if not args.resume:
            return 0, {
                "status": "partial_success",
                "runs": [{"round": 1}],
                "result": {"candidates": [{"name": "A"}], "failures": [{"stage": "cv-parse", "error_message": "timeout"}]},
                "ask": None,
            }
        return 0, {"status": "success", "runs": [{"round": 1}, {"round": 2}], "result": {"candidates": [{"name": "A"}, {"name": "B"}], "failures": []}, "ask": None}

    def complete_json(_system: str, _user: str) -> dict:
        return actions.pop(0)

    code, payload = planner.run_llm_planner(
        _args(tmp_path),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert code == 0
    assert payload["status"] == "success"
    assert resumes == [False, True]
    assert [step["tool"] for step in payload["planner_steps"]] == ["run_screening", "resume_run"]


# Verifies finish reuses a prior agent-state.json without calling the pipeline.
def test_planner_status_then_finish_without_run(tmp_path) -> None:
    planner = _import_planner()
    (tmp_path / "agent-state.json").write_text(
        json.dumps({"status": "success", "round": 1, "retry_decision": {"action": "stop"}, "runs": []}),
        encoding="utf-8",
    )
    actions = [
        {"tool": "get_run_status", "arguments": {}, "reason": "inspect"},
        {"tool": "finish", "arguments": {}, "reason": "reuse prior run"},
    ]

    def run_loop(_args: argparse.Namespace) -> tuple[int, dict]:
        raise AssertionError("should not screen")

    def complete_json(_system: str, _user: str) -> dict:
        return actions.pop(0)

    code, payload = planner.run_llm_planner(
        _args(tmp_path),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert code == 0
    assert payload["status"] == "success"
    assert payload.get("from_agent_state") is True
    assert payload["planner_steps"][0]["observation"]["status"] == "status_read"


# Verifies finish with no in-memory result and no agent-state is an error.
def test_planner_finish_without_state_errors(tmp_path) -> None:
    planner = _import_planner()

    def run_loop(_args: argparse.Namespace) -> tuple[int, dict]:
        raise AssertionError("should not screen")

    def complete_json(_system: str, _user: str) -> dict:
        return {"tool": "finish", "arguments": {}, "reason": "stop"}

    code, payload = planner.run_llm_planner(
        _args(tmp_path),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert code == 1
    assert "no prior screening result" in payload["error_message"]


# Verifies run_screening never inherits CLI --resume; only resume_run sets resume.
def test_planner_run_screening_ignores_cli_resume(tmp_path) -> None:
    planner = _import_planner()
    seen: list[bool] = []

    def run_loop(args: argparse.Namespace) -> tuple[int, dict]:
        seen.append(bool(args.resume))
        return 0, {"status": "success", "runs": [], "result": {"candidates": [], "failures": []}, "ask": None}

    def complete_json(_system: str, _user: str) -> dict:
        return {"tool": "run_screening", "arguments": {}, "reason": "fresh"}

    code, _payload = planner.run_llm_planner(
        _args(tmp_path, resume=True),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert code == 0
    assert seen == [False]


# Verifies ask_user drops unknown missing keys.
def test_planner_ask_user_allowlists_missing(tmp_path) -> None:
    planner = _import_planner()

    def run_loop(_args: argparse.Namespace) -> tuple[int, dict]:
        raise AssertionError("pipeline must not run")

    def complete_json(_system: str, _user: str) -> dict:
        return {
            "tool": "ask_user",
            "arguments": {"missing": ["weights", "jd"], "questions": ["Need JD"]},
            "reason": "ask",
        }

    _code, payload = planner.run_llm_planner(
        _args(tmp_path),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert payload["ask"]["missing"] == ["jd"]


# Verifies planner LLM context redacts emails and filesystem paths.
def test_sanitize_text_redacts_email_and_path() -> None:
    planner = _import_planner()
    text = planner._sanitize_text("failed for ada@polyu.edu.hk at /tmp/secret/cv.pdf extra")
    assert "ada@polyu.edu.hk" not in text
    assert "[redacted]" in text
    assert "[path]" in text
    assert "/tmp/secret" not in text


# Verifies unsupported tool names are rejected without calling the pipeline.
def test_planner_rejects_unknown_tool_then_asks(tmp_path) -> None:
    planner = _import_planner()
    actions = [
        {"tool": "hack_scores", "arguments": {}, "reason": "no"},
        {"tool": "ask_user", "arguments": {"missing": ["candidates"], "questions": ["Upload CVs."]}, "reason": "ask"},
    ]

    def run_loop(_args: argparse.Namespace) -> tuple[int, dict]:
        raise AssertionError("unknown tools must not reach the pipeline")

    def complete_json(_system: str, _user: str) -> dict:
        return actions.pop(0)

    code, payload = planner.run_llm_planner(
        _args(tmp_path, planner_max_steps=4),
        run_loop=run_loop,
        resolve_output_dir=lambda value: Path(value),
        complete_json=complete_json,
    )
    assert code == 2
    assert payload["planner_steps"][0]["tool"] == "invalid"
    assert payload["planner_steps"][1]["tool"] == "ask_user"


# Verifies planner errors include nested SSL causes instead of a bare Connection error.
def test_format_planner_error_unwraps_ssl() -> None:
    planner = _import_planner()
    root = Exception("certificate verify failed")
    wrapped = Exception("Connection error.")
    wrapped.__cause__ = root
    message = planner._format_planner_error(wrapped)
    assert "Connection error." in message
    assert "certificate verify failed" in message
    assert "--planner rules" in message

def test_cli_planner_llm_flag(tmp_path, monkeypatch, capsys) -> None:
    agent = _import_agent()
    planner = _import_planner()
    monkeypatch.setattr(
        planner,
        "_default_complete_json",
        lambda _system, _user: {"tool": "run_screening", "arguments": {}, "reason": "go"},
    )

    def fake_run(*_args, **_kwargs):
        payload = json.dumps({"status": "success", "candidates": [{"name": "A"}], "failures": [], "ask": None})
        import subprocess

        return subprocess.CompletedProcess(["pipeline"], 0, payload, "")

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    # main() does `import planner`; bind the same module object tests patched.
    monkeypatch.setitem(sys.modules, "planner", planner)
    code, out, _err = _run_cli(
        agent,
        [
            "--planner",
            "llm",
            "--jd-json",
            str(tmp_path / "jd.json"),
            "--extracted",
            str(tmp_path / "cv.json"),
            "--skip-reports",
            "--output-dir",
            str(tmp_path),
        ],
        monkeypatch,
        capsys,
    )
    payload = json.loads(out)
    assert code == 0
    assert payload["planner"] == "llm"
    assert payload["status"] == "success"
