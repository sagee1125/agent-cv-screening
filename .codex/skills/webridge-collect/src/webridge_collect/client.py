# Thin HTTP client for the Kimi WebBridge local daemon (http://127.0.0.1:10086).
from __future__ import annotations

import base64
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


# Client for the WebBridge daemon: one POST /command per browser action.
class WebBridgeClient:
    # Bind one client to a daemon URL and a session (tab group) name.
    def __init__(self, *, daemon_url: str = DEFAULT_DAEMON_URL, session: str = DEFAULT_SESSION, timeout: float = 120.0) -> None:
        self.daemon_url = daemon_url.rstrip("/")
        self.session = session
        self.timeout = timeout

    # POST one command and return the parsed JSON body.
    def command(self, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": action, "session": self.session}
        if args:
            payload["args"] = args
        try:
            response = httpx.post(f"{self.daemon_url}/command", json=payload, timeout=self.timeout)
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

    # Fetch a URL inside the browser (carries its login session) and return bytes.
    def fetch_bytes(self, url: str) -> bytes:
        meta = self.evaluate(
            "(async () => { const r = await fetch(%r); const b = await r.arrayBuffer(); "
            "window.__wbcv = { u: new Uint8Array(b), pos: 0, total: b.byteLength, status: r.status, ok: r.ok }; "
            "return { ok: r.ok, status: r.status, total: b.byteLength }; })()" % url
        )
        if not isinstance(meta, dict) or not meta.get("ok"):
            raise WebBridgeError(f"browser fetch failed for {url}: {meta}", reason="download-failed")
        chunks: list[str] = []
        for _ in range(int(meta.get("total", 0)) // CV_CHUNK_BYTES + 1):
            part = self.evaluate(
                "(function(){ const s = window.__wbcv; if (!s) return { error: 'no buffer' }; "
                "const CH = %d; const end = Math.min(s.pos + CH, s.total); let bin = ''; "
                "for (let i = s.pos; i < end; i++) bin += String.fromCharCode(s.u[i]); "
                "s.pos = end; return { done: s.pos >= s.total, pos: s.pos, total: s.total, chunk: btoa(bin) }; })()"
                % CV_CHUNK_BYTES
            )
            if not isinstance(part, dict) or "chunk" not in part:
                raise WebBridgeError(f"browser CV chunk failed: {part}", reason="download-failed")
            chunks.append(part["chunk"])
            if part.get("done"):
                break
        return base64.b64decode("".join(chunks))

    # Close every tab this session opened.
    def close_session(self) -> None:
        self.command("close_session")


__all__ = [
    "CV_CHUNK_BYTES",
    "DEFAULT_DAEMON_URL",
    "DEFAULT_SESSION",
    "WebBridgeClient",
    "WebBridgeError",
    "ensure_webbridge_daemon",
]
