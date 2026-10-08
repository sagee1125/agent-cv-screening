# The one sign-in test, shared by the readiness check and the screening run itself.
#
# It is a positive test: the page must land inside the internal area **and** render the records
# table. The sign-in hostname is never used as a signal, because an unknown identity provider
# could be reached from anywhere and a negative test on an unknown host would fail open.
#
# Both callers must use this same probe. If the readiness check and the run disagreed, a run
# could pass the check and then read a login page (reporting a job that "does not exist"), or
# refuse a page that was in fact fine — so the probe lives here rather than in either caller.
from __future__ import annotations

from typing import Any

from jas_import.errors import SiteLoginRequiredError

# The host-visible sentence for a failed login probe (preflight and the screening run).
# Opening jobs.polyu.edu.hk is not enough: the session must be inside /internal/, and Incognito
# hides the extension plus the signed-in cookies the collector needs.
ASK_LOGIN = (
    "You are not signed in to the internal job pages. Please sign in at "
    "https://jobs.polyu.edu.hk/internal in a normal Chrome window (not Incognito), then ask me again.",
    "你尚未登入內部招聘系統。請用一般 Chrome 視窗（不要用無痕）登入 "
    "https://jobs.polyu.edu.hk/internal ，然後再叫我。",
)

# JS run in the browser: report where we landed and whether the records table rendered.
# The selectors are the ones the parser itself looks for, so a page this accepts is a page the
# screening run can actually read.
LOGIN_PROBE_JS = """(() => {
  const table = document.querySelector('table#f-list, table.job-table, table.job-detail-table');
  return {
    path: String(location.pathname || '').slice(0, 200),
    has_table: !!table,
    title: String(document.title || '').slice(0, 120)
  };
})()"""


# Ask the browser where it landed, and answer the one question both callers share.
# A client that cannot answer is treated as not signed in: the caller is about to read a page it
# cannot vouch for, and refusing is the fail-closed direction.
def probe_sign_in(client: Any) -> dict:
    probe = client.evaluate(LOGIN_PROBE_JS)
    if not isinstance(probe, dict):
        return {"signed_in": False, "path": "", "has_table": False}
    path = str(probe.get("path") or "")
    has_table = bool(probe.get("has_table"))
    return {"signed_in": "/internal/" in path and has_table, "path": path, "has_table": has_table}


# Refuse to read a page that is really the sign-in page, on a site that requires a login.
#
# Called by the collector immediately before it reads the page, so a logged-out run stops with
# the right instruction instead of reporting a job that "does not exist". Sites that expect no
# login (the public demo) are unaffected.
def ensure_signed_in(client: Any, profile: dict) -> None:
    if not profile.get("expects_login"):
        return
    result = probe_sign_in(client)
    if not result["signed_in"]:
        raise SiteLoginRequiredError(
            "not signed in to the internal job system: the browser is on "
            f"{result['path'] or 'an unknown page'} instead of the internal records page"
            + ("" if result["has_table"] else " (and no records table rendered)")
            + ". Sign in at https://jobs.polyu.edu.hk/internal in a normal Chrome window "
            "(not Incognito), then run the screening again."
        )
