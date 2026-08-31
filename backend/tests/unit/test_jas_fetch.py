# Unit tests for the JAS live-fetch skeleton (cookie jar, download, JD from URL).
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# backend/tests/unit/test_jas_fetch.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"

from jas_import import fetch  # noqa: E402
from jas_import.mock import mock_records_html  # noqa: E402

ALLOWED_JD_URL = "https://jobs.polyu.edu.hk/internal/records.php?refno=260818001"
ALLOWED_CV_URL = "https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=123456&refno=260818001"


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


# Netscape cookies.txt lines load into an httpx cookie jar.
def test_load_cookie_file_parses_netscape(tmp_path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        "jobs.polyu.edu.hk\tTRUE\t/\tFALSE\t1735689600\tPHPSESSID\tabc123\n",
        encoding="utf-8",
    )
    cookies = fetch.load_cookie_file(cookie_file)
    assert cookies.get("PHPSESSID") == "abc123"


# HttpOnly Netscape cookie lines are parsed instead of treated as comments.
def test_load_cookie_file_parses_httponly_cookie(tmp_path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "#HttpOnly_.jobs.polyu.edu.hk\tTRUE\t/\tTRUE\t1735689600\tPHPSESSID\tsecret\n",
        encoding="utf-8",
    )
    cookies = fetch.load_cookie_file(cookie_file)
    assert cookies.get("PHPSESSID") == "secret"


# Redirect targets are allowlisted before the client follows them.
def test_request_rejects_redirect_to_disallowed_host(monkeypatch) -> None:
    class FakeClient:
        """Provides one redirect response without making a network request."""

        # Accepts the same construction arguments as httpx.AsyncClient.
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        # Enters the fake async client context.
        async def __aenter__(self):
            return self

        # Leaves the fake async client context.
        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        # Returns a redirect to a non-allowlisted host.
        async def get(self, url):
            request = fetch.httpx.Request("GET", url)
            return fetch.httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private"},
                request=request,
            )

    monkeypatch.setattr(fetch.httpx, "AsyncClient", FakeClient)
    with pytest.raises(ValueError, match="not allowlisted"):
        asyncio.run(fetch._request(ALLOWED_JD_URL, None, 1.0))


# CV filenames derive from the id query parameter with a safe extension.
def test_cv_filename_for_url() -> None:
    assert fetch.cv_filename_for_url(ALLOWED_CV_URL) == "123456.pdf"
    assert fetch.cv_filename_for_url("https://jobs.polyu.edu.hk/internal/file.php?t=supp&id=654321") == "654321.pdf"
    # id (application no.) takes priority over the path stem
    assert fetch.cv_filename_for_url("https://jobs.polyu.edu.hk/x/attachment.doc?id=7") == "7.doc"
    # without id, the path stem is used and the extension is preserved
    assert fetch.cv_filename_for_url("https://jobs.polyu.edu.hk/x/attachment.doc") == "attachment.doc"


# Plain-text fallback strips tags for non-JAS pages.
def test_html_to_text_fallback() -> None:
    text = fetch.html_to_text("<html><body><h1>Hello</h1><p>Requirements: Python</p></body></html>")
    assert "Hello" in text and "Requirements: Python" in text


# A JAS records page fetched from a URL parses into structured JD text.
def test_fetch_jd_text_parses_jas_page(monkeypatch) -> None:
    async def fake_request(url, cookie_file, timeout, allowed_hosts=None):
        class Response:
            text = mock_records_html()
            content = b""
        return Response()

    monkeypatch.setattr(fetch, "_request", fake_request)
    text = asyncio.run(fetch.fetch_jd_text(ALLOWED_JD_URL))
    assert "Post title: Project Associate" in text
    assert "Python" in text and "SQL" in text


# A fetched records page returns the full job payload (JD + candidates).
def test_fetch_job_payload_parses_records_page(monkeypatch) -> None:
    async def fake_request(url, cookie_file, timeout, allowed_hosts=None):
        class Response:
            text = mock_records_html()
            content = b""
        return Response()

    monkeypatch.setattr(fetch, "_request", fake_request)
    payload = asyncio.run(fetch.fetch_job_payload(ALLOWED_JD_URL))
    assert payload["refno"] == "260818001"
    assert payload["job"]["post_title"] == "Project Associate"
    assert [candidate["appno"] for candidate in payload["candidates"]] == ["123456", "654321"]
    assert payload["candidates"][0]["cv_url"].endswith("file.php?t=cv&id=123456&refno=260818001")


# Non-JAS pages are rejected so candidate-table PII cannot become JD text.
def test_fetch_jd_text_rejects_page_without_jd_table(monkeypatch) -> None:
    async def fake_request(url, cookie_file, timeout, allowed_hosts=None):
        class Response:
            text = "<html><body><p>Requirements: Python and SQL.</p></body></html>"
            content = b""
        return Response()

    monkeypatch.setattr(fetch, "_request", fake_request)
    with pytest.raises(ValueError, match="job advertisement table"):
        asyncio.run(fetch.fetch_jd_text(ALLOWED_JD_URL))


