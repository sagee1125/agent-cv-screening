# Demo-mode switch: route live JAS fetching to the public demo host without cookies.
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEMO_MODE_ENV = "JES_DEMO_MODE"
DEMO_CONFIG_NAME = "demo_mode.json"
DEFAULT_DEMO_BASE_URL = "https://jes-web-demo.vercel.app"
DEFAULT_DEMO_ALLOW_HOSTS = ("jes-web-demo.vercel.app",)

_TRUE_VALUES = {"1", "true", "on", "yes"}
_FALSE_VALUES = {"0", "false", "off", "no"}


# Build the default demo-mode settings.
def _default_settings() -> dict[str, Any]:
    return {"base_url": DEFAULT_DEMO_BASE_URL, "allow_hosts": list(DEFAULT_DEMO_ALLOW_HOSTS)}


# Resolve the demo_mode.json path (repo root, or cwd parents when repo_root is None).
def _config_path(repo_root: Path | None) -> Path | None:
    if repo_root is not None:
        return repo_root / DEMO_CONFIG_NAME
    candidate = Path.cwd()
    for _ in range(8):
        if (candidate / DEMO_CONFIG_NAME).is_file():
            return candidate / DEMO_CONFIG_NAME
        if (candidate / ".git").is_dir():
            break
        candidate = candidate.parent
    return Path.cwd() / DEMO_CONFIG_NAME


# Return demo-mode settings when enabled (env var or repo-root demo_mode.json), else None.
def demo_mode_settings(*, repo_root: Path | None = None) -> dict[str, Any] | None:
    env = os.environ.get(DEMO_MODE_ENV)
    if env is not None:
        value = env.strip().lower()
        if value in _TRUE_VALUES:
            return _default_settings()
        if value in _FALSE_VALUES:
            return None
    config = _config_path(repo_root)
    if config and config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("enabled"):
            return {
                "base_url": str(data.get("base_url") or DEFAULT_DEMO_BASE_URL),
                "allow_hosts": [str(host) for host in (data.get("allow_hosts") or DEFAULT_DEMO_ALLOW_HOSTS)],
            }
    return None


# Apply demo-mode defaults (base-url, allow-hosts, no-cookie) to a parsed CLI Namespace; True when active.
def apply_demo_defaults(args: Any, *, repo_root: Path | None = None) -> bool:
    settings = demo_mode_settings(repo_root=repo_root)
    if not settings:
        return False
    # A bare refno (no explicit URL) is routed to the demo host; explicit URLs are respected.
    if hasattr(args, "base_url") and not getattr(args, "base_url", None) and not getattr(args, "records_url", None):
        args.base_url = settings["base_url"]
    if hasattr(args, "allow_host"):
        existing = list(getattr(args, "allow_host", None) or [])
        args.allow_host = existing + [host for host in settings["allow_hosts"] if host not in existing]
    if hasattr(args, "no_cookie") and not getattr(args, "cookie_file", None):
        args.no_cookie = True
    return True


__all__ = [
    "DEMO_CONFIG_NAME",
    "DEMO_MODE_ENV",
    "DEFAULT_DEMO_ALLOW_HOSTS",
    "DEFAULT_DEMO_BASE_URL",
    "apply_demo_defaults",
    "demo_mode_settings",
]