# Site-mode switch: the one place that decides demo vs prod and holds both sites' URLs.
#
# This replaces the old demo-only switch (screening_core.demo_mode / JES_DEMO_MODE).
# There is exactly one switch now: JES_SITE_MODE.
#   JES_SITE_MODE=1 | prod   -> the internal JAS system (SSO, HR's own browser session)
#   unset | empty | 0 | demo -> the public demo platform
#   anything else            -> refused, non-zero exit
#
# The switch is read from the process environment, or from JES_SITE_MODE in the repo .env
# when the environment does not carry it; the real environment always wins.
#
# The refusal matters: with a bare "anything else means demo", a typo in a production
# run would silently screen real applicants against the demo host and still produce a
# normal-looking report. A wrong site must be loud, not plausible.
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

SITE_MODE_ENV = "JES_SITE_MODE"
SITE_PROFILES_NAME = "site_profiles.json"
PACK_SITE_MARKER = "site.json"

MODE_DEMO = "demo"
MODE_PROD = "prod"

PROD_VALUES = frozenset({"1", "prod"})
DEMO_VALUES = frozenset({"", "0", "demo"})

# Built-in profiles. site_profiles.json may override any key per mode, so an operator can
# repoint a site without a code change; the built-ins keep a checkout working with no file.
BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    MODE_DEMO: {
        "mode": MODE_DEMO,
        "base_url": "https://jes-web-demo.vercel.app",
        "list_url": "https://jes-web-demo.vercel.app/",
        "records_url_template": "https://jes-web-demo.vercel.app/records.html?refno={refno}",
        "allow_hosts": ["jes-web-demo.vercel.app"],
        "expects_login": False,
        "human_flow_available": True,
        "tab_group_title": "JES demo screening",
    },
    MODE_PROD: {
        "mode": MODE_PROD,
        "base_url": "https://jobs.polyu.edu.hk",
        # The internal records page doubles as its own list page (confirmed 2026-09-24):
        # with no query it renders the searchable list of jobs, with ?refno= one job.
        "list_url": "https://jobs.polyu.edu.hk/internal/records.php",
        "records_url_template": "https://jobs.polyu.edu.hk/internal/records.php?refno={refno}",
        "allow_hosts": ["jobs.polyu.edu.hk"],
        "expects_login": True,
        "human_flow_available": True,
        "tab_group_title": "JAS screening",
    },
}

DEFAULT_MODE = MODE_DEMO

# Keys site_profiles.json is allowed to override (never "mode": that comes from the switch).
_OVERRIDABLE_KEYS = tuple(key for key in BUILTIN_PROFILES[MODE_DEMO] if key != "mode")


# Raised when a site mode is neither prod nor demo; the CLIs turn this into a non-zero exit.
class SiteModeError(ValueError):
    pass


# Normalise one raw mode value, refusing anything that is not explicitly prod or demo.
def _normalise_mode(value: str | None, *, source: str) -> str:
    text = (value or "").strip().lower()
    if text in PROD_VALUES:
        return MODE_PROD
    if text in DEMO_VALUES:
        return MODE_DEMO
    prod_hint = ", ".join(sorted(PROD_VALUES))
    demo_hint = ", ".join(sorted(v for v in DEMO_VALUES if v))
    raise SiteModeError(
        f"{source} {value!r} is not a recognised site mode. "
        f"Use {prod_hint} for the internal system, or {demo_hint} (or leave it unset) for the demo."
    )


# Resolve the site_profiles.json path (repo root, or cwd parents when repo_root is None).
def _config_path(repo_root: Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root) / SITE_PROFILES_NAME
    candidate = Path.cwd()
    for _ in range(8):
        if (candidate / SITE_PROFILES_NAME).is_file():
            return candidate / SITE_PROFILES_NAME
        if (candidate / ".git").is_dir():
            break
        candidate = candidate.parent
    return Path.cwd() / SITE_PROFILES_NAME