# fetch_job_payload rejects pages that have refno but no JD advertisement table.
def test_fetch_job_payload_rejects_page_without_jd_table(monkeypatch) -> None:
    candidate_only_html = """
    <html><body>
    <table class="listTable job-detail-table"><tbody><tr>
      <td class="f-data-1">1</td>
      <td class="f-data-1">123456</td>
      <td class="f-data-1"><a href="https://jobs.polyu.edu.hk/internal/record_detail.php?id=123456&amp;refno=260818001">form</a></td>
      <td class="f-data-1">TBC</td>
      <td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td>
      <td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td>
      <td class="f-data-1"></td><td class="f-data-1"></td>
      <td class="f-data-1"><a href="https://jobs.polyu.edu.hk/internal/file.php?t=cv&amp;id=123456&amp;refno=260818001">cv</a></td>
      <td class="f-data-1"></td>
    </tr></tbody></table>
    </body></html>
    """

    async def fake_request(url, cookie_file, timeout, allowed_hosts=None):
        class Response:
            text = candidate_only_html
            content = b""
        return Response()

    monkeypatch.setattr(fetch, "_request", fake_request)
    with pytest.raises(ValueError, match="job advertisement table"):
        asyncio.run(fetch.fetch_job_payload(ALLOWED_JD_URL))


# download_to writes the fetched bytes to the destination.
def test_download_to_writes_bytes(tmp_path, monkeypatch) -> None:
    async def fake_request(url, cookie_file, timeout, allowed_hosts=None):
        class Response:
            content = b"%PDF-fake"
            text = ""
        return Response()

    monkeypatch.setattr(fetch, "_request", fake_request)
    dest = tmp_path / "123456.pdf"
    asyncio.run(fetch.download_to(ALLOWED_CV_URL, dest))
    assert dest.read_bytes() == b"%PDF-fake"


# Empty downloads are rejected instead of writing empty files.
def test_download_to_rejects_empty(tmp_path, monkeypatch) -> None:
    async def fake_request(url, cookie_file, timeout, allowed_hosts=None):
        class Response:
            content = b""
            text = ""
        return Response()

    monkeypatch.setattr(fetch, "_request", fake_request)
    with pytest.raises(ValueError):
        asyncio.run(fetch.download_to(ALLOWED_CV_URL, tmp_path / "x.pdf"))


