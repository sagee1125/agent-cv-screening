"""Whether the Kimi browser extension is installed on this computer, and whether it is switched on.

The WebBridge daemon answers exactly one question: is an extension attached to it *right now*?
When the answer is no, HR has three very different things to fix, and the daemon cannot tell them
apart:

    the extension was never installed             -> she has to install it
    it is installed but the browser switched it off -> she has to re-enable it
    it is installed and on, but no browser is open  -> she has to open the browser

Those facts are not in the daemon; they are in the browser's own profile on disk, so this module
reads them. Read-only, and never a guess: anything it cannot read comes back as `None`, meaning
unknown. A confident but wrong "not installed" would send HR to install something she already
has, which is worse than the generic message it replaces.

Where the browser really keeps this (learned the hard way, 2026-09-07): `Default/Preferences`
→ `extensions.settings` can be empty. The live store is **`Default/Secure Preferences`**, and a
profile that has an extension installed keeps its files under `Extensions/<extension id>/`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# The Kimi browser extension (renamed from Kimi WebBridge) in the Chrome Web Store. The id is the
# store id, which is also the folder name the browser uses under `Extensions/`.
EXTENSION_ID = "fldmhceldgbpfpkbgopacenieobmligc"
STORE_URL = f"https://chromewebstore.google.com/detail/kimi/{EXTENSION_ID}"

# Fallback for an extension the browser installed by hand (unpacked): it has no `Extensions/<id>`
# folder, so it is only recognisable by the name in its own manifest.
NAME_HINTS = ("kimi", "webbridge")

# `Secure Preferences` is a few hundred KB in a normal profile; a file far past this is not
# something to parse inside a readiness check.
MAX_SETTINGS_BYTES = 32 * 1024 * 1024

BROWSERS = ("Chrome", "Edge")


# Every profile root this platform could have, Chrome first. Roots that do not exist are dropped.
def profile_roots(*, env: dict | None = None, home: Path | None = None) -> list[tuple[str, Path]]:
    env = os.environ if env is None else env
    home = Path(home) if home is not None else Path.home()
    if sys.platform == "win32":
        base = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else home / "AppData" / "Local"
        candidates = [
            ("Chrome", base / "Google" / "Chrome" / "User Data"),
            ("Edge", base / "Microsoft" / "Edge" / "User Data"),
        ]
    elif sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        candidates = [
            ("Chrome", support / "Google" / "Chrome"),
            ("Edge", support / "Microsoft Edge"),
        ]
    else:
        config = home / ".config"
        candidates = [
            ("Chrome", config / "google-chrome"),
            ("Edge", config / "microsoft-edge"),
        ]
    return [(name, path) for name, path in candidates if path.is_dir()]


# The profile directories inside one browser root: `Default`, `Profile 1`, ... A directory counts
# as a profile when it holds either of the two files that carry the extension list.
def profile_dirs(root: Path) -> list[Path]:
    found: list[Path] = []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return []
    for child in children:
        if not child.is_dir():
            continue
        if (child / "Preferences").is_file() or (child / "Secure Preferences").is_file():
            found.append(child)
    return found


# Parse a JSON file, or None when it is missing, unreadable or not an object.
def _read_json(path: Path) -> dict | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_SETTINGS_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# `extensions.settings` for one profile, from the live store first and `Preferences` second.
#
# An empty mapping counts as "not found": that is the documented trap where `Preferences` carries
# the key but no entries, and reading it as "no extension installed" would be exactly the wrong
# conclusion.
def extension_settings(profile_dir: Path) -> dict | None:
    for name in ("Secure Preferences", "Preferences"):
        data = _read_json(profile_dir / name)
        if not isinstance(data, dict):
            continue
        extensions = data.get("extensions")
        if not isinstance(extensions, dict):
            continue
        settings = extensions.get("settings")
        if isinstance(settings, dict) and settings:
            return settings
    return None


# The id this profile holds the Kimi extension under: the store id, else any entry whose own
# manifest name matches. Unpacked installs get a generated id, which is why the name matters.
def _extension_id(settings: dict | None) -> str | None:
    if not isinstance(settings, dict):
        return None
    if EXTENSION_ID in settings:
        return EXTENSION_ID
    for extension_id, entry in settings.items():
        manifest = entry.get("manifest") if isinstance(entry, dict) else None
        name = str((manifest or {}).get("name") or "").lower()
        if any(hint in name for hint in NAME_HINTS):
            return str(extension_id)
    return None


# True when the browser itself has switched this extension off.
#
# `disable_reasons` is the field Chrome writes when it disables an extension on its own (the
# 2026-09-07 case: a permission increase HR never approved). An **empty list means enabled** - it
# is a positive signal, not a missing one, and reading it as unknown would leave the "open the
# browser" and "switch it back on" answers permanently unreachable on a current Chrome. `state`
# is the older 1/0 flag, used only when `disable_reasons` is absent.
def _switched_off(entry: Any) -> bool | None:
    if not isinstance(entry, dict):
        return None
    reasons = entry.get("disable_reasons")
    if isinstance(reasons, list):
        return bool(reasons)
    state = entry.get("state")
    if isinstance(state, int) and not isinstance(state, bool):
        return state == 0
    return None


# What one profile says about the extension. Every field is None when it could not be read.
def scan_profile(profile_dir: Path) -> dict:
    settings = extension_settings(profile_dir)
    extension_id = _extension_id(settings)
    folder = profile_dir / "Extensions" / EXTENSION_ID

    if extension_id is not None or folder.is_dir():
        installed: bool | None = True
    elif settings is not None:
        # The profile's extension list was readable and the extension is not in it.
        installed = False
    else:
        installed = None

    switched_off = None
    if installed and settings is not None:
        entry = settings.get(extension_id) if extension_id else None
        switched_off = _switched_off(entry)
    return {"installed": installed, "switched_off": switched_off}


# The best answer this computer can give, across every profile of every browser.
#
# `installed` is True if any profile holds it, False only if a readable profile does not and no
# other does. `switched_off` is True only if every instance found is off - one working copy is
# enough for the extension to attach.
def diagnose(*, env: dict | None = None, home: Path | None = None) -> dict:
    installed_votes: list[bool] = []
    off_votes: list[bool] = []
    browser: str | None = None
    profile: str | None = None
    for browser_name, root in profile_roots(env=env, home=home):
        for profile_dir in profile_dirs(root):
            scan = scan_profile(profile_dir)
            if scan["installed"] is True:
                installed_votes.append(True)
                if browser is None:
                    browser, profile = browser_name, profile_dir.name
                if scan["switched_off"] is not None:
                    off_votes.append(scan["switched_off"])
            elif scan["installed"] is False:
                installed_votes.append(False)

    if any(installed_votes):
        installed: bool | None = True
        if any(vote is False for vote in off_votes):
            switched_off: bool | None = False
        elif off_votes:
            switched_off = True
        else:
            switched_off = None
    elif installed_votes:
        installed, switched_off = False, None
    else:
        installed, switched_off = None, None
    return {
        "installed": installed,
        "switched_off": switched_off,
        "browser": browser,
        "profile": profile,
    }


# Run a small read-only command and return its output, or None when it cannot be run at all.
def _run(cmd: list[str]) -> str | None:
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout or ""


# Is a browser this extension can attach to actually open? None when it cannot be determined.
#
# The image names are matched exactly: a loose `msedge` match also hits `msedgewebview2.exe`,
# which is the desktop app's embedded webview and not a browser HR can use.
def browser_running() -> bool | None:
    if sys.platform == "win32":
        images = ("chrome.exe", "msedge.exe")
        for image in images:
            output = _run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"])
            if output is None:
                return None
            if image.lower() in output.lower():
                return True
        return False
    if sys.platform == "darwin":
        for name in ("Google Chrome", "Microsoft Edge"):
            output = _run(["pgrep", "-f", name])
            if output is None:
                return None
            if output.strip():
                return True
        return False
    return None


__all__ = [
    "BROWSERS",
    "EXTENSION_ID",
    "NAME_HINTS",
    "STORE_URL",
    "browser_running",
    "diagnose",
    "extension_settings",
    "profile_dirs",
    "profile_roots",
    "scan_profile",
]
