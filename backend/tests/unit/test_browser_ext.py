# Unit tests for the browser-extension diagnosis behind the readiness check.
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COLLECT_SRC = REPO_ROOT / ".codex" / "skills" / "webridge-collect" / "src"
if str(COLLECT_SRC) not in sys.path:
    sys.path.insert(0, str(COLLECT_SRC))

from webridge_collect import browser_ext as be  # noqa: E402


# A `sys` stand-in so the platform branches can be tested without touching the real one.
class _FakeSys:
    def __init__(self, platform: str) -> None:
        self.platform = platform


# Build a browser profile on disk. `settings` is the `extensions.settings` mapping to write;
# `folder` adds the `Extensions/<store id>/<version>/` directory an installed extension has.
def _profile(
    root: Path,
    name: str = "Default",
    *,
    settings: dict | None = None,
    folder: bool = False,
    secure: bool = True,
    write_store: bool = True,
) -> Path:
    profile = root / name
    (profile / "Extensions").mkdir(parents=True, exist_ok=True)
    if folder:
        (profile / "Extensions" / be.EXTENSION_ID / "2.0.5").mkdir(parents=True, exist_ok=True)
    if write_store:
        store = {"extensions": {"settings": settings}} if settings is not None else {}
        (profile / ("Secure Preferences" if secure else "Preferences")).write_text(
            json.dumps(store), encoding="utf-8"
        )
    return profile


def _entry(*, name: str = "Kimi", disable_reasons=None, state=None) -> dict:
    entry: dict = {"manifest": {"name": name, "version": "2.0.5"}}
    if disable_reasons is not None:
        entry["disable_reasons"] = disable_reasons
    if state is not None:
        entry["state"] = state
    return entry


# --- profile roots ---------------------------------------------------------


