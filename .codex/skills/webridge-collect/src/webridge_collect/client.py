# Thin HTTP client for the Kimi WebBridge local daemon (http://127.0.0.1:10086).
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_DAEMON_URL = "http://127.0.0.1:10086"
DEFAULT_SESSION = "jes-demo-screen"
CV_CHUNK_BYTES = 512 * 1024
DAEMON_START_WAIT = 25.0
# The browser extension reconnects several seconds after the daemon starts, so a run that
# begins as soon as the daemon answers HTTP would fail with "no extension connected".
EXTENSION_CONNECT_WAIT = 30.0
# Cleanup uses a short HTTP timeout so a hung daemon never delays a finished run.
CLEANUP_TIMEOUT_SECONDS = 10.0
CV_DOWNLOAD_TIMEOUT = 60.0
# Same Accept a browser sends when a click opens the CV link. file.php returns
# the file for that request and a not-found page for an in-page fetch.
CV_DOWNLOAD_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)


# True when the WebBridge daemon answers a status probe on the given URL.
def _daemon_reachable(daemon_url: str, *, timeout: float = 2.0) -> bool:
    try:
        response = httpx.post(f"{daemon_url.rstrip('/')}/status", timeout=timeout)
        return response.status_code < 400
    except httpx.HTTPError:
        return False


# True when a browser extension is attached to the daemon and can run commands.
def _extension_connected(daemon_url: str, *, timeout: float = 2.0) -> bool:
    url = f"{daemon_url.rstrip('/')}/status"
    for method in (httpx.get, httpx.post):
        try:
            response = method(url, timeout=timeout)
            if response.status_code >= 400:
                continue
            return bool(response.json().get("extension_connected"))
        except (httpx.HTTPError, json.JSONDecodeError, AttributeError):
            continue
    return False


# Read the daemon's /status body: reachability plus the extension state and version.
#
# Unlike _extension_connected this hands back the whole status object, so the readiness check
# can report "the daemon is down" and "no extension is attached" as two separate problems with
# two separate instructions. Returns None when the daemon does not answer at all.
def webbridge_status(daemon_url: str = DEFAULT_DAEMON_URL, *, timeout: float = 2.0) -> dict[str, Any] | None:
    url = f"{daemon_url.rstrip('/')}/status"
    for method in (httpx.get, httpx.post):
        try:
            response = method(url, timeout=timeout)
        except httpx.HTTPError:
            continue
        if response.status_code >= 400:
            continue
        try:
            data = response.json()
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, dict) else {}
    return None


# The browser extension's version as reported by /status, or None when it is not stated.
#
# Only meaningful while an extension is actually attached: the status object carries a single
# "version" field and there is no way to tell a daemon version from an extension one, so an
# unconnected daemon reports no version rather than a misleading one.
def extension_version(status: dict[str, Any] | None) -> str | None:
    if not isinstance(status, dict) or not status.get("extension_connected"):
        return None
    for key in ("extension_version", "extensionVersion", "version"):
        value = status.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    return None


