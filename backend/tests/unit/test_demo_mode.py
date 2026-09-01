# Unit tests for the demo-mode switch (screening_core.demo_mode).
from __future__ import annotations

import argparse
import json
from pathlib import Path

from screening_core import demo_mode

DEMO_URL = "https://jes-web-demo.vercel.app"


# Write a demo_mode.json with the given enabled flag and return its folder.
def _write_config(tmp_path: Path, *, enabled: bool) -> Path:
    (tmp_path / demo_mode.DEMO_CONFIG_NAME).write_text(
        json.dumps({"enabled": enabled, "base_url": DEMO_URL, "allow_hosts": ["jes-web-demo.vercel.app"]}),
        encoding="utf-8",
    )
    return tmp_path


# An enabled demo_mode.json turns demo mode on with the configured host.
def test_demo_mode_settings_enabled_by_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(demo_mode.DEMO_MODE_ENV, raising=False)
    root = _write_config(tmp_path, enabled=True)
    settings = demo_mode.demo_mode_settings(repo_root=root)
    assert settings == {"base_url": DEMO_URL, "allow_hosts": ["jes-web-demo.vercel.app"]}


# A disabled demo_mode.json keeps the switch off.
def test_demo_mode_settings_disabled_by_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(demo_mode.DEMO_MODE_ENV, raising=False)
    root = _write_config(tmp_path, enabled=False)
    assert demo_mode.demo_mode_settings(repo_root=root) is None


# No config file and no env means demo mode is off.
def test_demo_mode_settings_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(demo_mode.DEMO_MODE_ENV, raising=False)
    assert demo_mode.demo_mode_settings(repo_root=tmp_path) is None


# The env var can force demo mode on even without a config file.
def test_demo_mode_settings_env_on(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(demo_mode.DEMO_MODE_ENV, "1")
    assert demo_mode.demo_mode_settings(repo_root=tmp_path) is not None


# The env var can force demo mode off even when a config file is enabled.
def test_demo_mode_settings_env_off_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(demo_mode.DEMO_MODE_ENV, "0")
    root = _write_config(tmp_path, enabled=True)
    assert demo_mode.demo_mode_settings(repo_root=root) is None


# apply_demo_defaults routes a bare refno run to the demo host and skips the cookie gate.
def test_apply_demo_defaults_bare_refno(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(demo_mode.DEMO_MODE_ENV, raising=False)
    root = _write_config(tmp_path, enabled=True)
    args = argparse.Namespace(base_url=None, records_url=None, allow_host=[], no_cookie=False, cookie_file=None)
    assert demo_mode.apply_demo_defaults(args, repo_root=root) is True
    assert args.base_url == DEMO_URL
    assert "jes-web-demo.vercel.app" in args.allow_host
    assert args.no_cookie is True


# apply_demo_defaults keeps an explicit records URL untouched.
def test_apply_demo_defaults_respects_explicit_url(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(demo_mode.DEMO_MODE_ENV, raising=False)
    root = _write_config(tmp_path, enabled=True)
    args = argparse.Namespace(base_url=None, records_url="https://jobs.polyu.edu.hk/internal/records.php?refno=1", allow_host=[], no_cookie=False, cookie_file=None)
    assert demo_mode.apply_demo_defaults(args, repo_root=root) is True
    assert args.base_url is None
    assert args.records_url == "https://jobs.polyu.edu.hk/internal/records.php?refno=1"