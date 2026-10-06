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


# build_records_url honors an explicit --base-url, and otherwise takes the URL from the
# active site profile: the switch decides the host, not the absence of a base URL.
def test_build_records_url_base_url(monkeypatch) -> None:
    assert collect.build_records_url("2600827001", DEMO_BASE_URL) == RECORDS_URL
    monkeypatch.setenv("JES_SITE_MODE", "0")
    assert collect.build_records_url("2600827001", None) == RECORDS_URL
    monkeypatch.setenv("JES_SITE_MODE", "1")
    assert (
        collect.build_records_url("2600827001", None)
        == "https://jobs.polyu.edu.hk/internal/records.php?refno=2600827001"
    )


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
    # A single-post page gains the null post key and no post list (PRD Section 6).
    assert manifest["candidates"][0]["post"] is None
    assert "posts" not in manifest


# §1.6: cvs/ starts empty, so a file left by an earlier run — possibly a run on the other site —
# can never sit in the folder and be scored as one of this run's applicants.
def test_collect_clears_stale_cvs_before_collecting(tmp_path, monkeypatch) -> None:
    async def fake_fetch_html(url, cookie_file=None, allowed_hosts=None):
        return DEMO_HTML

    async def fake_download_to(url, dest, cookie_file=None, allowed_hosts=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(collect._jas_fetch, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(collect._jas_fetch, "download_to", fake_download_to)

    folder = tmp_path / "job"
    stale_dir = folder / "cvs"
    stale_dir.mkdir(parents=True)
    (stale_dir / "9999999999.pdf").write_bytes(b"stale-from-an-earlier-run")
    (stale_dir / "notes.txt").write_text("stray", encoding="utf-8")

    manifest = collect.collect_job(
        records_url=RECORDS_URL,
        folder=folder,
        driver="http",
        base_url=DEMO_BASE_URL,
        allowed_hosts=ALLOWED,
    )

    assert (folder / "cvs" / "2600827004.pdf").is_file()
    assert not (folder / "cvs" / "9999999999.pdf").exists()
    assert not (folder / "cvs" / "notes.txt").exists()
    assert sorted(path.name for path in (folder / "cvs").iterdir()) == ["2600827004.pdf"]
    assert manifest["cv_downloaded"] == ["2600827004"]


# A multi-post page carries the post per candidate and the per-post counts (PRD Section 6).
def test_collect_multi_post_manifest_carries_the_post_dimension(tmp_path, monkeypatch) -> None:
    from jas_import import mock

    html = mock.mock_records_html("260818001", multi_post=True)

    async def fake_fetch_html(url, cookie_file=None, allowed_hosts=None):
        return html

    async def fake_download_to(url, dest, cookie_file=None, allowed_hosts=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(collect._jas_fetch, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(collect._jas_fetch, "download_to", fake_download_to)

    folder = tmp_path / "job"
    manifest = collect.collect_job(
        records_url="https://jes-web-demo.vercel.app/records.html?refno=260818001",
        folder=folder,
        driver="http",
        base_url=DEMO_BASE_URL,
        allowed_hosts=ALLOWED,
    )

    assert manifest["multi_post"] is True
    assert manifest["posts"] == [
        {"post": "Project Associate", "applicants": 1},
        {"post": "Project Assistant", "applicants": 1},
    ]
    assert [candidate["post"] for candidate in manifest["candidates"]] == [
        "Project Associate",
        "Project Assistant",
    ]
    # The folder on disk is still one folder per refno, and the manifest matches what was returned.
    on_disk = json.loads((folder / collect.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert on_disk["posts"] == manifest["posts"]


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


# When the list filter cannot be driven, collection falls back to the direct records URL and records it.
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
    assert manifest["human_flow"] == "fallback_direct_url"


# A successful View-link click is recorded as view_link on the manifest.
def test_collect_webridge_human_flow_view_link(tmp_path) -> None:
    class FakeBrowser:
        def __init__(self):
            self.urls = []

        def navigate(self, url, *, new_tab=True, group_title=None):
            self.urls.append(url)

        def cdp(self, method, params=None):
            pass

        def evaluate(self, code):
            return {"typed": True, "clicked": True, "href": RECORDS_URL, "text": "View"}

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
    assert manifest["human_flow"] == "view_link"


# A list split across pages is followed: the next-page link is opened, then the row's View link.
def test_navigate_like_human_follows_next_list_page() -> None:
    class FakeBrowser:
        # First look reports a pager link; the reloaded page then has the row.
        def __init__(self):
            self.urls = []
            self.scripts = []

        def navigate(self, url, *, new_tab=True, group_title=None):
            self.urls.append(url)

        def cdp(self, method, params=None):
            pass

        def evaluate(self, code):
            self.scripts.append(code)
            if len(self.scripts) == 1:
                return {
                    "typed": True,
                    "clicked": False,
                    "reason": "next-page",
                    "href": "https://jobs.polyu.edu.hk/internal/records.php?page=2",
                }
            return {
                "typed": False,
                "clicked": True,
                "href": "https://jobs.polyu.edu.hk/internal/records.php?refno=190001010",
                "text": "View",
            }

    browser = FakeBrowser()
    target, flow = collect.navigate_like_human(
        browser,  # type: ignore[arg-type]
        refno="190001010",
        list_url="https://jobs.polyu.edu.hk/internal/records.php",
        records_url="https://jobs.polyu.edu.hk/internal/records.php?refno=190001010",
        tab_group_title="JAS screening",
    )
    assert target == "https://jobs.polyu.edu.hk/internal/records.php?refno=190001010"
    assert flow == "view_link_paged"
    assert browser.urls == [
        "https://jobs.polyu.edu.hk/internal/records.php",
        "https://jobs.polyu.edu.hk/internal/records.php?page=2",
    ]
    assert "const typeFilter = true" in browser.scripts[0]
    assert "const typeFilter = false" in browser.scripts[1]


# An in-page pager (no reload) is recorded as paged once the script reports the turns.
def test_navigate_like_human_records_in_page_turns() -> None:
    class FakeBrowser:
        def __init__(self):
            self.urls = []

        def navigate(self, url, *, new_tab=True, group_title=None):
            self.urls.append(url)

        def cdp(self, method, params=None):
            pass

        def evaluate(self, code):
            return {"typed": True, "clicked": True, "href": RECORDS_URL, "pages_turned": 2}

    browser = FakeBrowser()
    target, flow = collect.navigate_like_human(
        browser,  # type: ignore[arg-type]
        refno="2600827001",
        list_url=DEMO_BASE_URL + "/",
        records_url=RECORDS_URL,
        tab_group_title="JES demo screening",
    )
    assert target == RECORDS_URL
    assert flow == "view_link_paged"
    assert browser.urls == [DEMO_BASE_URL + "/"]


# The same next-page address is not opened twice, and the search then stops as not found.
def test_navigate_like_human_stops_on_repeated_next_page() -> None:
    class FakeBrowser:
        def __init__(self):
            self.urls = []

        def navigate(self, url, *, new_tab=True, group_title=None):
            self.urls.append(url)

        def cdp(self, method, params=None):
            pass

        def evaluate(self, code):
            return {
                "typed": True,
                "clicked": False,
                "reason": "next-page",
                "href": "https://jobs.polyu.edu.hk/internal/records.php?page=2",
            }

    browser = FakeBrowser()
    target, flow = collect.navigate_like_human(
        browser,  # type: ignore[arg-type]
        refno="190001010",
        list_url="https://jobs.polyu.edu.hk/internal/records.php",
        records_url="https://jobs.polyu.edu.hk/internal/records.php?refno=190001010",
        tab_group_title="JAS screening",
    )
    assert target is None
    assert flow == "not_found"
    assert browser.urls == [
        "https://jobs.polyu.edu.hk/internal/records.php",
        "https://jobs.polyu.edu.hk/internal/records.php?page=2",
    ]


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


# A CV is downloaded over HTTP with the browser's cookies. The file URL is never opened.
def test_webridge_client_fetch_bytes_uses_http_session(monkeypatch) -> None:
    client = WebBridgeClient(session="test-session")
    cv_url = "https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=300880&refno=260625010"
    records = "https://jobs.polyu.edu.hk/internal/records.php?refno=260625010"
    calls: list[tuple] = []
    captured: dict = {}

    def fake_command(action, args=None, timeout=None):
        calls.append((action, args))
        if action == "list_tabs":
            return {"tabs": [{"url": records, "active": True}]}
        if action == "cdp":
            return {"cookies": [{"name": "PHPSESSID", "value": "session"}]}
        if action == "evaluate":
            return {"value": "Mozilla/5.0 Test"}
        return {}

    def fake_download(url, headers):
        captured["url"] = url
        captured["headers"] = headers
        return b"%PDF-1.4"

    monkeypatch.setattr(client, "command", fake_command)
    monkeypatch.setattr(client_mod, "_http_download", fake_download)
    assert client.fetch_bytes(cv_url).startswith(b"%PDF")
    assert captured["url"] == cv_url
    assert captured["headers"]["Referer"] == records
    assert captured["headers"]["Sec-Fetch-Mode"] == "navigate"
    assert "PHPSESSID=session" in captured["headers"]["Cookie"]
    assert not any(action == "navigate" for action, _args in calls)


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

    def fake_run_pipeline(folder, *, report_dir, engine, no_open, skip_reports, conditions=None, site=None):
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


# ensure_webbridge_daemon returns False when the daemon is up but the extension never connects.
def test_ensure_daemon_extension_never_connects(monkeypatch) -> None:
    monkeypatch.setattr(client_mod, "_daemon_reachable", lambda url, timeout=2.0: True)
    monkeypatch.setattr(client_mod, "_extension_connected", lambda url, timeout=2.0: False)
    monkeypatch.setattr(client_mod.time, "sleep", lambda *a, **k: None)
    assert ensure_webbridge_daemon(wait_seconds=0.5, extension_wait=0.5) is False


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

    def fake_run_pipeline(folder, *, report_dir, engine, no_open, skip_reports, conditions=None, site=None):
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


# --- the sign-in gate -------------------------------------------------------
#
# A site that requires a login must be signed in *before* the collector reads the page.
# Without the gate a logged-out run reads the identity provider's page, which parses as
# "no job" — so HR is told the job does not exist when the session is what is missing.


# A prod-shaped profile, taken from the shipped profile so the test tracks the real thing.
def _prod_profile() -> dict:
    from screening_core.site_mode import site_profile

    return site_profile("prod")


# A browser whose answer to the shared sign-in probe is scripted.
class _ProbeBrowser:
    def __init__(self, *, path: str, has_table: bool) -> None:
        self.path = path
        self.has_table = has_table
        self.urls: list[str] = []

    def navigate(self, url, *, new_tab=True, group_title=None):
        self.urls.append(url)

    def cdp(self, method, params=None):
        pass

    # The sign-in probe is identified by its own selector text, so one fake can answer both
    # the probe and the ghost-cursor script the human flow runs.
    def evaluate(self, code):
        if "has_table" in code:
            return {"path": self.path, "has_table": self.has_table}
        return {"typed": True, "clicked": True, "href": RECORDS_URL, "text": "View"}

    def page_html(self):
        return DEMO_HTML

    def fetch_bytes(self, url):
        return b"%PDF"


# Logged out on prod: the run stops before it reads or writes anything, with a sign-in message.
def test_prod_collect_refuses_when_not_signed_in(tmp_path) -> None:
    from jas_import.errors import SiteLoginRequiredError

    browser = _ProbeBrowser(path="/sso/login", has_table=False)
    folder = tmp_path / "job"
    with pytest.raises(SiteLoginRequiredError) as excinfo:
        collect.collect_job(
            records_url=RECORDS_URL,
            folder=folder,
            profile=_prod_profile(),
            driver="webbridge",
            base_url=DEMO_BASE_URL,
            refno="2600827001",
            client=browser,  # type: ignore[arg-type]
        )
    assert "sign in" in str(excinfo.value).lower()
    # The gate runs before the page is read, so no half-collected job is left on disk.
    assert not (folder / "records.html").exists()


# Signed in on prod: the same run proceeds and collects normally.
def test_prod_collect_proceeds_when_signed_in(tmp_path) -> None:
    browser = _ProbeBrowser(path="/internal/records.php", has_table=True)
    folder = tmp_path / "job"
    manifest = collect.collect_job(
        records_url=RECORDS_URL,
        folder=folder,
        profile=_prod_profile(),
        driver="webbridge",
        base_url=DEMO_BASE_URL,
        refno="2600827001",
        client=browser,  # type: ignore[arg-type]
    )
    assert (folder / "records.html").is_file()
    assert manifest["site"] == "prod"


# The demo has no login, so the gate must never fire there — even with no session at all.
def test_demo_collect_is_not_gated(tmp_path) -> None:
    from screening_core.site_mode import site_profile

    browser = _ProbeBrowser(path="/", has_table=False)
    folder = tmp_path / "job"
    manifest = collect.collect_job(
        records_url=RECORDS_URL,
        folder=folder,
        profile=site_profile("demo"),
        driver="webbridge",
        base_url=DEMO_BASE_URL,
        refno="2600827001",
        client=browser,  # type: ignore[arg-type]
    )
    assert manifest["site"] == "demo"


# A page that renders the records table but is not inside the internal area is not a signed-in
# session: the identity provider is unknown, so only landing inside /internal/ counts.
def test_prod_collect_refuses_a_table_outside_the_internal_area(tmp_path) -> None:
    from jas_import.errors import SiteLoginRequiredError

    browser = _ProbeBrowser(path="/sso/login", has_table=True)
    with pytest.raises(SiteLoginRequiredError):
        collect.collect_job(
            records_url=RECORDS_URL,
            folder=tmp_path / "job",
            profile=_prod_profile(),
            driver="webbridge",
            base_url=DEMO_BASE_URL,
            refno="2600827001",
            client=browser,  # type: ignore[arg-type]
        )


# The probe is shared with the readiness check: the run and the check must agree on what
# "signed in" means, or a run could pass the check and then read a login page.
def test_probe_sign_in_is_the_shared_test() -> None:
    from webridge_collect.login import LOGIN_PROBE_JS, probe_sign_in

    assert "has_table" in LOGIN_PROBE_JS and "/internal/" not in LOGIN_PROBE_JS
    assert probe_sign_in(_ProbeBrowser(path="/internal/records.php", has_table=True))["signed_in"] is True
    assert probe_sign_in(_ProbeBrowser(path="/internal/records.php", has_table=False))["signed_in"] is False
    assert probe_sign_in(_ProbeBrowser(path="/sso/login", has_table=True))["signed_in"] is False


# A client that cannot answer the probe is treated as not signed in (fail closed).
def test_probe_sign_in_fails_closed_on_a_silent_client() -> None:
    from webridge_collect.login import probe_sign_in

    class _Silent:
        def evaluate(self, code):
            return None

    assert probe_sign_in(_Silent())["signed_in"] is False


# CLI maps a missing session to need_input(jas_session) with the sign-in question — the same
# contract the readiness check uses, so HR reads one sentence about signing in either way.
def test_cli_missing_session_asks_hr_to_sign_in(tmp_path, monkeypatch, capsys) -> None:
    from jas_import.errors import SiteLoginRequiredError

    module = _import_cli()

    def fake_collect_job(**kwargs):
        raise SiteLoginRequiredError("not signed in to the internal job system")

    monkeypatch.setattr(module, "collect_job", fake_collect_job)
    monkeypatch.setattr(module, "ensure_webbridge_daemon", lambda daemon_url: True)
    monkeypatch.setattr(
        sys, "argv", [module.__file__, "2600827001", "--driver", "webbridge", "--collect-dir", str(tmp_path)]
    )
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 2
    payload = json.loads(captured.out)
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["jas_session"]
    assert "sign in" in payload["questions"][0].lower()
