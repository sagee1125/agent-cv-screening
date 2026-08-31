# Resolves TLS verification for skill HTTP calls (JAS_SSL_VERIFY override + system store).
from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Any


# Loads repo .env so JAS_SSL_VERIFY / SSL_CERT_FILE work in any shell.
def _load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


# Injects the OS certificate store when truststore is installed (idempotent).
def _use_system_trust() -> None:
    try:
        import truststore  # type: ignore[import-not-found]

        truststore.inject_into_ssl()
    except Exception:
        pass


# Returns the httpx verify value: an SSLContext, a CA bundle path, or True.
def resolve_ssl_verify() -> Any:
    _load_dotenv_if_present()
    raw = os.environ.get("JAS_SSL_VERIFY", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw == "system":
        _use_system_trust()
        return ssl.create_default_context()
    if raw and Path(raw).is_file():
        return ssl.create_default_context(cafile=raw)
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context()
    # Default: with truststore installed, httpx's own CA verification already
    # resolves through the OS store; otherwise certifi behaves as before.
    _use_system_trust()
    return True


# Returns an SSLContext verified against the OS/system certificate store.
def os_trust_context() -> ssl.SSLContext:
    _use_system_trust()
    return ssl.create_default_context()


__all__ = ["os_trust_context", "resolve_ssl_verify"]