# Best-effort start of the local Kimi WebBridge daemon process (non-blocking).
def _start_daemon_process() -> bool:
    candidates = [
        os.environ.get("KIMI_WEBRIDGE_BIN", ""),
        str(Path.home() / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"),
        str(Path.home() / ".kimi-webbridge" / "bin" / "kimi-webbridge"),
    ]
    for binary in candidates:
        if not binary:
            continue
        if not Path(binary).is_file():
            continue
        try:
            subprocess.Popen([binary, "start"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False


# Best-effort start of the local daemon, for callers running their own wait loop.
#
# ensure_webbridge_daemon owns the start-and-wait policy for a screening run and answers a single
# yes/no. The readiness check needs the same start but a two-step wait, so that it can say which
# step failed; this exposes the start half without changing the run's behaviour.
def start_webbridge_daemon() -> bool:
    return _start_daemon_process()


# Ensure the WebBridge daemon is running and a browser extension is attached to it.
def ensure_webbridge_daemon(
    daemon_url: str = DEFAULT_DAEMON_URL,
    *,
    wait_seconds: float = DAEMON_START_WAIT,
    extension_wait: float = EXTENSION_CONNECT_WAIT,
) -> bool:
    if not _daemon_reachable(daemon_url):
        if not _start_daemon_process():
            return False
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if _daemon_reachable(daemon_url):
                break
            time.sleep(1.0)
        else:
            return False
    # The daemon answers HTTP before the extension reconnects, so keep waiting for the
    # extension instead of letting the first browser command fail.
    deadline = time.monotonic() + extension_wait
    while time.monotonic() < deadline:
        if _extension_connected(daemon_url):
            return True
        time.sleep(1.0)
    return False


# Raised when the WebBridge daemon rejects a command or is unreachable.
class WebBridgeError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "webbridge") -> None:
        """Record a machine-readable reason alongside the human message."""
        self.reason = reason
        super().__init__(message)


# Cookie header from the browser's cookie jar. Values stay in the request only.
def _cookie_header(cookies: list[Any]) -> str:
    parts: list[str] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "")
        if not name:
            continue
        parts.append(f"{name}={cookie.get('value') or ''}")
    return "; ".join(parts)


# GET a CV with the browser's cookies. Does not open the URL in a tab.
def _http_download(url: str, headers: dict[str, str]) -> bytes:
    from screening_core.ssl_verify import resolve_ssl_verify

    with httpx.Client(timeout=CV_DOWNLOAD_TIMEOUT, follow_redirects=False, verify=resolve_ssl_verify()) as client:
        response = client.get(url, headers=headers)
    if response.status_code >= 400:
        raise WebBridgeError(
            f"CV download failed for {url}: HTTP {response.status_code}",
            reason="download-failed",
        )
    body = response.content or b""
    if not body or body.lstrip().startswith(b"<"):
        raise WebBridgeError(
            f"CV download for {url} returned a page instead of a file",
            reason="download-failed",
        )
    return body


# Client for the WebBridge daemon: one POST /command per browser action.
class WebBridgeClient:
    # Bind one client to a daemon URL and a session (tab group) name.
    def __init__(self, *, daemon_url: str = DEFAULT_DAEMON_URL, session: str = DEFAULT_SESSION, timeout: float = 120.0) -> None:
        self.daemon_url = daemon_url.rstrip("/")
        self.session = session
        self.timeout = timeout

    # POST one command and return the parsed JSON body; timeout overrides the client default.
    def command(
        self,
        action: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": action, "session": self.session}
        if args:
            payload["args"] = args
        try:
            response = httpx.post(
                f"{self.daemon_url}/command",
                json=payload,
                timeout=self.timeout if timeout is None else timeout,
            )
        except httpx.HTTPError as exc:
            raise WebBridgeError(
                f"Kimi WebBridge daemon unreachable at {self.daemon_url} ({exc.__class__.__name__}). "
                'Start it with: & "$env:USERPROFILE\\.kimi-webbridge\\bin\\kimi-webbridge.exe" start',
                reason="daemon-unreachable",
            ) from exc
        if response.status_code >= 400:
            # A reachable daemon with no browser attached answers 502 "no extension
            # connected"; that needs a different instruction from an unreachable daemon.
            if response.status_code == 502 and "no extension connected" in response.text:
                raise WebBridgeError(
                    "Kimi WebBridge daemon is running but no browser extension is connected. "
                    "Open Chrome/Edge with the Kimi WebBridge extension enabled, then retry.",
                    reason="extension-disconnected",
                )
            raise WebBridgeError(
                f"WebBridge daemon returned HTTP {response.status_code}: {response.text[:200]}",
                reason="daemon-error",
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise WebBridgeError(
                f"WebBridge daemon returned non-JSON: {response.text[:200]}",
                reason="daemon-error",
            ) from exc
        # The daemon wraps responses as {"ok": true, "data": {...}} and errors as
        # {"ok": false, "error": {code, message}}; unwrap them for the callers.
        if isinstance(data, dict):
            if data.get("ok") is False:
                error = data.get("error") or {}
                raise WebBridgeError(
                    str(error.get("message") or data),
                    reason=str(error.get("code") or "command-failed"),
                )
            if data.get("success") is False:
                raise WebBridgeError(str(data.get("error") or data.get("message") or data), reason="command-failed")
            if isinstance(data.get("data"), dict):
                return data["data"]
        return data

    # Open a URL in a tab and label the tab group for this task.
    def navigate(self, url: str, *, new_tab: bool = True, group_title: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"url": url, "newTab": new_tab}
        if group_title:
            args["group_title"] = group_title
        return self.command("navigate", args)

    # Run a raw Chrome DevTools Protocol command (e.g. Page.bringToFront) through the daemon.
    def cdp(self, method: str, params: dict[str, Any] | None = None) -> Any:
        args: dict[str, Any] = {"method": method}
        if params:
            args["params"] = params
        data = self.command("cdp", args)
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data

    # Run JS in the current tab and return its JSON-encodable value.
    def evaluate(self, code: str) -> Any:
        data = self.command("evaluate", {"code": code})
        if not isinstance(data, dict) or "value" not in data:
            raise WebBridgeError(f"evaluate returned no value: {data}", reason="evaluate-no-value")
        return data["value"]

    # Return the full rendered outerHTML of the current tab.
    def page_html(self) -> str:
        return str(self.evaluate("document.documentElement.outerHTML"))

    # Download a CV over HTTP with the browser's own cookies. The tab stays put.
    #
    # Opening file.php in the tab shows the site's not-found page under automation,
    # and fetch() from the page is answered 404. A normal click downloads the file.
    # This sends that same request from outside the page, using the session cookies
    # the browser already holds, and never navigates to the file URL.
    def fetch_bytes(self, url: str) -> bytes:
        referer = self._current_tab_url()
        payload = self.cdp("Network.getCookies", {"urls": [url]})
        cookies = payload.get("cookies") if isinstance(payload, dict) else None
        header = _cookie_header(cookies if isinstance(cookies, list) else [])
        if not header:
            raise WebBridgeError(
                f"CV download failed for {url}: the browser has no login cookies",
                reason="download-failed",
            )
        user_agent = ""
        try:
            agent = self.evaluate("navigator.userAgent")
            if isinstance(agent, str):
                user_agent = agent
        except Exception:
            user_agent = ""
        headers = {
            "Accept": CV_DOWNLOAD_ACCEPT,
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": header,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }
        if user_agent:
            headers["User-Agent"] = user_agent
        if referer and "file.php" not in referer:
            headers["Referer"] = referer
        return _http_download(url, headers)

    # The URL of the tab this session is driving, sent as the CV download Referer.
    def _current_tab_url(self) -> str:
        for tab in self.list_tabs():
            if tab.get("active") and tab.get("url"):
                return str(tab["url"])
        return ""

    # List the tabs this session opened (diagnostics before/after cleanup).
    def list_tabs(self) -> list[dict[str, Any]]:
        data = self.command("list_tabs")
        if isinstance(data, dict):
            tabs = data.get("tabs")
            if isinstance(tabs, list):
                return [tab for tab in tabs if isinstance(tab, dict)]
        return []

    # Close every tab this session opened; the daemon answers {"success", "closed": n}.
    def close_session(self, *, timeout: float | None = None) -> dict[str, Any]:
        data = self.command("close_session", timeout=timeout)
        return data if isinstance(data, dict) else {}


# Best-effort cleanup of the tabs a session opened; never raises, never blocks a run.
# HR should never see a stack trace (or a failed screening) because the browser was
# already closed by hand or the extension dropped off while the reports were rendering.
def close_session_tabs(
    browser: WebBridgeClient | None,
    *,
    delay_seconds: float = 0.0,
    timeout: float = CLEANUP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if browser is None:
        return {"ok": False, "closed": 0, "reason": "no-browser"}
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    try:
        data = browser.close_session(timeout=timeout)
    except Exception as exc:  # cleanup is best-effort: a dead daemon is not a screening failure
        return {"ok": False, "closed": 0, "reason": str(exc)[:200]}
    closed = data.get("closed")
    return {
        "ok": bool(data.get("success", True)),
        "closed": int(closed) if isinstance(closed, (int, float)) else 0,
        "reason": None,
    }


__all__ = [
    "CV_CHUNK_BYTES",
    "DAEMON_START_WAIT",
    "DEFAULT_DAEMON_URL",
    "DEFAULT_SESSION",
    "EXTENSION_CONNECT_WAIT",
    "WebBridgeClient",
    "WebBridgeError",
    "close_session_tabs",
    "ensure_webbridge_daemon",
    "extension_version",
    "start_webbridge_daemon",
    "webbridge_status",
]
