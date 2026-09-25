# Unit tests for the readiness preflight (webridge-collect run_preflight).
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# backend/tests/unit/test_preflight.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCRIPT = SKILLS_DIR / "webridge-collect" / "scripts" / "run_preflight.py"
COLLECT_SRC = SKILLS_DIR / "webridge-collect" / "src"
SHARED_SRC = SKILLS_DIR / "_shared" / "src"

for path in (COLLECT_SRC, SHARED_SRC):
    sys.path.insert(0, str(path))

from webridge_collect import client as client_mod  # noqa: E402


# A browser stub: records the navigations and answers the login probe.
class _FakeClient:
    def __init__(self, *, probe: object = None, error: Exception | None = None) -> None:
        self.probe = probe
        self.error = error
        self.navigated: list[str] = []

    def navigate(self, url: str, *, new_tab: bool = True, group_title: str | None = None) -> dict:
        self.navigated.append(url)
        return {}

    def evaluate(self, code: str) -> object:
        if self.error is not None:
            raise self.error
        return self.probe


def _import_cli():
    """Import the preflight CLI module in-process."""
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_preflight", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Install a fake browser and record whether the check closed its tabs.
def _patch_browser(module, monkeypatch, *, probe=None, error=None) -> tuple[dict, list]:
    holder: dict = {}
    closed: list = []

    def factory(**kwargs):
        holder["client"] = _FakeClient(probe=probe, error=error)
        return holder["client"]

    monkeypatch.setattr(module, "WebBridgeClient", factory)
    monkeypatch.setattr(
        module, "close_session_tabs", lambda client: closed.append(client) or {"ok": True, "closed": 1}
    )
    return holder, closed


# --- the daemon wait -------------------------------------------------------


# A daemon that already answers is used as-is, without starting anything.
def test_await_daemon_uses_a_running_daemon(monkeypatch) -> None:
    module = _import_cli()
    started: list = []
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    monkeypatch.setattr(module, "start_webbridge_daemon", lambda: started.append(1) or True)
    assert module._await_daemon("http://127.0.0.1:10086", wait_seconds=0.0) == {"extension_connected": True}
    assert started == []


# A daemon that is not running is started, then waited for: the check must not report "not
# running" for something a screening run would have started itself.
def test_await_daemon_starts_then_waits(monkeypatch) -> None:
    module = _import_cli()
    calls: list = []

    def fake_status(url, timeout=2.0):
        calls.append(1)
        return {"extension_connected": True} if len(calls) > 1 else None

    monkeypatch.setattr(module, "webbridge_status", fake_status)
    monkeypatch.setattr(module, "start_webbridge_daemon", lambda: True)
    assert module._await_daemon("http://127.0.0.1:10086", wait_seconds=0.5) == {"extension_connected": True}


# When the daemon cannot be started at all the wait gives up and reports nothing.
def test_await_daemon_gives_up_when_start_fails(monkeypatch) -> None:
    module = _import_cli()
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: None)
    monkeypatch.setattr(module, "start_webbridge_daemon", lambda: False)
    assert module._await_daemon("http://127.0.0.1:10086", wait_seconds=5.0) is None


# An extension that attaches late is picked up by the wait.
def test_await_extension_polls_until_connected(monkeypatch) -> None:
    module = _import_cli()
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    result = module._await_extension("http://127.0.0.1:10086", {"extension_connected": False}, wait_seconds=0.5)
    assert result["extension_connected"] is True


# --- the login probe -------------------------------------------------------


# Inside /internal/ with the records table rendered is the positive sign-in test.
def test_check_login_passes_inside_internal_with_table(monkeypatch) -> None:
    module = _import_cli()
    client = _FakeClient(probe={"path": "/internal/records.php", "has_table": True})
    result = module._check_login(client, {"list_url": "https://jobs.polyu.edu.hk/internal/records.php"})
    assert result == {"check": "login", "ok": True, "reason": None, "version": None}


# A page outside /internal/ is not a signed-in JAS page even if it renders a table: the identity
# provider is unknown, so only landing inside the internal area counts.
def test_check_login_fails_outside_internal(monkeypatch) -> None:
    module = _import_cli()
    client = _FakeClient(probe={"path": "/sso/login", "has_table": True})
    result = module._check_login(client, {"list_url": "https://jobs.polyu.edu.hk/internal/records.php"})
    assert result["ok"] is False
    assert result["reason"] == "not_signed_in"


# A sign-in form served in place under /internal/ has no records table, so it is not signed in.
def test_check_login_fails_without_the_records_table(monkeypatch) -> None:
    module = _import_cli()
    client = _FakeClient(probe={"path": "/internal/records.php", "has_table": False})
    result = module._check_login(client, {"list_url": "https://jobs.polyu.edu.hk/internal/records.php"})
    assert result["ok"] is False
    assert result["reason"] == "not_signed_in"


# --- the CLI ---------------------------------------------------------------


# The http driver drives no browser, so there is nothing to check and nothing is opened.
def test_cli_http_driver_reports_no_checks(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "0")
    monkeypatch.setattr(sys, "argv", [module.__file__, "--driver", "http"])
    assert module.main() == module.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert payload["checks"] == []
    assert payload["site"] == "demo"


# A daemon that cannot be started asks HR to start it, naming the browser rather than a session.
def test_cli_daemon_unreachable_asks_for_the_browser(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "0")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: None)
    monkeypatch.setattr(module, "start_webbridge_daemon", lambda: False)
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_NEED_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing"] == ["browser"]
    assert payload["checks"] == [{"check": "daemon", "ok": False, "reason": "daemon_unreachable", "version": None}]


