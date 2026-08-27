# Unit tests for the live JAS screening URL mode (--records-url).
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

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
        "keep_cvs": False,
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


# Default URL mode: downloads CVs to scratch, runs, then cleans scratch.
def test_run_url_screening_downloads_runs_and_cleans(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    captured_cmd: list[list[str]] = []

    def fake_pipeline(cmd):
        captured_cmd.append(cmd)
        return 0, {"status": "success", "candidates": []}

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", fake_pipeline)

    exit_code = module.run_url_screening(_url_args(tmp_path, engine="matching"))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert not (tmp_path / "scratch" / "260818001").exists(), "scratch should be cleaned by default"

    out_dir = tmp_path / "out"
    manifest = json.loads((out_dir / "260818001" / "_pipeline" / "jas-manifest.json").read_text(encoding="utf-8"))
    assert [candidate["appno"] for candidate in manifest["candidates"]] == ["123456", "654321"]

    assert captured_cmd
    cmd = captured_cmd[0]
    assert "--position" in cmd and "Project Associate" in cmd
    assert "--refno" in cmd and "260818001" in cmd
    assert any("260818001" in token and "123456.pdf" in token for token in cmd)
    assert any("260818001" in token and "654321.pdf" in token for token in cmd)


# --keep-cvs retains the downloaded CVs in scratch.
def test_run_url_screening_keep_cvs_retains(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))

    exit_code = module.run_url_screening(_url_args(tmp_path, keep_cvs=True))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    scratch_job = tmp_path / "scratch" / "260818001"
    assert (scratch_job / "123456.pdf").is_file()
    assert (scratch_job / "654321.pdf").is_file()


# When every download fails, the run errors and scratch is still cleaned.
def test_run_url_screening_no_cv_error_cleans(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to", fake_download)

    exit_code = module.run_url_screening(_url_args(tmp_path))
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

    async def fake_fetch(url, cookie_file=None):
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

    async def fake_fetch(url, cookie_file=None):
        return job

    async def fake_download(url, dest, cookie_file=None):
        downloaded.append(url)
        return Path(dest)

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to", fake_download)
    exit_code = module.run_url_screening(_url_args(tmp_path))
    captured = capsys.readouterr()

    assert exit_code == module.EXIT_ERROR
    assert downloaded == []
    assert "not allowlisted" in captured.err


# Path-like reference numbers are rejected before creating a scratch job directory.
def test_run_url_screening_rejects_unsafe_refno(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()

    async def fake_fetch(url, cookie_file=None):
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

    async def fake_fetch(url, cookie_file=None):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None):
        if "654321" in url:
            raise RuntimeError("network down")
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to", fake_download)
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

    async def fake_fetch(url, cookie_file=None):
        return _job_payload()

    async def fake_download(url, dest, cookie_file=None):
        Path(dest).write_bytes(b"%PDF")
        return Path(dest)

    monkeypatch.setattr(module, "fetch_job_payload", fake_fetch)
    monkeypatch.setattr(module, "download_to", fake_download)
    monkeypatch.setattr(module, "_run_pipeline", lambda cmd: (0, {"status": "success", "candidates": []}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--records-url",
            ALLOWED_URL,
            "--output-dir",
            str(tmp_path / "out"),
            "--scratch-dir",
            str(tmp_path / "scratch"),
            "--skip-reports",
        ],
    )

    exit_code = module.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert not (tmp_path / "scratch" / "260818001").exists()