# Pipeline resolves --jd-url / --cv-url into local files before the run.
def test_pipeline_resolve_url_inputs(tmp_path, monkeypatch) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    async def fake_fetch_jd_text(url, cookie_file=None):
        return "Post title: Project Associate\nDescription: Python SQL"

    async def fake_download_to(url, dest, cookie_file=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(module, "fetch_jd_text", fake_fetch_jd_text)
    monkeypatch.setattr(module, "download_to", fake_download_to)

    args = argparse.Namespace(
        jd_url=ALLOWED_JD_URL,
        cv_url=[ALLOWED_CV_URL],
        cookie_file=None,
        scratch_dir=str(tmp_path / "scratch"),
        jd_file=None,
        cv=[],
        extracted=[],
        jd_json=None,
        polyu_ref=None,
        polyu_detail_url=None,
    )
    module._resolve_url_inputs(args, out_dir)

    assert args.jd_file == str(out_dir / "jd-from-url.txt")
    assert (out_dir / "jd-from-url.txt").read_text(encoding="utf-8") == "Post title: Project Associate\nDescription: Python SQL"
    assert any(str(tmp_path / "scratch" / "123456.pdf") == path for path in args.cv)


# A --jd-url resolves first, then missing CVs surface as need_input.
def test_pipeline_jd_url_reaches_need_input_for_candidates(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")

    async def fake_fetch_jd_text(url, cookie_file=None):
        return "Post title: Project Associate\nDescription: Python"

    monkeypatch.setattr(module, "fetch_jd_text", fake_fetch_jd_text)
    exit_code, out, _err = _run_module(
        module,
        ["--jd-url", ALLOWED_JD_URL, "--skip-reports", "--output-dir", str(tmp_path / "out")],
        monkeypatch,
        capsys,
    )
    assert exit_code == 2
    payload = json.loads(out)
    assert payload["status"] == "need_input"
    assert payload["missing"] == ["candidates"]


# Missing JD is reported before a --cv-url download can write candidate PII.
def test_pipeline_missing_jd_does_not_download_cv(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    downloaded: list[str] = []

    async def fake_download_to(url, dest, cookie_file=None):
        downloaded.append(url)
        return Path(dest)

    monkeypatch.setattr(module, "download_to", fake_download_to)
    exit_code, out, _err = _run_module(
        module,
        ["--cv-url", ALLOWED_CV_URL, "--skip-reports", "--output-dir", str(tmp_path / "out")],
        monkeypatch,
        capsys,
    )
    assert exit_code == 2
    assert json.loads(out)["missing"] == ["jd"]
    assert downloaded == []


# Pipeline removes downloaded CVs when a later stage fails.
def test_pipeline_cleans_downloaded_cv_after_failure(tmp_path, monkeypatch, capsys) -> None:
    module = _import_script("pipeline", "run_pipeline.py")
    jd = tmp_path / "jd.txt"
    jd.write_text("Requirements: Python", encoding="utf-8")
    scratch = tmp_path / "scratch"

    async def fake_download_to(url, dest, cookie_file=None):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(module, "download_to", fake_download_to)
    monkeypatch.setattr(module, "_resolve_jd_source", lambda args, out_dir: (_ for _ in ()).throw(RuntimeError("stop")))
    exit_code, _out, err = _run_module(
        module,
        [
            "--jd-file",
            str(jd),
            "--cv-url",
            ALLOWED_CV_URL,
            "--scratch-dir",
            str(scratch),
            "--skip-reports",
        ],
        monkeypatch,
        capsys,
    )
    assert exit_code == 1
    assert "stop" in err
    assert not (scratch / "123456.pdf").exists()


# Screening-agent forwards URL/cookie/scratch flags to the pipeline command.
def test_run_agent_forwards_url_flags(tmp_path) -> None:
    module = _import_script("screening-agent", "run_agent.py")
    args = argparse.Namespace(
        engine="legacy",
        pipeline_max_retries=2,
        resume=False,
        fail_fast=False,
        skip_reports=True,
        reference_date=None,
        position="Project Associate",
        jd_file=None,
        jd_json=None,
        polyu_ref=None,
        polyu_detail_url=None,
        cv=[],
        extracted=[],
        trust_extracted=False,
        jd_url=ALLOWED_JD_URL,
        cv_url=[ALLOWED_CV_URL],
        cookie_file=str(tmp_path / "cookies.txt"),
        scratch_dir="data/jas_scratch",
    )
    cmd = module._pipeline_cmd(args, tmp_path / "out", resume=False)
    assert "--jd-url" in cmd and ALLOWED_JD_URL in cmd
    assert "--cv-url" in cmd and ALLOWED_CV_URL in cmd
    assert "--cookie-file" in cmd
    assert "--scratch-dir" in cmd

# fetch_job_payload threads base_url through so relative CV links resolve to the demo host.
def test_fetch_job_payload_base_url_resolves_cv_links(monkeypatch) -> None:
    html = """
    <html><body>
    <table class="listTable job-detail-table"><tbody><tr>
      <td class="f-data-1">1</td>
      <td class="f-data-1">123456</td>
      <td class="f-data-1"><a href="/record_detail.php?id=123456&amp;refno=260818001">form</a></td>
      <td class="f-data-1">TBC</td>
      <td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td>
      <td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td><td class="f-data-1"></td>
      <td class="f-data-1"></td><td class="f-data-1"><a href="/uploads/CV.pdf">cv</a></td><td class="f-data-1"></td>
    </tr></tbody></table>
    <p>Job advertisement information</p>
    <table><tbody>
      <tr><td class="f-header">Reference number</td><td class="f-data-1">260818001</td></tr>
      <tr><td class="f-header">Post title</td><td class="f-data-1">Project Associate</td></tr>
      <tr><td class="f-header">Description</td><td class="f-data-1"><p>Python SQL</p></td></tr>
    </tbody></table>
    </body></html>
    """

    async def fake_request(url, cookie_file, timeout, allowed_hosts=None):
        class Response:
            text = html
            content = b""
        return Response()

    monkeypatch.setattr(fetch, "_request", fake_request)
    payload = asyncio.run(
        fetch.fetch_job_payload(
            "https://jes-web-demo.vercel.app/records.html?refno=260818001",
            base_url="https://jes-web-demo.vercel.app",
            allowed_hosts=("jes-web-demo.vercel.app",),
        )
    )
    assert payload["refno"] == "260818001"
    assert payload["candidates"][0]["cv_url"] == "https://jes-web-demo.vercel.app/uploads/CV.pdf"


# _request passes the resolved TLS verify setting to the httpx client.
def test_request_passes_resolved_ssl_verify(monkeypatch) -> None:
    captured: dict = {}

    class FakeClient:
        # Captures the client construction kwargs for assertions.
        def __init__(self, **kwargs):
            captured.update(kwargs)

        # Enters the fake async client context.
        async def __aenter__(self):
            return self

        # Leaves the fake async client context.
        async def __aexit__(self, exc_type, exc, traceback):
            return None

        # Returns a plain 200 response for the allowlisted URL.
        async def get(self, url):
            request = fetch.httpx.Request("GET", url)
            return fetch.httpx.Response(200, content=b"ok", request=request)

    monkeypatch.setattr(fetch, "resolve_ssl_verify", lambda: False)
    monkeypatch.setattr(fetch.httpx, "AsyncClient", FakeClient)
    html = asyncio.run(fetch.fetch_html(ALLOWED_JD_URL))
    assert html == "ok"
    assert captured["verify"] is False
