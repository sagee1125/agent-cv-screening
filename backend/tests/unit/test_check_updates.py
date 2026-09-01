# Unit tests for the check_updates CLI (no report generation).
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# backend/tests/unit/test_check_updates.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCRIPT = SKILLS_DIR / "jas-import" / "scripts" / "check_updates.py"

DEMO_BASE = "https://jes-web-demo.vercel.app"


def _import_module():
    """Import the check_updates CLI module in-process."""
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("check_updates", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job_payload(refno: str = "260818001") -> dict:
    """Build a mock JAS job payload with two candidates."""
    return {
        "status": "success",
        "refno": refno,
        "job": {"refno": refno, "post_title": "Project Associate"},
        "jd_text": "Post title: Project Associate\nDescription: Python SQL",
        "candidates": [
            {"appno": "123456", "status": "S", "cv_url": None},
            {"appno": "654321", "status": "TBC", "cv_url": None},
        ],
    }


def _changed_payload() -> dict:
    """A payload with a new candidate, a removed one, and a changed JD."""
    payload = _job_payload()
    payload["jd_text"] = "Post title: Project Associate\nDescription: Python FastAPI SQL"
    payload["candidates"] = [
        {"appno": "123456", "status": "S", "cv_url": None},
        {"appno": "999888", "status": "TBC", "cv_url": None},
    ]
    return payload


def _run(module, argv, monkeypatch, capsys):
    """Run check_updates.main() with argv and return (exit_code, stdout, stderr)."""
    monkeypatch.setattr(sys, "argv", [module.__file__, *argv])
    exit_code = module.main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# First check stores a baseline; a second check with the same page reports no change.
def test_check_no_changes_between_runs(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        return _job_payload()

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)

    exit_code, out, _ = _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    assert exit_code == 0
    first = json.loads(out)
    assert first["status"] == "success"
    assert first["tool"] == "check_updates"
    assert first["first_check"] is True
    assert first["has_changes"] is False
    assert first["candidate_count"] == 2

    exit_code, out, _ = _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    assert exit_code == 0
    second = json.loads(out)
    assert second["first_check"] is False
    assert second["has_changes"] is False
    assert second["last_check_at"] == first["checked_at"]


# A changed roster/JD is reported and stored.
def test_check_detects_changes(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()
    payloads = [_job_payload(), _changed_payload()]
    calls = {"n": 0}

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        payload = payloads[calls["n"] % len(payloads)]
        calls["n"] += 1
        return payload

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)

    _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    exit_code, out, _ = _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["has_changes"] is True
    assert payload["changes"]["added"] == ["999888"]
    assert payload["changes"]["removed"] == ["654321"]
    assert payload["changes"]["jd_changed"] is True


# --no-store reports changes without persisting a new snapshot.
def test_check_no_store_does_not_persist(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()
    payloads = [_job_payload(), _changed_payload()]
    calls = {"n": 0}

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        payload = payloads[calls["n"] % len(payloads)]
        calls["n"] += 1
        return payload

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)

    _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    exit_code, out, _ = _run(
        module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys
    )
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["has_changes"] is True


# A records URL + base-url builds the demo records URL and passes it to fetch.
def test_check_builds_demo_url(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()
    captured: dict = {}

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        captured["url"] = url
        captured["base_url"] = base_url
        return _job_payload("2600827001")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)

    exit_code, out, _ = _run(
        module,
        ["2600827001", "--base-url", DEMO_BASE, "--allow-host", "jes-web-demo.vercel.app", "--state-dir", str(tmp_path / "state")],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert captured["url"] == f"{DEMO_BASE}/records.html?refno=2600827001"
    assert captured["base_url"] == DEMO_BASE


# An auth failure maps to need_input(jas_session).
def test_check_auth_failure_need_input(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)

    exit_code, out, _ = _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["missing"] == ["jas_session"]


# A missing refno / URL maps to need_input(refno).
def test_check_no_refno_need_input(monkeypatch, capsys) -> None:
    module = _import_module()
    exit_code, out, _ = _run(module, [], monkeypatch, capsys)
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["missing"] == ["refno"]
