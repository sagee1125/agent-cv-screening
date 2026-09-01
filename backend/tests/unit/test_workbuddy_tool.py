# Unit tests for the WorkBuddy tool wrapper (run_workbuddy_tool.py).
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# backend/tests/unit/test_workbuddy_tool.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".codex" / "skills" / "host-envelope" / "scripts" / "run_workbuddy_tool.py"


def _import_module():
    """Import the WorkBuddy tool wrapper module in-process."""
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_workbuddy_tool", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(module, argv, monkeypatch, capsys):
    """Run run_workbuddy_tool.main() with argv and return (exit_code, stdout, stderr)."""
    monkeypatch.setattr(sys, "argv", [module.__file__, *argv])
    exit_code = module.main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# request_jas_access with missing session returns need_input envelope.
def test_request_jas_access_missing(monkeypatch, capsys) -> None:
    module = _import_module()
    exit_code, out, _ = _run(module, ["request_jas_access"], monkeypatch, capsys)
    assert exit_code == 2
    envelope = json.loads(out)
    assert envelope["tool"] == "request_jas_access"
    assert envelope["status"] == "need_input"
    assert envelope["ask"]["missing"] == ["jas_session"]


# request_jas_access with granted session returns success envelope.
def test_request_jas_access_granted(monkeypatch, capsys) -> None:
    module = _import_module()
    exit_code, out, _ = _run(
        module, ["request_jas_access", "--jas-session", "granted", "--cookie-file-present"], monkeypatch, capsys
    )
    assert exit_code == 0
    envelope = json.loads(out)
    assert envelope["status"] == "success"
    assert envelope["auth"]["jas_session"] == "granted"
    assert envelope["auth"]["cookie_file_present"] is True


# screen_refno runs the skill and projects stdout through host-envelope.
def test_screen_refno_projects_skill_stdout(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()

    fake_payload = {
        "status": "success",
        "refno": "260818001",
        "post_title": "Project Associate",
        "candidates": [
            {"rank": 1, "appno": "123456", "total_score": 88.5, "tier": "Tier 1"},
        ],
        "reports": {"ranking_overview_html": str(tmp_path / "overview.html")},
    }

    def fake_run_skill(cmd):
        return 0, fake_payload

    def fake_read_pipeline_manifest(stdout):
        return {}

    def fake_read_jas_manifest(stdout):
        return {}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)
    monkeypatch.setattr(module, "_read_pipeline_manifest", fake_read_pipeline_manifest)
    monkeypatch.setattr(module, "_read_jas_manifest", fake_read_jas_manifest)

    exit_code, out, _ = _run(module, ["screen_refno", "260818001", "--driver", "http"], monkeypatch, capsys)
    assert exit_code == 0
    envelope = json.loads(out)
    assert envelope["tool"] == "screen_refno"
    assert envelope["status"] == "success"
    assert envelope["refno"] == "260818001"
    assert envelope["ranking"][0]["appno"] == "123456"
    assert "name" not in json.dumps(envelope)


# screen_refno with a need_input skill output maps to need_input envelope.
def test_screen_refno_need_input(monkeypatch, capsys) -> None:
    module = _import_module()

    def fake_run_skill(cmd):
        return 2, {"status": "need_input", "missing": ["refno"], "questions": ["Send the refno."]}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)
    monkeypatch.setattr(module, "_read_pipeline_manifest", lambda s: {})
    monkeypatch.setattr(module, "_read_jas_manifest", lambda s: {})

    exit_code, out, _ = _run(module, ["screen_refno", "--driver", "http"], monkeypatch, capsys)
    assert exit_code == 2
    envelope = json.loads(out)
    assert envelope["status"] == "need_input"
    assert envelope["ask"]["missing"] == ["refno"]


# check_updates runs the skill and projects stdout through host-envelope.
def test_check_updates_projects_skill_stdout(monkeypatch, capsys) -> None:
    module = _import_module()

    fake_payload = {
        "status": "success",
        "tool": "check_updates",
        "refno": "260818001",
        "post_title": "Project Associate",
        "candidate_count": 3,
        "first_check": False,
        "has_changes": True,
        "changes": {"jd_changed": False, "added": ["999888"], "removed": [], "status_changed": {}},
    }

    def fake_run_skill(cmd):
        return 0, fake_payload

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)

    exit_code, out, _ = _run(module, ["check_updates", "260818001"], monkeypatch, capsys)
    assert exit_code == 0
    envelope = json.loads(out)
    assert envelope["tool"] == "check_updates"
    assert envelope["has_changes"] is True
    assert envelope["changes"]["added"] == ["999888"]


# check_updates with need_input maps to need_input envelope.
def test_check_updates_need_input(monkeypatch, capsys) -> None:
    module = _import_module()

    def fake_run_skill(cmd):
        return 2, {"status": "need_input", "missing": ["refno"], "questions": ["Send the refno."]}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)

    exit_code, out, _ = _run(module, ["check_updates"], monkeypatch, capsys)
    assert exit_code == 2
    envelope = json.loads(out)
    assert envelope["status"] == "need_input"
    assert envelope["ask"]["missing"] == ["refno"]