# A running daemon with no extension attached asks for the extension specifically.
def test_cli_extension_disabled(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "0")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": False})
    monkeypatch.setattr(module, "EXTENSION_CONNECT_WAIT", 0.0)
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_NEED_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing"] == ["extension"]
    assert [item["check"] for item in payload["checks"]] == ["daemon", "extension"]
    assert payload["checks"][1]["reason"] == "extension_disabled"


# The demo site is public, so its check list never includes a login probe.
def test_cli_demo_never_checks_login(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "0")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True, "version": "2.0.17"})
    _patch_browser(module, monkeypatch, probe={"path": "/sso/login", "has_table": False})
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert [item["check"] for item in payload["checks"]] == ["daemon", "extension"]
    assert payload["checks"][1]["version"] == "2.0.17"


# On the internal site a signed-out browser is reported as a session problem, not a browser one.
def test_cli_prod_not_signed_in(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "1")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    _patch_browser(module, monkeypatch, probe={"path": "/sso/login", "has_table": True})
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_NEED_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing"] == ["jas_session"]
    assert payload["checks"][-1] == {"check": "login", "ok": False, "reason": "not_signed_in", "version": None}


# A signed-in internal browser passes all three checks.
def test_cli_prod_signed_in(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "1")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    holder, _ = _patch_browser(module, monkeypatch, probe={"path": "/internal/records.php", "has_table": True})
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert [item["check"] for item in payload["checks"]] == ["daemon", "extension", "login"]
    assert all(item["ok"] for item in payload["checks"])
    # The probe opened the internal records page, not the demo list.
    assert holder["client"].navigated == ["https://jobs.polyu.edu.hk/internal/records.php"]


# The check opened a page only to look at it, so it is closed again by default.
def test_cli_closes_the_tabs_it_opened(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "1")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    _, closed = _patch_browser(module, monkeypatch, probe={"path": "/internal/records.php", "has_table": True})
    monkeypatch.setattr(sys, "argv", [module.__file__])
    module.main()
    capsys.readouterr()
    assert len(closed) == 1


# --keep-browser leaves the page on screen for inspection.
def test_cli_keep_browser_keeps_the_tab(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "1")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    _, closed = _patch_browser(module, monkeypatch, probe={"path": "/internal/records.php", "has_table": True})
    monkeypatch.setattr(sys, "argv", [module.__file__, "--keep-browser"])
    module.main()
    capsys.readouterr()
    assert closed == []


# A failed sign-in still closes the page: the check left nothing to look at.
def test_cli_not_signed_in_still_closes_the_tabs(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "1")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    _, closed = _patch_browser(module, monkeypatch, probe={"path": "/sso/login", "has_table": False})
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_NEED_INPUT
    capsys.readouterr()
    assert len(closed) == 1


# A typo in the switch refuses to start rather than checking the wrong site.
def test_cli_refuses_bad_site_mode(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "production")
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_ERROR
    captured = capsys.readouterr()
    assert json.loads(captured.err)["error_code"] == "bad_site_mode"


# A browser command that blows up after the checks passed is a real error, not a sign-in problem.
def test_cli_probe_failure_is_an_error(monkeypatch, capsys) -> None:
    module = _import_cli()
    monkeypatch.setenv("JES_SITE_MODE", "1")
    monkeypatch.setattr(module, "webbridge_status", lambda url, timeout=2.0: {"extension_connected": True})
    _patch_browser(module, monkeypatch, error=RuntimeError("browser went away"))
    monkeypatch.setattr(sys, "argv", [module.__file__])
    assert module.main() == module.EXIT_ERROR
    captured = capsys.readouterr()
    assert json.loads(captured.err)["status"] == "error"


# --- the client primitives -------------------------------------------------


# /status is read over GET or POST; an unreachable or non-JSON daemon reports nothing.
def test_webbridge_status_shapes(monkeypatch) -> None:
    import httpx

    class _Response:
        def __init__(self, *, status_code=200, payload=None, raises=False) -> None:
            self.status_code = status_code
            self._payload = payload
            self._raises = raises

        def json(self):
            if self._payload is None:
                raise json.JSONDecodeError("bad", "", 0)
            return self._payload

    def fake_get(url, timeout=None):
        return _Response(payload={"extension_connected": True, "version": "2.0.17"})

    monkeypatch.setattr(client_mod.httpx, "get", fake_get)
    monkeypatch.setattr(client_mod.httpx, "post", lambda url, timeout=None: _Response(status_code=502))
    assert client_mod.webbridge_status() == {"extension_connected": True, "version": "2.0.17"}

    def boom(url, timeout=None):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(client_mod.httpx, "get", boom)
    assert client_mod.webbridge_status() is None


# The extension version is only reported while an extension is actually attached.
def test_extension_version_requires_a_connected_extension() -> None:
    assert client_mod.extension_version({"extension_connected": True, "version": "2.0.17"}) == "2.0.17"
    assert client_mod.extension_version({"extension_connected": True, "extension_version": "1.2.3"}) == "1.2.3"
    assert client_mod.extension_version({"extension_connected": False, "version": "2.0.17"}) is None
    assert client_mod.extension_version(None) is None
    assert client_mod.extension_version({"extension_connected": True}) is None
