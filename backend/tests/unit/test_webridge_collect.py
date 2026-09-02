# Unit tests for the webridge-collect skill (WebBridge + HTTP collection).
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

# backend/tests/unit/test_webridge_collect.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCRIPT = SKILLS_DIR / "webridge-collect" / "scripts" / "run_webridge_collect.py"
COLLECT_SRC = SKILLS_DIR / "webridge-collect" / "src"
SHARED_SRC = REPO_ROOT / ".codex" / "skills" / "_shared" / "src"
JAS_SRC = SKILLS_DIR / "jas-import" / "src"

for path in (COLLECT_SRC, SHARED_SRC, JAS_SRC):
    sys.path.insert(0, str(path))

from jas_import.errors import JobNotFoundError  # noqa: E402
from webridge_collect import collect  # noqa: E402
from webridge_collect import client as client_mod  # noqa: E402
from webridge_collect.client import (  # noqa: E402
    WebBridgeClient,
    WebBridgeError,
    ensure_webbridge_daemon,
)

RECORDS_URL = "https://jes-web-demo.vercel.app/records.html?refno=2600827001"
DEMO_BASE_URL = "https://jes-web-demo.vercel.app"

DEMO_HTML = """
<html><body>
<table id="f-list" class="listTable job-detail-table">
  <thead><tr><th>No.</th><th>Application no.</th><th>Form</th><th>Status</th><th>Title</th><th>Surname</th><th>Given</th><th>Chinese</th><th>HKID</th><th>Former</th><th>No.</th><th>Email</th><th>Phone</th><th>CV</th><th>Supp</th></tr></thead>
  <tbody><tr>
    <td class="f-data-1">4</td>
    <td class="f-data-1">2600827004</td>
    <td class="f-data-1"><a href="https://jes-web-demo.vercel.app/record_detail.php?id=2600827004&amp;refno=2600827001">form</a></td>
    <td class="f-data-1">T <a href="https://jes-web-demo.vercel.app/records.html?appno=2600827004&amp;refno=2600827001&amp;appstatus=P">P</a> <a href="https://jes-web-demo.vercel.app/records.html?appno=2600827004&amp;refno=2600827001&amp;appstatus=S">S</a> <a href="https://jes-web-demo.vercel.app/records.html?appno=2600827004&amp;refno=2600827001&amp;appstatus=N">N</a></td>
    <td class="f-data-1">**</td>
    <td class="f-data-1">LEUNG</td>
    <td class="f-data-1">Sophia</td>
    <td class="f-data-1"></td>
    <td class="f-data-1">T215</td>
    <td class="f-data-1">No</td>
    <td class="f-data-1"></td>
    <td class="f-data-1">sophia@example.com</td>
    <td class="f-data-1">123</td>
    <td class="f-data-1"><a href="https://jes-web-demo.vercel.app/uploads/CV_Sophia_Leung.pdf">cv</a></td>
    <td class="f-data-1"></td>
  </tr></tbody>
</table>
<p>Job advertisement information</p>
<table id="f-list" style="margin:0px;">
  <tbody>
    <tr><td class="f-header">Reference number</td><td class="f-data-1">2600827001</td></tr>
    <tr><td class="f-header">Job group</td><td class="f-data-1">Research / Project Posts</td></tr>
    <tr><td class="f-header">Unit</td><td class="f-data-1">Department of Computing and Information Sciences</td></tr>
    <tr><td class="f-header">Post title</td><td class="f-data-1">Senior Software Engineer</td></tr>
    <tr><td class="f-header">Description</td><td class="f-data-1"><p>Python, FastAPI, React.</p></td></tr>
    <tr><td class="f-header">Posting date</td><td class="f-data-1">2026-08-15</td></tr>
  </tbody>
</table>
</body></html>
"""

ALLOWED = ("jes-web-demo.vercel.app",)


