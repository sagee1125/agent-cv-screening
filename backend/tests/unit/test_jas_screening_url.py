# Unit tests for the live JAS screening URL mode (--records-url).
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from jas_import.errors import JobNotFoundError

# backend/tests/unit/test_jas_screening_url.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCREENING_SCRIPT = SKILLS_DIR / "jas-import" / "scripts" / "run_jas_screening.py"

ALLOWED_URL = "https://jobs.polyu.edu.hk/internal/records.php?refno=260818001"


def _import_screening_module():
    """Import the offline JAS screening CLI module in-process."""
    sys.path.insert(0, str(SCREENING_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_jas_screening_url", SCREENING_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job_payload(refno: str = "260818001") -> dict:
    """Build a mock JAS job payload with two candidates."""
    return {
        "status": "success",
        "source": "jas",
        "refno": refno,
        "job": {"refno": refno, "post_title": "Project Associate"},
        "jd_text": "Post title: Project Associate\nDescription: Python SQL",
        "candidates": [
            {
                "appno": "123456",
                "status": "S",
                "cv_url": f"https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=123456&refno={refno}",
                "supp_url": None,
                "record_detail_url": None,
            },
            {
                "appno": "654321",
                "status": "TBC",
                "cv_url": f"https://jobs.polyu.edu.hk/internal/file.php?t=cv&id=654321&refno={refno}",
                "supp_url": None,
                "record_detail_url": None,
            },
        ],
    }


def _url_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    """Build the URL-mode screening Namespace with defaults."""
    values = {
        "records_url": ALLOWED_URL,
        "cookie_file": None,
        "no_cookie": False,
        "allow_host": [],
        "base_url": None,
        "cleanup_cvs": False,
        "state_dir": str(tmp_path / "state"),
        "scratch_dir": str(tmp_path / "scratch"),
        "output_dir": str(tmp_path / "out"),
        "engine": "legacy",
        "max_retries": 2,
        "skip_reports": True,
        "no_open": True,
        "resume": False,
        "fail_fast": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


# Default URL mode: downloads CVs to scratch, runs, and keeps them for reuse.
def test_run_url_screening_downloads_runs_and_keeps(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        Path(dest).write_bytes(b"%PDF")
        return True, {"etag": None, "last_modified": None}

    captured_cmd: list[list[str]] = []

    def fake_pipeline(cmd):
        captured_cmd.append(cmd)
        return 0, {"status": "success", "candidates": []}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", fake_pipeline)

    exit_code = module.run_url_screening(_url_args(tmp_path, engine="matching"))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert (tmp_path / "scratch" / "260818001" / "123456.pdf").is_file(), "CVs should be kept by default"

    out_dir = tmp_path / "out"
    manifest = json.loads((out_dir / "260818001" / "_pipeline" / "jas-manifest.json").read_text(encoding="utf-8"))
    assert [candidate["appno"] for candidate in manifest["candidates"]] == ["123456", "654321"]

    assert captured_cmd
    cmd = captured_cmd[0]
    assert "--position" in cmd and "Project Associate" in cmd
    assert "--refno" in cmd and "260818001" in cmd
    assert any("260818001" in token and "123456.pdf" in token for token in cmd)
    assert any("260818001" in token and "654321.pdf" in token for token in cmd)


# --cleanup-cvs removes the downloaded CVs from scratch after the run.
def test_run_url_screening_cleanup_cvs_removes(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        Path(dest).write_bytes(b"%PDF")
        return True, {"etag": None, "last_modified": None}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))

    exit_code = module.run_url_screening(_url_args(tmp_path, cleanup_cvs=True))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert not (tmp_path / "scratch" / "260818001").exists()


# When every download fails, the run errors and scratch is still cleaned.
def test_run_url_screening_no_cv_error_cleans(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)

    exit_code = module.run_url_screening(_url_args(tmp_path, cleanup_cvs=True))
    captured = capsys.readouterr()

    assert exit_code == module.EXIT_ERROR
    err = json.loads(captured.err)
    assert err["status"] == "error"
    assert "no candidate CVs could be downloaded" in err["error_message"]
    assert not (tmp_path / "scratch" / "260818001").exists()


# Non-allowlisted records URLs are rejected before any fetch.
def test_run_url_screening_rejects_disallowed_host(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    called: list[str] = []

    async def fake_fetch(url, cookie_file=None, **kwargs):
        called.append(url)
        return _job_payload()

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    exit_code = module.run_url_screening(_url_args(tmp_path, records_url="https://evil.example.com/x"))
    captured = capsys.readouterr()

    assert exit_code == module.EXIT_ERROR
    assert called == []
    err = json.loads(captured.err)
    assert "not allowlisted" in err["error_message"]


# Candidate CV links are independently allowlisted before download.
def test_run_url_screening_rejects_disallowed_candidate_url(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    job = _job_payload()
    job["candidates"] = [{**job["candidates"][0], "cv_url": "https://evil.example.com/cv.pdf"}]
    downloaded: list[str] = []

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return job

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        downloaded.append(url)
        return True, {"etag": None, "last_modified": None}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    exit_code = module.run_url_screening(_url_args(tmp_path))
    captured = capsys.readouterr()

    assert exit_code == module.EXIT_ERROR
    assert downloaded == []
    assert "not allowlisted" in captured.err


# Path-like reference numbers are rejected before creating a scratch job directory.
def test_run_url_screening_rejects_unsafe_refno(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload("../escaped")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    exit_code = module.run_url_screening(_url_args(tmp_path))
    captured = capsys.readouterr()

    assert exit_code == module.EXIT_ERROR
    assert "invalid reference number" in captured.err
    assert not (tmp_path / "escaped").exists()


# Partial CV download failures are surfaced in manifest and stdout on success.
def test_run_url_screening_reports_partial_download_failures(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        if "654321" in url:
            raise RuntimeError("network down")
        Path(dest).write_bytes(b"%PDF")
        return True, {"etag": None, "last_modified": None}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))

    exit_code = module.run_url_screening(_url_args(tmp_path))
    captured = capsys.readouterr()

    assert exit_code == module.EXIT_OK
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert len(payload["download_failures"]) == 1
    assert payload["download_failures"][0]["appno"] == "654321"

    manifest = json.loads((tmp_path / "out" / "260818001" / "_pipeline" / "jas-manifest.json").read_text(encoding="utf-8"))
    assert manifest["candidates_without_cv"] == ["654321"]
    assert manifest["download_failures"][0]["error_message"] == "network down"


# The CLI dispatches --records-url to the live URL mode end-to-end.
def test_main_url_mode_dispatches(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        Path(dest).write_bytes(b"%PDF")
        return True, {"etag": None, "last_modified": None}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--records-url",
            ALLOWED_URL,
            "--cookie-file",
            str(jar),
            "--output-dir",
            str(tmp_path / "out"),
            "--scratch-dir",
            str(tmp_path / "scratch"),
            "--cleanup-cvs",
            "--skip-reports",
        ],
    )

    exit_code = module.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert not (tmp_path / "scratch" / "260818001").exists()


# A 401/403 from JAS asks HR to grant session access again.
def test_run_url_screening_auth_failure_is_need_input(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    exit_code = module.run_url_screening(_url_args(tmp_path))
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == module.EXIT_NEED_INPUT
    assert payload["missing"] == ["jas_session"]

# Build a demo-style records URL for the public jes-web-demo.vercel.app host.
DEMO_BASE_URL = "https://jes-web-demo.vercel.app"


# --base-url builds a demo records URL from a bare refno.
def test_build_records_url_for_refno_base_url() -> None:
    module = _import_screening_module()
    assert (
        module.build_records_url_for_refno("2600827001", DEMO_BASE_URL)
        == "https://jes-web-demo.vercel.app/records.html?refno=2600827001"
    )
    assert (
        module.build_records_url_for_refno("2600827001", None)
        == "https://jobs.polyu.edu.hk/internal/records.php?refno=2600827001"
    )


# A public demo host works when allowlisted via --allow-host with --no-cookie.
def test_run_url_screening_demo_host_allowed(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    captured: dict = {}

    async def fake_fetch(url, cookie_file=None, **kwargs):
        captured["kwargs"] = kwargs
        return _job_payload(refno="2600827001")  # must match the URL refno

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        Path(dest).write_bytes(b"%PDF")
        return True, {"etag": None, "last_modified": None}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))

    args = _url_args(
        tmp_path,
        records_url=f"{DEMO_BASE_URL}/records.html?refno=2600827001",
        no_cookie=True,
        allow_host=["jes-web-demo.vercel.app"],
        base_url=DEMO_BASE_URL,
    )
    exit_code = module.run_url_screening(args)
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert captured["kwargs"]["base_url"] == DEMO_BASE_URL
    assert "jes-web-demo.vercel.app" in captured["kwargs"]["allowed_hosts"]
    # The matching demo job is collected into its own scratch dir (kept for reuse).
    assert (tmp_path / "scratch" / "2600827001").exists()


# main() accepts a bare refno for the public demo without a cookie jar.
def test_main_refno_with_base_url_no_cookie(monkeypatch, capsys) -> None:
    module = _import_screening_module()
    captured: dict = {}

    def fake_run_url_screening(args):
        captured["records_url"] = args.records_url
        captured["base_url"] = args.base_url
        captured["allow_host"] = args.allow_host
        return module.EXIT_OK

    monkeypatch.setattr(module, "run_url_screening", fake_run_url_screening)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "2600827001",
            "--base-url",
            DEMO_BASE_URL,
            "--allow-host",
            "jes-web-demo.vercel.app",
            "--no-cookie",
        ],
    )
    exit_code = module.main()
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert captured["records_url"] == f"{DEMO_BASE_URL}/records.html?refno=2600827001"
    assert captured["allow_host"] == ["jes-web-demo.vercel.app"]

# A kept CV whose server ETag still matches is reused (304) instead of re-downloaded.
def test_run_url_screening_skips_unchanged_cv_download(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    scratch_job = tmp_path / "scratch" / "260818001"
    scratch_job.mkdir(parents=True)
    (scratch_job / "123456.pdf").write_bytes(b"%PDF-v1")
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    state = {
        "schema_version": "job-state-v1",
        "refno": "260818001",
        "history": [],
        "cv_meta": {"123456": {"etag": '"abc123"', "last_modified": "Mon, 31 Aug 2026 09:11:06 GMT"}},
    }
    (state_dir / "260818001.json").write_text(json.dumps(state), encoding="utf-8")

    downloaded: list[str] = []

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        if kwargs.get("etag"):
            return False, {"etag": kwargs["etag"], "last_modified": kwargs.get("last_modified") or ""}
        downloaded.append(url)
        Path(dest).write_bytes(b"%PDF-v2")
        return True, {"etag": '"new-etag"', "last_modified": "Mon, 31 Aug 2026 10:00:00 GMT"}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))

    exit_code = module.run_url_screening(_url_args(tmp_path))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert len(downloaded) == 1 and "654321" in downloaded[0], "only the changed/new CV should be re-downloaded"


# URL mode records run history and CV hashes in the per-refno state file.
def test_run_url_screening_writes_state(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None, **kwargs):
        Path(dest).write_bytes(b"%PDF")
        return True, {"etag": None, "last_modified": None}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to_if_changed", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))

    exit_code = module.run_url_screening(_url_args(tmp_path))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    state = json.loads((tmp_path / "state" / "260818001.json").read_text(encoding="utf-8"))
    assert state["history"][-1]["kind"] == "screen"
    assert state["history"][-1]["result"] == "success"
    assert state["cv_hashes"]["123456"]
    assert state["last_screen"]["candidates"]["123456"] == "S"


# A not-found job in URL mode is reported with error_code not_found (exit 1).
def test_run_url_screening_not_found_reports_error_code(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        raise JobNotFoundError("no JAS job found for refno 260818001")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    exit_code = module.run_url_screening(_url_args(tmp_path))
    captured = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(captured.err)
    assert payload["status"] == "error"
    assert payload["error_code"] == "not_found"
    assert "260818001" in payload["error_message"]


# URL mode refuses to screen when the records page returns a different job.
def test_run_url_screening_wrong_job_reports_not_found(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None, **kwargs):
        return _job_payload(refno="260806012")  # page returns a different job

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    exit_code = module.run_url_screening(_url_args(tmp_path))
    captured = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(captured.err)
    assert payload["status"] == "error"
    assert payload["error_code"] == "not_found"
    assert "260806012" in payload["error_message"]