# Read site_profiles.json; missing or unreadable falls back to the built-in profiles.
def _read_config(repo_root: Path | None) -> dict[str, Any]:
    path = _config_path(repo_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# Read one key from the repo .env, so the switch documented in .env.example really works.
#
# The CLIs resolve the mode before any settings object is built, so at that moment .env has
# not been copied into os.environ; without this fallback a documented JES_SITE_MODE line in
# .env would be ignored and the run would quietly use the demo site.
def _read_env_file(key: str, repo_root: Path | None) -> str | None:
    env_path = _config_path(repo_root).parent / ".env"
    if not env_path.is_file():
        return None
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, _, value = text.partition("=")
        if name.strip() != key:
            continue
        value = value.strip()
        # Tolerate the quoted form (JES_SITE_MODE="1"), which is common in hand-edited files.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value
    return None


# Resolve the active mode: explicit argument, then the JES_SITE_MODE environment variable,
# then the same key in .env, then the file's default, then the built-in default.
# Unknown values raise rather than falling through.
def resolve_site_mode(mode: str | None = None, *, repo_root: Path | None = None) -> str:
    if mode:
        return _normalise_mode(mode, source="site mode")
    env = os.environ.get(SITE_MODE_ENV)
    if env is not None:
        return _normalise_mode(env, source=SITE_MODE_ENV)
    from_env_file = _read_env_file(SITE_MODE_ENV, repo_root)
    if from_env_file is not None:
        return _normalise_mode(from_env_file, source=f".env {SITE_MODE_ENV}")
    configured = _read_config(repo_root).get("default")
    if configured:
        return _normalise_mode(str(configured), source=f"{SITE_PROFILES_NAME} default")
    return DEFAULT_MODE


# Build the active site profile: built-in values overlaid with any site_profiles.json override.
def site_profile(mode: str | None = None, *, repo_root: Path | None = None) -> dict[str, Any]:
    resolved = resolve_site_mode(mode, repo_root=repo_root)
    profile = dict(BUILTIN_PROFILES[resolved])
    overrides = (_read_config(repo_root).get("profiles") or {}).get(resolved) or {}
    if isinstance(overrides, dict):
        for key in _OVERRIDABLE_KEYS:
            if overrides.get(key) is not None:
                profile[key] = overrides[key]
    profile["mode"] = resolved
    profile["allow_hosts"] = [str(host) for host in profile.get("allow_hosts") or []]
    return profile


# Build the records URL for a refno from the active profile's template.
def records_url_for_refno(refno: str, mode: str | None = None, *, repo_root: Path | None = None) -> str:
    template = str(site_profile(mode, repo_root=repo_root)["records_url_template"])
    return template.format(refno=refno.strip())


# Resolve the default per-refno job-state directory, scoped by site so a demo baseline can
# never be read as a prod baseline for the same refno (or the reverse).
def default_state_dir(repo_root: Path, mode: str | None = None) -> Path:
    return Path(repo_root) / "data" / "jas_state" / resolve_site_mode(mode, repo_root=repo_root)


# Apply the active site's defaults to a parsed CLI Namespace; returns the profile used.
def apply_site_defaults(args: Any, *, repo_root: Path | None = None) -> dict[str, Any]:
    profile = site_profile(getattr(args, "site", None), repo_root=repo_root)
    if hasattr(args, "site"):
        args.site = profile["mode"]
    # Allowlist the active host, so a run cannot wander off the site it declared.
    if hasattr(args, "allow_host"):
        existing = list(getattr(args, "allow_host", None) or [])
        args.allow_host = existing + [host for host in profile["allow_hosts"] if host not in existing]
    # A site that expects no login (the demo) runs cookie-free. A site that does expect one
    # (the internal system) keeps --no-cookie untouched, so the CLI still asks HR for JAS
    # access when no cookie jar was supplied; the WebBridge flow authenticates from HR's own
    # browser session and never reaches that branch. An explicit --cookie-file is honoured.
    if (
        hasattr(args, "no_cookie")
        and not getattr(args, "cookie_file", None)
        and not profile.get("expects_login")
    ):
        args.no_cookie = True
    return profile


# Record which site owns a report pack; archive its cached artifacts if the site changed.
#
# Returns True when the pack already belonged to this site or was unclaimed (nothing to
# resume, nothing to lose), and False when a pack from the other site was archived — the
# caller must then re-score rather than resume, because _pipeline is keyed by refno alone
# and a demo cache would otherwise be scored into a prod report.
#
# `keep` names files that are not caches and must survive the archive: HR's own answers
# (the conditions file) are authored by a person, not derived from a run.
def claim_pack_site(
    work_dir: str | Path, site: str, *, keep: tuple[str, ...] = (), stamp: str | None = None
) -> bool:
    root = Path(work_dir)
    marker = root / PACK_SITE_MARKER
    previous: str | None = None
    if marker.is_file():
        try:
            previous = str(json.loads(marker.read_text(encoding="utf-8")).get("site") or "").strip() or None
        except (OSError, json.JSONDecodeError):
            previous = None
    matched = previous is None or previous == site
    if previous is not None and previous != site:
        backup = root / f"_backup-{stamp or datetime.now().strftime('%Y%m%d-%H%M%S')}"
        backup.mkdir(parents=True, exist_ok=True)
        for entry in root.iterdir():
            if (
                entry == backup
                or entry.name.startswith("_backup-")
                or entry.name == PACK_SITE_MARKER
                or entry.name in keep
            ):
                continue
            shutil.move(str(entry), str(backup / entry.name))
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"site": site}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return matched


__all__ = [
    "BUILTIN_PROFILES",
    "DEFAULT_MODE",
    "MODE_DEMO",
    "MODE_PROD",
    "PACK_SITE_MARKER",
    "SITE_MODE_ENV",
    "SITE_PROFILES_NAME",
    "SiteModeError",
    "apply_site_defaults",
    "claim_pack_site",
    "default_state_dir",
    "records_url_for_refno",
    "resolve_site_mode",
    "site_profile",
]
