# Unit tests for the check_updates CLI (no report generation).
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from jas_import.errors import JobNotFoundError

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
    baseline = _job_payload()
    changed = _changed_payload()
    calls = {"n": 0}

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        # First call returns the baseline; every later call returns the changed page.
        payload = baseline if calls["n"] == 0 else changed
        calls["n"] += 1
        return payload

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)

    # First run stores the baseline snapshot.
    _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    # Second run with --no-store: reports changes but must NOT update the stored snapshot.
    exit_code, out, _ = _run(
        module, ["260818001", "--no-store", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys
    )
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["has_changes"] is True

    # Third run without --no-store: must still see changes because the baseline was not updated.
    exit_code, out, _ = _run(
        module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys
    )
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["has_changes"] is True, "baseline must not have been updated by --no-store run"


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


# After a successful screen, a check compares against last_screen (not last_check)
# so a failed screening doesn't mask still-pending changes.
def test_check_prefers_last_screen_over_last_check(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()
    state_dir = tmp_path / "state"

    # Seed job state: a successful screen happened with the original roster.
    from screening_core.job_state import record_screen_run, save_job_state, load_job_state

    screened_job = _job_payload()
    cv = tmp_path / "cvs" / "123456.pdf"
    cv.parent.mkdir(parents=True, exist_ok=True)
    cv.write_bytes(b"%PDF")
    record_screen_run(
        state_dir,
        "260818001",
        job=screened_job,
        cv_paths={"123456": cv},
        result="success",
        output="Desktop/workbuddy-cv-screen/260818001",
    )

    # Now the page has changed (new candidate). A check should detect it.
    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        return _changed_payload()

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)

    exit_code, out, _ = _run(module, ["260818001", "--state-dir", str(state_dir)], monkeypatch, capsys)
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["has_changes"] is True
    assert payload["changes"]["added"] == ["999888"]

    # A second check (page still changed, no new screen) must STILL report changes,
    # because last_screen hasn't been updated — last_check must not shadow it.
    exit_code, out, _ = _run(module, ["260818001", "--state-dir", str(state_dir)], monkeypatch, capsys)
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["has_changes"] is True, "second check must still see changes when last_screen is stale"


# The WebBridge driver navigates the browser and parses the returned HTML.
def test_check_webbridge_driver_parses_browser_html(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()

    fetched_urls: list[str] = []

    class FakeClient:
        # Stand-in for WebBridgeClient: records navigation and returns canned JAS HTML.
        def __init__(self, **kwargs):
            pass

        def navigate(self, url, *, new_tab=True, group_title=None):
            fetched_urls.append(url)

        # Return a minimal JAS records page that job_payload_from_html can parse.
        def page_html(self):
            return (
                '<html><body>'
                '<table id="f-list" class="listTable job-detail-table">'
                '<thead><tr><th>Application no.</th><th>Status</th><th>CV</th></tr></thead>'
                '<tbody><tr>'
                '<td class="f-data-1">123456</td>'
                '<td class="f-data-1">S</td>'
                '<td class="f-data-1"><a href="https://example.com/cv.pdf">cv</a></td>'
                '</tr></tbody></table>'
                '<p>Job advertisement information</p>'
                '<table id="f-list"><tbody>'
                '<tr><td class="f-header">Reference number</td><td class="f-data-1">260818001</td></tr>'
                '<tr><td class="f-header">Post title</td><td class="f-data-1">Project Associate</td></tr>'
                '<tr><td class="f-header">Description</td><td class="f-data-1">Python SQL</td></tr>'
                '</tbody></table>'
                '</body></html>'
            )

    import webridge_collect.client as wb_client_module

    monkeypatch.setattr(wb_client_module, "WebBridgeClient", FakeClient)
    monkeypatch.setattr(wb_client_module, "ensure_webbridge_daemon", lambda **kw: True)

    exit_code, out, _ = _run(
        module,
        ["260818001", "--driver", "webbridge", "--state-dir", str(tmp_path / "state")],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["status"] == "success"
    assert payload["refno"] == "260818001"
    assert payload["candidate_count"] == 1
    assert fetched_urls, "browser was not navigated"


# A WebBridge daemon-down error maps to need_input(jas_session).
def test_check_webbridge_daemon_down_need_input(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()

    class FakeClient:
        # Simulates WebBridgeClient raising a daemon-unreachable error on navigate.
        def __init__(self, **kwargs):
            from webridge_collect.client import WebBridgeError

            self._error = WebBridgeError(
                "Kimi WebBridge daemon unreachable",
                reason="daemon-unreachable",
            )

        def navigate(self, *args, **kwargs):
            raise self._error

    import webridge_collect.client as wb_client_module

    monkeypatch.setattr(wb_client_module, "WebBridgeClient", FakeClient)
    monkeypatch.setattr(wb_client_module, "ensure_webbridge_daemon", lambda **kw: True)

    exit_code, out, _ = _run(
        module,
        ["260818001", "--driver", "webbridge", "--state-dir", str(tmp_path / "state")],
        monkeypatch,
        capsys,
    )
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["jas_session"]


# A missing job is reported as an error with error_code not_found (exit 1).
def test_check_not_found_reports_error_code(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        raise JobNotFoundError("no JAS job found for refno 260818001")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    exit_code, out, err = _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert payload["error_code"] == "not_found"
    assert "260818001" in payload["error_message"]


# A records page that returns a different job is reported not_found (never checks the wrong job).
def test_check_wrong_job_reports_not_found(tmp_path, monkeypatch, capsys) -> None:
    module = _import_module()

    async def fake_fetch(url, cookie_file=None, base_url=None, allowed_hosts=None):
        return _job_payload(refno="260806012")  # page returns a different job

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    exit_code, out, err = _run(module, ["260818001", "--state-dir", str(tmp_path / "state")], monkeypatch, capsys)
    assert exit_code == 1
    payload = json.loads(err)
    assert payload["status"] == "error"
    assert payload["error_code"] == "not_found"
    assert "260806012" in payload["error_message"]
