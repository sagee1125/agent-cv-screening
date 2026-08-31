# Unit tests for the JAS_SSL_VERIFY TLS resolution helper.
from __future__ import annotations

import ssl
import sys
from pathlib import Path

# backend/tests/unit/test_ssl_verify.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_SRC = REPO_ROOT / ".codex" / "skills" / "_shared" / "src"
sys.path.insert(0, str(SHARED_SRC))

from screening_core.ssl_verify import os_trust_context, resolve_ssl_verify  # noqa: E402


# Default (no env) falls back to boolean verification (certifi-style).
def test_default_returns_true_without_env(monkeypatch) -> None:
    monkeypatch.delenv("JAS_SSL_VERIFY", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert resolve_ssl_verify() is True


# An explicit SSL_CERT_FILE makes the default use the OS/system store.
def test_default_uses_system_store_when_ssl_cert_file_set(monkeypatch) -> None:
    monkeypatch.delenv("JAS_SSL_VERIFY", raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", "C:/some/cacert.pem")
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert isinstance(resolve_ssl_verify(), ssl.SSLContext)


# JAS_SSL_VERIFY=0 disables verification explicitly.
def test_env_zero_disables_verification(monkeypatch) -> None:
    monkeypatch.setenv("JAS_SSL_VERIFY", "0")
    assert resolve_ssl_verify() is False


# JAS_SSL_VERIFY=false disables verification explicitly.
def test_env_false_disables_verification(monkeypatch) -> None:
    monkeypatch.setenv("JAS_SSL_VERIFY", "false")
    assert resolve_ssl_verify() is False


# JAS_SSL_VERIFY=system forces the OS store context.
def test_env_system_returns_context(monkeypatch) -> None:
    monkeypatch.setenv("JAS_SSL_VERIFY", "system")
    assert isinstance(resolve_ssl_verify(), ssl.SSLContext)


# A missing JAS_SSL_VERIFY bundle path falls back to the default behavior.
def test_env_missing_bundle_falls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JAS_SSL_VERIFY", str(tmp_path / "nope.pem"))
    value = resolve_ssl_verify()
    assert value is True or isinstance(value, ssl.SSLContext)


# os_trust_context always returns a system-store SSLContext.
def test_os_trust_context_returns_context() -> None:
    assert isinstance(os_trust_context(), ssl.SSLContext)
