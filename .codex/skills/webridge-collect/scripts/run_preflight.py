"""CLI: readiness check before a screening run. No CV download, no pipeline, no report.

Answers three questions in one cheap pass, so the conversation can hand a failure back to HR
with the right instruction instead of starting a run that cannot finish:

    daemon     is the Kimi WebBridge daemon answering on 127.0.0.1:10086?   (both sites)
    extension  is a browser extension attached to it?                       (both sites)
    login      is the browser signed in to the internal job pages?          (prod only)

The check deliberately *starts* the daemon the way a screening run would, because a check that
reports "not running" for something the run would have started itself would block HR on a
non-problem. Its verdict is meant to predict the run, not to be stricter than it.

When no extension is attached, the check does not stop at "not connected": the daemon cannot say
*why*, and the three reasons need three different instructions from HR. `browser_ext` reads the
browser's own profile to tell "never installed" from "installed but switched off" from "no
browser open", and says nothing it cannot support.

The login check is a positive test: the page must land inside `/internal/` **and** render the
records table. The sign-in hostname is never used as a signal, because an unknown identity
provider could be reached from anywhere and a negative test on an unknown host would fail open.

The `--driver http` path has no client-side prerequisites at all (it fetches the public demo
pages directly, with no browser), so it reports an empty check list.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)

from screening_core.site_mode import SiteModeError, apply_site_defaults
from webridge_collect.browser_ext import PRODUCT_URL, STORE_URL, browser_running, diagnose
from webridge_collect.client import (
    DAEMON_START_WAIT,
    EXTENSION_CONNECT_WAIT,
    WebBridgeClient,
    close_session_tabs,
    extension_version,
    start_webbridge_daemon,
    webbridge_status,
)
from webridge_collect.login import ASK_LOGIN, probe_sign_in

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2

CHECK_DAEMON = "daemon"
CHECK_EXTENSION = "extension"
CHECK_LOGIN = "login"

REASON_DAEMON = "daemon_unreachable"
# The fallback when the browser's profile could not be read: an extension is not attached and we
# could not find out why, so HR gets the sentence that lists every cause.
REASON_EXTENSION = "extension_disabled"
REASON_EXTENSION_MISSING = "extension_not_installed"
REASON_EXTENSION_OFF = "extension_off"
REASON_BROWSER_CLOSED = "browser_not_running"
REASON_LOGIN = "not_signed_in"

# The host-visible token each failure asks for. The login failure reuses `jas_session` so it
# rides the existing auth projection rather than inventing a second way to say "no session".
TOKEN_BROWSER = "browser"
TOKEN_EXTENSION = "extension"
TOKEN_SESSION = "jas_session"

ASK_DAEMON = (
    "The screening browser helper (Kimi WebBridge) is not running and could not be started. "
    "Please start it, then ask me to screen again.",
    "篩選用的瀏覽器助手（Kimi WebBridge）沒有運行，亦無法自動啟動。請先啟動它，然後再叫我篩選。",
)
# The four extension sentences. Which one HR gets is decided by `_extension_reason`, so she is
# never told to install something she already has, nor to re-enable something that is already on.
#
# The two links travel in the sentence itself: a computer that has never had the extension has no
# other way to be told where to get it, and "contact us" costs a round trip. The store listing is
# the one-click path; the vendor's own page is the fallback when the Web Store is unreachable.
ASK_EXTENSION = (
    "Kimi WebBridge is running, but no browser extension is connected. Please open a normal "
    "Chrome (or Edge) window — not Incognito — with the Kimi extension enabled, then ask me again.",
    "Kimi WebBridge 已在運行，但沒有瀏覽器擴充連上。請用一般 Chrome（或 Edge）視窗（不要用無痕）"
    "並啟用 Kimi 瀏覽器擴充，然後再叫我。",
)
ASK_EXTENSION_MISSING = (
    "The Kimi browser extension is not installed on this computer. Install it from the Chrome Web "
    f"Store ({STORE_URL}), or from Kimi's own page ({PRODUCT_URL}), then ask me again. Use a "
    "normal window, not Incognito.",
    f"這台電腦尚未安裝 Kimi 瀏覽器擴充功能。請從 Chrome 線上應用程式商店安裝（{STORE_URL}），"
    f"或到 Kimi 官方頁面下載（{PRODUCT_URL}），然後再叫我。請用一般視窗，不要用無痕。",
)
ASK_EXTENSION_OFF = (
    "The Kimi browser extension is installed but switched off. Please open chrome://extensions "
    "in a normal Chrome window (not Incognito) and enable Kimi, then ask me again.",
    "Kimi 瀏覽器擴充功能已安裝但被停用。請用一般 Chrome 視窗（不要用無痕）開啟 "
    "chrome://extensions 啟用 Kimi，然後再叫我。",
)
ASK_BROWSER_CLOSED = (
    "The Kimi browser extension is installed and enabled, but no browser is open. Please open "
    "a normal Chrome window (not Incognito), then ask me again.",
    "Kimi 瀏覽器擴充功能已安裝並已啟用，但沒有開啟瀏覽器。請開啟一般 Chrome 視窗（不要用無痕），"
    "然後再叫我。",
)

# The sentence that goes with each reason. The fallback covers "could not tell".
_EXTENSION_ASK = {
    REASON_EXTENSION_MISSING: ASK_EXTENSION_MISSING,
    REASON_EXTENSION_OFF: ASK_EXTENSION_OFF,
    REASON_BROWSER_CLOSED: ASK_BROWSER_CLOSED,
    REASON_EXTENSION: ASK_EXTENSION,
}

# Build one check record; `reason` is set only when the check failed.
#
# The identifier key is `check`, never `name`: `name` is the candidate-name field in the host
# denylist, so a check record that used it would be rejected as a PII leak.
def _check(name: str, ok: bool, *, reason: str | None = None, version: str | None = None) -> dict:
    return {"check": name, "ok": ok, "reason": None if ok else reason, "version": version}


# Decide whether the browser is signed in: inside /internal/ AND the records table rendered.
#
# The probe itself lives in `webridge_collect.login` because the screening run uses the very same
# test before it reads a page. A check that could disagree with the run would be worse than none.
def _check_login(client: WebBridgeClient, profile: dict) -> dict:
    list_url = str(profile.get("list_url") or "")
    client.navigate(list_url, new_tab=True, group_title=str(profile.get("tab_group_title") or ""))
    return _check(CHECK_LOGIN, probe_sign_in(client)["signed_in"], reason=REASON_LOGIN)


# What this computer can say about the extension, or nothing at all.
#
# Never raises: a readiness check must not turn into an error because a browser profile was odd.
# An unreadable profile returns unknowns, which fall through to the generic sentence.
def _diagnose_extension() -> dict:
    try:
        return diagnose()
    except Exception:
        return {"installed": None, "switched_off": None, "browser": None, "profile": None}


# Pick the one thing HR has to fix. Order matters: "not installed" outranks "switched off",
# because an extension that is not there cannot also be switched off, and sending her to
# re-enable something her browser does not list wastes the round trip the check exists to save.
def _extension_reason(diagnosis: dict, browser_up: bool | None) -> str:
    if diagnosis.get("installed") is False:
        return REASON_EXTENSION_MISSING
    if diagnosis.get("installed") is True and diagnosis.get("switched_off") is True:
        return REASON_EXTENSION_OFF
    if (
        diagnosis.get("installed") is True
        and diagnosis.get("switched_off") is False
        and browser_up is False
    ):
        return REASON_BROWSER_CLOSED
    return REASON_EXTENSION


# Poll /status until the daemon answers (starting it first) or the wait runs out.
def _await_daemon(daemon_url: str, *, wait_seconds: float) -> dict | None:
    status = webbridge_status(daemon_url)
    if status is not None:
        return status
    if not start_webbridge_daemon():
        return None
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status = webbridge_status(daemon_url)
        if status is not None:
            return status
        time.sleep(1.0)
    return None


# Poll /status until an extension is attached, or the wait runs out; returns the last status.
def _await_extension(daemon_url: str, status: dict, *, wait_seconds: float) -> dict:
    deadline = time.monotonic() + wait_seconds
    while not status.get("extension_connected"):
        if time.monotonic() >= deadline:
            break
        time.sleep(1.0)
        status = webbridge_status(daemon_url) or status
    return status


# Print a PII-free envelope; errors go to stderr.
def _emit(payload: dict, *, to_stderr: bool = False) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    (sys.stderr if to_stderr else sys.stdout).write(text + "\n")
    return EXIT_ERROR if to_stderr else EXIT_OK


# Emit a failed readiness result and return exit code 2.
def _fail(checks: list[dict], token: str, questions: tuple[str, str], site: str) -> int:
    payload = {
        "status": "need_input",
        "tool": "preflight",
        "site": site,
        "checks": checks,
        "missing": [token],
        "questions": list(questions),
        "ask": {"missing": [token], "questions": list(questions)},
    }
    print(json.dumps(payload, ensure_ascii=False))
    return EXIT_NEED_INPUT


# Build the argparse CLI for the readiness check.
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that the screening browser is ready before a run (daemon, extension, sign-in)."
    )
    parser.add_argument(
        "--site",
        choices=("demo", "prod"),
        default=None,
        help="Which site to check: prod = the internal JAS system, demo = the public demo. "
        "Defaults to JES_SITE_MODE (1/prod = prod, unset/0/demo = demo).",
    )
    parser.add_argument(
        "--driver",
        choices=("webbridge", "http"),
        default="webbridge",
        help="The driver the run will use. http needs no browser, so it reports no checks.",
    )
    parser.add_argument("--daemon-url", default="http://127.0.0.1:10086", help="WebBridge daemon URL.")
    parser.add_argument("--session", default="jes-preflight", help="WebBridge session (tab group) name.")
    parser.add_argument(
        "--keep-browser",
        action="store_true",
        help="Keep the WebBridge tab the check opened (default: close it once the check is done).",
    )
    args = parser.parse_args()

    try:
        profile = apply_site_defaults(args, repo_root=_bootstrap.REPO_ROOT)
    except SiteModeError as exc:
        # Same refusal as a screening run: a typo must not silently check the wrong site.
        return _emit({"status": "error", "error_code": "bad_site_mode", "error_message": str(exc)}, to_stderr=True)
    site = str(profile["mode"])

    # The http driver drives no browser, so there is nothing client-side to verify.
    if args.driver == "http":
        return _emit({"status": "success", "tool": "preflight", "site": site, "checks": []})

    checks: list[dict] = []
    status = _await_daemon(args.daemon_url, wait_seconds=DAEMON_START_WAIT)
    if status is None:
        checks.append(_check(CHECK_DAEMON, False, reason=REASON_DAEMON))
        return _fail(checks, TOKEN_BROWSER, ASK_DAEMON, site)
    checks.append(_check(CHECK_DAEMON, True))

    status = _await_extension(args.daemon_url, status, wait_seconds=EXTENSION_CONNECT_WAIT)
    connected = bool(status.get("extension_connected"))
    checks.append(
        _check(
            CHECK_EXTENSION,
            connected,
            reason=REASON_EXTENSION,
            version=extension_version(status) if connected else None,
        )
    )
    if not connected:
        diagnosis = _diagnose_extension()
        # Only worth a process listing when the extension itself is accounted for: if it is not
        # installed, or was switched off, whether a browser is open is not the answer.
        browser_up = browser_running() if diagnosis.get("installed") else None
        reason = _extension_reason(diagnosis, browser_up)
        checks[-1]["reason"] = reason
        return _fail(checks, TOKEN_EXTENSION, _EXTENSION_ASK[reason], site)

    # Only the internal site expects a login; the demo pages are public.
    client = WebBridgeClient(daemon_url=args.daemon_url, session=args.session)
    try:
        if profile.get("expects_login"):
            login = _check_login(client, profile)
            checks.append(login)
            if not login["ok"]:
                return _fail(checks, TOKEN_SESSION, ASK_LOGIN, site)
    except Exception as exc:
        return _emit({"status": "error", "error_message": str(exc)}, to_stderr=True)
    finally:
        # The check opened a page only to look at it, so nothing should be left on screen —
        # the same rule a not-found run follows. --keep-browser keeps it for inspection.
        if not args.keep_browser:
            close_session_tabs(client)

    return _emit({"status": "success", "tool": "preflight", "site": site, "checks": checks})


if __name__ == "__main__":
    raise SystemExit(main())