# Windows: both browsers live under LOCALAPPDATA, Chrome first.
def test_profile_roots_windows(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    local = tmp_path / "Local"
    (local / "Google" / "Chrome" / "User Data").mkdir(parents=True)
    (local / "Microsoft" / "Edge" / "User Data").mkdir(parents=True)
    roots = be.profile_roots(env={"LOCALAPPDATA": str(local)}, home=tmp_path)
    assert [name for name, _ in roots] == ["Chrome", "Edge"]


# macOS: the same two browsers under Application Support.
def test_profile_roots_macos(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("darwin"))
    support = tmp_path / "Library" / "Application Support"
    (support / "Google" / "Chrome").mkdir(parents=True)
    (support / "Microsoft Edge").mkdir(parents=True)
    roots = be.profile_roots(env={}, home=tmp_path)
    assert [name for name, _ in roots] == ["Chrome", "Edge"]


# A browser that is not installed is simply absent: no root, no error.
def test_profile_roots_skips_missing_browsers(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    assert be.profile_roots(env={"LOCALAPPDATA": str(tmp_path / "nope")}, home=tmp_path) == []


# --- reading one profile ---------------------------------------------------


# The extension folder alone is enough to prove it is installed, even with nothing readable.
def test_scan_profile_finds_the_extension_folder(tmp_path) -> None:
    profile = _profile(tmp_path, folder=True)
    assert be.scan_profile(profile) == {"installed": True, "switched_off": None}


# The store id in `extensions.settings` also proves it, which covers a profile whose folder is
# somewhere else.
def test_scan_profile_finds_the_store_id(tmp_path) -> None:
    profile = _profile(tmp_path, settings={be.EXTENSION_ID: _entry()})
    assert be.scan_profile(profile)["installed"] is True


# An unpacked install has a generated id, so the extension's own manifest name is the only signal.
def test_scan_profile_matches_an_unpacked_install_by_name(tmp_path) -> None:
    profile = _profile(tmp_path, settings={"abcdefghijklmnopabcdefghijklmnop": _entry(name="Kimi WebBridge")})
    scan = be.scan_profile(profile)
    assert scan["installed"] is True
    # Its entry carries no state information at all, so nothing is claimed about it.
    assert scan["switched_off"] is None


# A profile whose extension list was readable and does not contain it is the only case that
# justifies telling HR to install anything.
def test_scan_profile_says_not_installed_only_when_it_could_read_the_list(tmp_path) -> None:
    profile = _profile(tmp_path, settings={"otherid": _entry(name="Something Else")})
    assert be.scan_profile(profile)["installed"] is False


# Nothing readable at all is unknown, never "not installed".
def test_scan_profile_is_unknown_when_there_is_nothing_to_read(tmp_path) -> None:
    profile = _profile(tmp_path)
    assert be.scan_profile(profile) == {"installed": None, "switched_off": None}


# An empty `extensions.settings` is the documented trap: `Preferences` carries the key but no
# entries, and reading that as "nothing installed" is exactly the wrong conclusion.
def test_empty_settings_is_unknown_not_absent(tmp_path) -> None:
    profile = tmp_path / "Default"
    profile.mkdir()
    (profile / "Preferences").write_text(json.dumps({"extensions": {"settings": {}}}), encoding="utf-8")
    assert be.extension_settings(profile) is None
    assert be.scan_profile(profile)["installed"] is None


# `Secure Preferences` is the live store, so it wins over a stale `Preferences`.
def test_secure_preferences_wins_over_preferences(tmp_path) -> None:
    profile = tmp_path / "Default"
    profile.mkdir()
    (profile / "Preferences").write_text(
        json.dumps({"extensions": {"settings": {"stale": _entry()}}}), encoding="utf-8"
    )
    (profile / "Secure Preferences").write_text(
        json.dumps({"extensions": {"settings": {be.EXTENSION_ID: _entry()}}}), encoding="utf-8"
    )
    settings = be.extension_settings(profile)
    assert settings is not None and be.EXTENSION_ID in settings


# --- switched off ----------------------------------------------------------


# An empty `disable_reasons` is a positive "enabled", not a missing value: reading it as unknown
# would make the "switch it back on" and "open the browser" answers unreachable on current Chrome.
def test_disable_reasons_empty_means_enabled(tmp_path) -> None:
    profile = _profile(tmp_path, settings={be.EXTENSION_ID: _entry(disable_reasons=[])})
    assert be.scan_profile(profile)["switched_off"] is False


# A non-empty `disable_reasons` is Chrome having switched it off on its own (the 2026-09-07 case).
def test_disable_reasons_non_empty_means_switched_off(tmp_path) -> None:
    profile = _profile(tmp_path, settings={be.EXTENSION_ID: _entry(disable_reasons=[2])})
    assert be.scan_profile(profile)["switched_off"] is True


# The older 1/0 flag is used only when `disable_reasons` is absent.
def test_state_flag_is_the_fallback(tmp_path) -> None:
    off = _profile(tmp_path / "a", settings={be.EXTENSION_ID: _entry(state=0)})
    on = _profile(tmp_path / "b", settings={be.EXTENSION_ID: _entry(state=1)})
    assert be.scan_profile(off)["switched_off"] is True
    assert be.scan_profile(on)["switched_off"] is False


# --- the aggregate ---------------------------------------------------------


# One profile holding the extension is enough, and its profile name is reported.
def test_diagnose_finds_it_in_a_second_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    root = tmp_path / "Local" / "Google" / "Chrome" / "User Data"
    _profile(root, "Default", settings={"otherid": _entry(name="Other")})
    _profile(root, "Profile 1", settings={be.EXTENSION_ID: _entry(disable_reasons=[])})
    result = be.diagnose(env={"LOCALAPPDATA": str(tmp_path / "Local")}, home=tmp_path)
    assert result["installed"] is True
    assert result["browser"] == "Chrome"
    assert result["profile"] == "Profile 1"


# One working copy is enough for the extension to attach, so a second profile that has it switched
# off must not turn the whole answer into "switched off".
def test_diagnose_prefers_the_working_copy(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    root = tmp_path / "Local" / "Google" / "Chrome" / "User Data"
    _profile(root, "Default", settings={be.EXTENSION_ID: _entry(disable_reasons=[2])})
    _profile(root, "Profile 1", settings={be.EXTENSION_ID: _entry(disable_reasons=[])})
    assert be.diagnose(env={"LOCALAPPDATA": str(tmp_path / "Local")}, home=tmp_path)["switched_off"] is False


# Readable profiles that do not hold it is the only route to "not installed".
def test_diagnose_not_installed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    root = tmp_path / "Local" / "Google" / "Chrome" / "User Data"
    _profile(root, "Default", settings={"otherid": _entry(name="Other")})
    assert be.diagnose(env={"LOCALAPPDATA": str(tmp_path / "Local")}, home=tmp_path)["installed"] is False


# No browser on the computer at all means nothing is known - and saying "not installed" here would
# be a guess about a browser that is not even there.
def test_diagnose_without_any_browser(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    result = be.diagnose(env={"LOCALAPPDATA": str(tmp_path / "Local")}, home=tmp_path)
    assert result == {"installed": None, "switched_off": None, "browser": None, "profile": None}


# --- the browser process ---------------------------------------------------


# The exact image name is what counts: a loose match also hits `msedgewebview2.exe`, which is the
# desktop app's embedded webview and not a browser HR can use.
def test_browser_running_matches_exact_image_names(monkeypatch) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    seen: list[list[str]] = []

    def fake_run(cmd):
        seen.append(cmd)
        if "chrome.exe" in cmd[2]:
            return "INFO: No tasks are running which match the specified criteria."
        if "msedge.exe" in cmd[2]:
            return '"msedge.exe","1234","Console","1","100,000 K"'
        return ""

    monkeypatch.setattr(be, "_run", fake_run)
    assert be.browser_running() is True
    assert [cmd[2] for cmd in seen] == ["IMAGENAME eq chrome.exe", "IMAGENAME eq msedge.exe"]


# `msedgewebview2.exe` in the listing must not be read as a browser being open.
def test_browser_running_ignores_the_embedded_webview(monkeypatch) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    monkeypatch.setattr(
        be, "_run", lambda cmd: '"msedgewebview2.exe","1234","Console","1","100,000 K"'
    )
    assert be.browser_running() is False


# A command that cannot be run at all is unknown, not "no browser open".
def test_browser_running_is_unknown_when_the_listing_fails(monkeypatch) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("win32"))
    monkeypatch.setattr(be, "_run", lambda cmd: None)
    assert be.browser_running() is None


# An unknown platform is unknown, not a false alarm.
def test_browser_running_on_an_unknown_platform(monkeypatch) -> None:
    monkeypatch.setattr(be, "sys", _FakeSys("freebsd"))
    assert be.browser_running() is None