# build_records_url honors --base-url for the public demo.
def test_build_records_url_base_url() -> None:
    assert collect.build_records_url("2600827001", DEMO_BASE_URL) == RECORDS_URL
    assert collect.build_records_url("2600827001", None) == "https://jobs.polyu.edu.hk/internal/records.php?refno=2600827001"


# origin_of returns the scheme://host part of a URL.
def test_origin_of() -> None:
    assert collect.origin_of(RECORDS_URL) == DEMO_BASE_URL


# The HTTP driver fetches the page and CVs, writes records.html + cvs/<appno>.pdf.
def test_collect_http_driver_writes_folder(tmp_path, monkeypatch) -> None:
    async def fake_fetch_html(url, cookie_file=None, allowed_hosts=None):
        return DEMO_HTML

    async def fake_download_to(url, dest, cookie_file=None, allowed_hosts=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(collect._jas_fetch, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(collect._jas_fetch, "download_to", fake_download_to)

    folder = tmp_path / "job"
    manifest = collect.collect_job(
        records_url=RECORDS_URL,
        folder=folder,
        driver="http",
        base_url=DEMO_BASE_URL,
        allowed_hosts=ALLOWED,
    )

    assert (folder / "records.html").is_file()
    cv = folder / "cvs" / "2600827004.pdf"
    assert cv.is_file() and cv.read_bytes() == b"%PDF"
    assert manifest["refno"] == "2600827001"
    assert manifest["post_title"] == "Senior Software Engineer"
    assert manifest["candidates"][0]["status"] == "TBC"
    assert manifest["cv_downloaded"] == ["2600827004"]


# The WebBridge driver simulates a human (list page -> View link) and writes the same folder layout.
def test_collect_webridge_driver_writes_folder(tmp_path) -> None:
    class FakeBrowser:
        # Record navigations + CDP calls and return the demo page HTML.
        def __init__(self):
            self.urls = []
            self.cdp_calls = []

        def navigate(self, url, *, new_tab=True, group_title=None):
            self.urls.append(url)

        def cdp(self, method, params=None):
            self.cdp_calls.append(method)

        # Simulate the human flow: the list page was read and the View link was found.
        def evaluate(self, code):
            return {"typed": True, "clicked": True, "href": RECORDS_URL, "text": "View"}

        # Return the saved demo page HTML for the collected records file.
        def page_html(self):
            return DEMO_HTML

        # Return canned CV bytes for any candidate CV URL.
        def fetch_bytes(self, url):
            return b"%PDF"

    browser = FakeBrowser()
    folder = tmp_path / "job"
    manifest = collect.collect_job(
        records_url=RECORDS_URL,
        folder=folder,
        driver="webbridge",
        base_url=DEMO_BASE_URL,
        refno="2600827001",
        client=browser,  # type: ignore[arg-type]
    )

    # Human flow: land on the job list page first, then open the row's View link, keeping the tab focused.
    assert browser.urls == [DEMO_BASE_URL + "/", RECORDS_URL]
    assert browser.cdp_calls.count("Page.bringToFront") == 2
    assert (folder / "records.html").is_file()
    assert (folder / "cvs" / "2600827004.pdf").read_bytes() == b"%PDF"
    assert manifest["cv_downloaded"] == ["2600827004"]


# When the job row is not found on the list page, the WebBridge flow falls back to the records URL directly.
def test_collect_webridge_human_flow_falls_back_to_records_url(tmp_path) -> None:
    class FakeBrowser:
        # Record navigations + CDP calls and return the demo page HTML.
        def __init__(self):
            self.urls = []
            self.cdp_calls = []

        def navigate(self, url, *, new_tab=True, group_title=None):
            self.urls.append(url)

        def cdp(self, method, params=None):
            self.cdp_calls.append(method)

        # Simulate the list page not containing the requested job.
        def evaluate(self, code):
            return {"typed": False, "clicked": False, "reason": "row-not-found"}

        def page_html(self):
            return DEMO_HTML

        def fetch_bytes(self, url):
            return b"%PDF"

    browser = FakeBrowser()
    folder = tmp_path / "job"
    manifest = collect.collect_job(
        records_url=RECORDS_URL,
        folder=folder,
        driver="webbridge",
        base_url=DEMO_BASE_URL,
        refno="2600827001",
        client=browser,  # type: ignore[arg-type]
    )

    assert browser.urls == [DEMO_BASE_URL + "/", RECORDS_URL]
    assert manifest["refno"] == "2600827001"


# A records page that returns the wrong job is refused (never collects a wrong report).
def test_collect_webridge_refuses_wrong_job(tmp_path, monkeypatch) -> None:
    async def fake_fetch_html(url, cookie_file=None, allowed_hosts=None):
        return DEMO_HTML  # DEMO_HTML carries refno 2600827001

    async def fake_download_to(url, dest, cookie_file=None, allowed_hosts=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(collect._jas_fetch, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(collect._jas_fetch, "download_to", fake_download_to)
    with pytest.raises(JobNotFoundError):
        collect.collect_job(
            records_url=RECORDS_URL,
            folder=tmp_path / "job",
            driver="http",
            base_url=DEMO_BASE_URL,
            refno="260806012",
            allowed_hosts=ALLOWED,
        )


# A CV download failure is recorded without aborting the job.
def test_collect_http_driver_records_download_failure(tmp_path, monkeypatch) -> None:
    async def fake_fetch_html(url, cookie_file=None, allowed_hosts=None):
        return DEMO_HTML

    async def fake_download_to(url, dest, cookie_file=None, allowed_hosts=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(collect._jas_fetch, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(collect._jas_fetch, "download_to", fake_download_to)

    manifest = collect.collect_job(
        records_url=RECORDS_URL,
        folder=tmp_path / "job",
        driver="http",
        base_url=DEMO_BASE_URL,
        allowed_hosts=ALLOWED,
    )
    assert manifest["candidates_without_cv"] == ["2600827004"]
    assert manifest["download_failures"][0]["appno"] == "2600827004"


# WebBridgeClient.fetch_bytes pulls the CV in chunks through evaluate.
def test_webridge_client_fetch_bytes_chunks(monkeypatch) -> None:
    client = WebBridgeClient(session="test-session")
    calls: list[str] = []

    def fake_evaluate(code):
        calls.append(code)
        if len(calls) == 1:
            return {"ok": True, "status": 200, "total": 5}
        return {"done": True, "pos": 5, "total": 5, "chunk": "aGVsbG8="}

    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    assert client.fetch_bytes("https://jes-web-demo.vercel.app/uploads/CV.pdf") == b"hello"
    assert len(calls) == 2


# WebBridgeClient unwraps the daemon's {"ok": true, "data": {...}} envelope.
def test_webridge_client_unwraps_daemon_envelope(monkeypatch) -> None:
    client = WebBridgeClient(session="test-session")

    def fake_post(url, json=None, timeout=None):
        class FakeResponse:
            status_code = 200
            text = '{"ok": true, "data": {"type": "string", "value": "hi"}}'

            def json(self):
                return {"ok": True, "data": {"type": "string", "value": "hi"}}

        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    assert client.evaluate("1+1") == "hi"


# WebBridgeClient surfaces daemon-level errors from {"ok": false, "error": {...}}.
def test_webridge_client_daemon_error_raises(monkeypatch) -> None:
    client = WebBridgeClient(session="test-session")

    def fake_post(url, json=None, timeout=None):
        class FakeResponse:
            status_code = 200
            text = '{"ok": false, "error": {"code": "extension_error", "message": "boom"}}'

            def json(self):
                return {"ok": False, "error": {"code": "extension_error", "message": "boom"}}

        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(WebBridgeError) as exc:
        client.command("evaluate", {"code": "x"})
    assert exc.value.reason == "extension_error"


# WebBridgeClient.cdp forwards a CDP method and returns the result payload.
def test_webridge_client_cdp_forwards(monkeypatch) -> None:
    client = WebBridgeClient(session="test-session")
    calls: list[tuple[str, dict | None]] = []

    def fake_command(action, args=None):
        calls.append((action, args))
        return {"result": {"ok": True}}

    monkeypatch.setattr(client, "command", fake_command)
    assert client.cdp("Page.bringToFront", {"x": 1}) == {"ok": True}
    assert calls == [("cdp", {"method": "Page.bringToFront", "params": {"x": 1}})]


# An unreachable daemon raises WebBridgeError with a machine-readable reason.
def test_webridge_client_unreachable(monkeypatch) -> None:
    client = WebBridgeClient(daemon_url="http://127.0.0.1:1", session="test")

    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(WebBridgeError) as exc:
        client.command("navigate")
    assert exc.value.reason == "daemon-unreachable"


def _import_cli():
    """Import the webridge-collect CLI module in-process."""
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_webridge_collect", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# CLI with no refno/URL asks for the reference number.
def test_cli_no_refno_need_input(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setattr(sys, "argv", [module.__file__])
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 2
    payload = json.loads(captured.out)
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["refno"]


# CLI maps an unreachable WebBridge daemon to need_input(jas_session).
def test_cli_webbridge_daemon_down_need_input(tmp_path, monkeypatch, capsys) -> None:
    module = _import_cli()

    def fake_collect_job(**kwargs):
        raise WebBridgeError("daemon unreachable", reason="daemon-unreachable")

    monkeypatch.setattr(module, "collect_job", fake_collect_job)
    # Pre-check passes; the daemon dies mid-run so the except-branch handles it.
    monkeypatch.setattr(module, "ensure_webbridge_daemon", lambda daemon_url: True)
    monkeypatch.setattr(sys, "argv", [module.__file__, "2600827001", "--driver", "webbridge", "--collect-dir", str(tmp_path)])
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 2
    payload = json.loads(captured.out)
    assert payload["missing"] == ["jas_session"]


# CLI http driver collects and then runs the pipeline, reporting HR files.
def test_cli_http_driver_runs_pipeline(tmp_path, monkeypatch, capsys) -> None:
    module = _import_cli()
    manifest = {
        "refno": "2600827001",
        "post_title": "Senior Software Engineer",
        "candidates": [{"appno": "2600827004", "status": "TBC"}],
        "cv_downloaded": ["2600827004"],
        "candidates_without_cv": [],
        "download_failures": [],
    }

    def fake_collect_job(**kwargs):
        return manifest

    def fake_run_pipeline(folder, *, report_dir, engine, no_open, skip_reports):
        return 0, {"status": "success", "hr_files": "Desktop/workbuddy-cv-screen/2600827001"}

    monkeypatch.setattr(module, "collect_job", fake_collect_job)
    monkeypatch.setattr(module, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "2600827001",
            "--driver",
            "http",
            "--base-url",
            DEMO_BASE_URL,
            "--allow-host",
            "jes-web-demo.vercel.app",
            "--collect-dir",
            str(tmp_path),
            "--no-open",
            "--skip-reports",
        ],
    )
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert payload["refno"] == "2600827001"
    assert payload["hr_files"] == "Desktop/workbuddy-cv-screen/2600827001"


# CLI maps a not-found collection to error_code not_found (exit 1).
def test_cli_not_found_reports_error_code(monkeypatch, capsys) -> None:
    module = _import_cli()

    def fake_collect_job(**kwargs):
        raise JobNotFoundError("no JAS job found for refno 999999999")

    monkeypatch.setattr(module, "collect_job", fake_collect_job)
    monkeypatch.setattr(
        sys,
        "argv",
        [module.__file__, "999999999", "--driver", "http", "--collect-dir", "tmp", "--no-pipeline"],
    )
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(captured.err)
    assert payload["status"] == "error"
    assert payload["error_code"] == "not_found"
    assert "999999999" in payload["error_message"]


# When the refno is typed into the filter but no row matches, collect stops with not found
# and the browser stays on the search page (it is never navigated to the fallback URL).
def test_collect_webridge_search_not_found_keeps_page_open(tmp_path) -> None:
    class FakeBrowser:
        # Record navigations; the search finds no row, so the list page must stay open.
        def __init__(self):
            self.urls = []
            self.cdp_calls = []

        def navigate(self, url, *, new_tab=True, group_title=None):
            self.urls.append(url)

        def cdp(self, method, params=None):
            self.cdp_calls.append(method)

        # Simulate typing the refno into the filter with no matching row.
        def evaluate(self, code):
            return {"typed": True, "clicked": False, "reason": "row-not-found"}

        def page_html(self):
            return DEMO_HTML

        def fetch_bytes(self, url):
            return b"%PDF"

    browser = FakeBrowser()
    folder = tmp_path / "job"
    with pytest.raises(JobNotFoundError):
        collect.collect_job(
            records_url=RECORDS_URL,
            folder=folder,
            driver="webbridge",
            base_url=DEMO_BASE_URL,
            refno="999999999",
            client=browser,  # type: ignore[arg-type]
        )
    # Only the list page was opened; the search page was never navigated away from.
    assert browser.urls == [DEMO_BASE_URL + "/"]
    assert not (folder / "records.html").exists()


# ensure_webbridge_daemon returns True immediately when the daemon is already up.
def test_ensure_daemon_already_running(monkeypatch) -> None:
    monkeypatch.setattr(client_mod, "_daemon_reachable", lambda url, timeout=2.0: True)
    monkeypatch.setattr(client_mod, "_extension_connected", lambda url, timeout=2.0: True)
    calls = {"start": 0}

    def fake_start():
        calls["start"] += 1
        return True

    monkeypatch.setattr(client_mod, "_start_daemon_process", fake_start)
    assert ensure_webbridge_daemon(wait_seconds=0.5) is True
    assert calls["start"] == 0


# ensure_webbridge_daemon starts the daemon once and waits for it to come up.
def test_ensure_daemon_auto_starts(monkeypatch) -> None:
    state = {"reachable": False}

    def fake_reachable(url, timeout=2.0):
        state["reachable"] = True  # daemon comes up right after being started
        return state["reachable"]

    monkeypatch.setattr(client_mod, "_daemon_reachable", fake_reachable)
    monkeypatch.setattr(client_mod, "_extension_connected", lambda url, timeout=2.0: True)
    monkeypatch.setattr(client_mod, "_start_daemon_process", lambda: True)
    monkeypatch.setattr(client_mod.time, "sleep", lambda *a, **k: None)
    assert ensure_webbridge_daemon(wait_seconds=0.5) is True


# ensure_webbridge_daemon fails fast when the daemon cannot be started.
def test_ensure_daemon_start_fails(monkeypatch) -> None:
    monkeypatch.setattr(client_mod, "_daemon_reachable", lambda url, timeout=2.0: False)
    monkeypatch.setattr(client_mod, "_start_daemon_process", lambda: False)
    assert ensure_webbridge_daemon(wait_seconds=0.5) is False


# close_session_tabs counts the tabs the daemon reports as closed.
def test_close_session_tabs_counts_closed(monkeypatch) -> None:
    client = WebBridgeClient(session="test-session")
    monkeypatch.setattr(client, "close_session", lambda timeout=None: {"success": True, "closed": 3})
    assert client_mod.close_session_tabs(client) == {"ok": True, "closed": 3, "reason": None}


# Cleanup is best-effort: a browser that is already gone must not fail the screening.
def test_close_session_tabs_never_raises(monkeypatch) -> None:
    client = WebBridgeClient(session="test-session")

    def boom(timeout=None):
        raise WebBridgeError("extension gone", reason="extension-disconnected")

    monkeypatch.setattr(client, "close_session", boom)
    result = client_mod.close_session_tabs(client)
    assert result["ok"] is False
    assert result["closed"] == 0
    assert "extension gone" in result["reason"]


# The HTTP driver opens no tabs, so there is nothing to close.
def test_close_session_tabs_without_browser() -> None:
    result = client_mod.close_session_tabs(None)
    assert result["closed"] == 0
    assert result["ok"] is False


class _FakeBrowser:
    # Stands in for WebBridgeClient: records close_session calls only.
    def __init__(self, *, daemon_url=None, session=None, timeout=None):
        self.closed = 0

    def close_session(self, *, timeout=None):
        self.closed += 1
        return {"success": True, "closed": 2}


def _run_cli(module, monkeypatch, tmp_path, extra_args, pipeline_exit=0, pipeline_status="success"):
    """Run the CLI with fakes and return (exit_code, payload, browsers created)."""
    browsers: list[_FakeBrowser] = []

    def factory(**kwargs):
        browser = _FakeBrowser(**kwargs)
        browsers.append(browser)
        return browser

    monkeypatch.setattr(module, "WebBridgeClient", factory)
    monkeypatch.setattr(module, "ensure_webbridge_daemon", lambda daemon_url: True)
    monkeypatch.setattr(
        module,
        "collect_job",
        lambda **kwargs: {
            "refno": "2600827001",
            "post_title": "Senior Software Engineer",
            "candidates": [{"appno": "2600827004", "status": "TBC"}],
            "cv_downloaded": ["2600827004"],
            "candidates_without_cv": [],
            "download_failures": [],
        },
    )

    def fake_run_pipeline(folder, *, report_dir, engine, no_open, skip_reports):
        return pipeline_exit, {"status": pipeline_status, "hr_files": "Desktop/workbuddy-cv-screen/2600827001"}

    monkeypatch.setattr(module, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [module.__file__, "2600827001", "--driver", "webbridge", "--collect-dir", str(tmp_path), *extra_args],
    )
    return module.main(), browsers


# Once the ranking report is on screen, the WebBridge tabs are closed and counted.
def test_cli_closes_browser_tabs_after_success(tmp_path, monkeypatch, capsys) -> None:
    module = _import_cli()
    exit_code, browsers = _run_cli(module, monkeypatch, tmp_path, [])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["browser_tabs_closed"] == 2
    assert payload["browser_closed"] is True
    assert browsers[0].closed == 1


# --no-open keeps the ranking report closed, so the WebBridge tabs stay open for HR.
def test_cli_no_open_keeps_tabs_open(tmp_path, monkeypatch, capsys) -> None:
    module = _import_cli()
    exit_code, browsers = _run_cli(module, monkeypatch, tmp_path, ["--no-open"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "browser_tabs_closed" not in payload
    assert browsers[0].closed == 0


# --keep-browser leaves the tabs open for HR to inspect.
def test_cli_keep_browser_leaves_tabs_open(tmp_path, monkeypatch, capsys) -> None:
    module = _import_cli()
    exit_code, browsers = _run_cli(module, monkeypatch, tmp_path, ["--keep-browser"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "browser_tabs_closed" not in payload
    assert browsers[0].closed == 0


# A failed pipeline keeps the page open so HR can see what went wrong.
def test_cli_pipeline_error_keeps_tabs_open(tmp_path, monkeypatch, capsys) -> None:
    module = _import_cli()
    exit_code, browsers = _run_cli(module, monkeypatch, tmp_path, [], pipeline_exit=1, pipeline_status="error")
    payload = json.loads(capsys.readouterr().err)
    assert exit_code == 1
    assert "browser_tabs_closed" not in payload
    assert browsers[0].closed == 0


# CLI with a daemon that cannot start returns need_input(jas_session) instead of HTTP fallback.
def test_cli_webbridge_daemon_auto_start_fails_need_input(tmp_path, monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setattr(module, "ensure_webbridge_daemon", lambda daemon_url: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [module.__file__, "2600827001", "--driver", "webbridge", "--collect-dir", str(tmp_path)],
    )
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 2
    payload = json.loads(captured.out)
    assert payload["missing"] == ["jas_session"]