# No envelope ever leaks filesystem paths or names.
def test_envelope_never_contains_paths_or_names(monkeypatch, capsys) -> None:
    module = _import_module()

    fake_payload = {
        "status": "success",
        "refno": "260818001",
        "post_title": "Project Associate",
        "candidates": [
            {"rank": 1, "appno": "123456", "name": "Alice Chen", "source": "C:\\Users\\hr\\cv.pdf", "total_score": 90},
        ],
        "reports": {"ranking_overview_html": "C:\\Users\\hr\\Desktop\\overview.html"},
    }

    monkeypatch.setattr(module, "_run_skill", lambda cmd: (0, fake_payload))
    monkeypatch.setattr(module, "_read_pipeline_manifest", lambda s: {})
    monkeypatch.setattr(module, "_read_jas_manifest", lambda s: {})

    exit_code, out, _ = _run(module, ["screen_refno", "260818001", "--driver", "http"], monkeypatch, capsys)
    assert exit_code == 0
    dumped = out
    assert "Alice" not in dumped
    assert "C:" not in dumped
    assert "Users" not in dumped


# A URL target must be routed to webridge-collect, not misdetected as a folder.
def test_url_target_routed_to_webridge_not_folder(monkeypatch, capsys) -> None:
    module = _import_module()
    captured_cmds: list[list[str]] = []

    def fake_run_skill(cmd):
        captured_cmds.append(cmd)
        return 0, {"status": "success", "refno": "260818001", "post_title": "PA"}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)
    monkeypatch.setattr(module, "_read_pipeline_manifest", lambda s: {})
    monkeypatch.setattr(module, "_read_jas_manifest", lambda s: {})

    url = "https://jes-web-demo.vercel.app/records.html?refno=2600827001"
    _run(module, ["screen_refno", url, "--driver", "webbridge"], monkeypatch, capsys)

    assert captured_cmds, "skill was not invoked"
    cmd = captured_cmds[0]
    cmd_str = " ".join(cmd)
    assert "run_webridge_collect.py" in cmd_str, "URL must go to webridge-collect, not jas-import"
    assert "--driver" in cmd and "webbridge" in cmd


# A bare refno (no slashes) must also go to webridge-collect.
def test_refno_target_routed_to_webridge(monkeypatch, capsys) -> None:
    module = _import_module()
    captured_cmds: list[list[str]] = []

    def fake_run_skill(cmd):
        captured_cmds.append(cmd)
        return 0, {"status": "success", "refno": "260818001", "post_title": "PA"}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)
    monkeypatch.setattr(module, "_read_pipeline_manifest", lambda s: {})
    monkeypatch.setattr(module, "_read_jas_manifest", lambda s: {})

    _run(module, ["screen_refno", "260818001", "--driver", "webbridge"], monkeypatch, capsys)

    assert captured_cmds
    cmd_str = " ".join(captured_cmds[0])
    assert "run_webridge_collect.py" in cmd_str


# A local folder path must go to jas-import, not webridge-collect.
def test_folder_target_routed_to_jas_import(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()
    folder = tmp_path / "jas-export"
    folder.mkdir()
    captured_cmds: list[list[str]] = []

    def fake_run_skill(cmd):
        captured_cmds.append(cmd)
        return 0, {"status": "success", "refno": "260818001", "post_title": "PA"}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)
    monkeypatch.setattr(module, "_read_pipeline_manifest", lambda s: {})
    monkeypatch.setattr(module, "_read_jas_manifest", lambda s: {})

    _run(module, ["screen_refno", str(folder)], monkeypatch, capsys)

    assert captured_cmds
    cmd_str = " ".join(captured_cmds[0])
    assert "run_jas_import.py" in cmd_str


# A skill error must produce exit code 1, not 0.
def test_skill_error_returns_exit_code_1(monkeypatch, capsys) -> None:
    module = _import_module()

    def fake_run_skill(cmd):
        return 1, {"status": "error", "error_message": "pipeline failed"}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)
    monkeypatch.setattr(module, "_read_pipeline_manifest", lambda s: {})
    monkeypatch.setattr(module, "_read_jas_manifest", lambda s: {})

    exit_code, out, _ = _run(module, ["screen_refno", "260818001", "--driver", "http"], monkeypatch, capsys)
    assert exit_code == 1
    envelope = json.loads(out)
    assert envelope["status"] == "error"


# A check_updates error must also produce exit code 1.
def test_check_updates_error_returns_exit_code_1(monkeypatch, capsys) -> None:
    module = _import_module()

    def fake_run_skill(cmd):
        return 1, {"status": "error", "error_message": "fetch failed"}

    monkeypatch.setattr(module, "_run_skill", fake_run_skill)

    exit_code, out, _ = _run(module, ["check_updates", "260818001"], monkeypatch, capsys)
    assert exit_code == 1
    envelope = json.loads(out)
    assert envelope["status"] == "error"
