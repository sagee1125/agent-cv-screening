# Checks a projected HostToolReturn object against the WorkBuddy whitelist schema.
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0.0"
ALLOWED_TOOLS = frozenset(
    {"request_jas_access", "screen_refno", "get_run_status", "check_updates", "preflight"}
)
ALLOWED_STATUS = frozenset({"success", "partial_success", "need_input", "conditions_pending", "error"})
ALLOWED_ERROR_CODES = frozenset(
    {
        "envelope_rejected",
        "unauthorized",
        "session_expired",
        "host_not_allowlisted",
        "refno_invalid",
        "fetch_failed",
        "need_input",
        "conditions_pending",
        "not_found",
        "conditions_unreadable",
        "pipeline_error",
        "partial_failures",
        "internal",
        # The readiness check's reasons. They also travel as checks[].reason, but a whitelist that
        # does not know them is the exact trap this schema exists to close: the value would be
        # silently swallowed and HR would be told "something went wrong" instead of what to fix.
        "daemon_unreachable",
        "extension_disabled",
        "not_signed_in",
        # A site switch that is neither prod nor demo; the run refuses to start rather than
        # silently screening the wrong site.
        "bad_site_mode",
    }
)
ALLOWED_MISSING = frozenset(
    {
        "jas_session",
        "refno",
        "candidates",
        "jd",
        "position",
        "scope",
        "input",
        "conditions",
        # Client-side prerequisites of the browser flow, so a readiness failure can name the one
        # thing HR has to fix instead of collapsing into a generic "input".
        "browser",
        "extension",
    }
)
ALLOWED_HR_STATUS = frozenset({"TBC", "P", "S", "N"})
ALLOWED_FAILURE_STAGES = frozenset({"cv-parse", "score", "match", "report-gen", "download"})
ALLOWED_SESSION = frozenset({"missing", "granted", "denied", "expired"})
# Which site a run used. Without it a wrong-site run is undetectable after the fact, because the
# report it produced looks entirely normal (decision 2.8).
ALLOWED_SITES = frozenset({"demo", "prod"})
# The readiness check's per-check records. The identifier key is `check`, not `name`: `name` is
# denylisted because it is the candidate-name field, and a check record must never borrow it.
ALLOWED_CHECKS = frozenset({"daemon", "extension", "login"})
ALLOWED_CHECK_REASONS = frozenset({"daemon_unreachable", "extension_disabled", "not_signed_in"})
CHECK_KEYS = frozenset({"check", "ok", "reason", "version"})
TOP_KEYS = frozenset(
    {
        "schema_version",
        "tool",
        "status",
        "error_code",
        "error_message",
        "run_id",
        "refno",
        "post_title",
        "engine",
        "candidate_count",
        "failed_count",
        "auth",
        "ask",
        "conditions",
        "ranking",
        "reports",
        "scratch_retained",
        "has_changes",
        "first_check",
        "changes",
        # The post dimension: per-post applicant counts and the applicants whose post the page
        # did not state. Both the screen and the update check report it (FR-7, FR-11, FR-12).
        "posts",
        # Which site the run used, and the readiness check's per-check results.
        "site",
        "checks",
    }
)
RANKING_KEYS = frozenset(
    {
        "rank",
        "appno",
        "hr_status",
        "total_score",
        "tier",
        "match_score",
        "fit_band",
        "eligible",
        "parse_failed",
        "failure_stage",
        # Which post this row's rank is relative to. A rank is only meaningful inside its post,
        # so the conversation cannot read the ranking correctly without it (FR-5, FR-11).
        "post",
    }
)
DENY_KEYS = frozenset(
    {
        "name",
        "email",
        "phone",
        "hkid",
        "salary",
        "cookie",
        "cookies",
        "cookie_file",
        "jd_text",
        "extracted_json",
        "score_json",
        "detail_json",
        "interview_questions",
        "radar_dimensions",
    }
)


# Walks a JSON-like value and records denylisted keys.
def _collect_deny_keys(value: Any, found: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in DENY_KEYS:
                found.append(str(key))
            _collect_deny_keys(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_deny_keys(child, found)


# Returns a list of whitelist violations, empty when the envelope is host-safe.
def validate_envelope(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["envelope is not an object"]
    extra = set(payload) - TOP_KEYS
    if extra:
        errors.append(f"unknown keys: {sorted(extra)}")
    deny: list[str] = []
    _collect_deny_keys(payload, deny)
    if deny:
        errors.append(f"denylisted keys: {sorted(set(deny))}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    if payload.get("tool") not in ALLOWED_TOOLS:
        errors.append("tool")
    if payload.get("status") not in ALLOWED_STATUS:
        errors.append("status")
    code = payload.get("error_code")
    if code is not None and code not in ALLOWED_ERROR_CODES:
        errors.append("error_code")
    refno = payload.get("refno")
    if refno is not None and (not str(refno).isdigit() or len(str(refno)) > 16):
        errors.append("refno")
    ranking = payload.get("ranking") or []
    if not isinstance(ranking, list):
        errors.append("ranking")
    else:
        for index, row in enumerate(ranking):
            if not isinstance(row, dict):
                errors.append(f"ranking[{index}]")
                continue
            extra_row = set(row) - RANKING_KEYS
            if extra_row:
                errors.append(f"ranking[{index}] extra {sorted(extra_row)}")
            if "rank" not in row or "appno" not in row or "parse_failed" not in row:
                errors.append(f"ranking[{index}] required")
    ask = payload.get("ask")
    if ask is not None:
        missing = ask.get("missing") or []
        if any(item not in ALLOWED_MISSING for item in missing):
            errors.append("ask.missing")
    site = payload.get("site")
    if site is not None and site not in ALLOWED_SITES:
        errors.append("site")
    checks = payload.get("checks")
    if checks is not None:
        if not isinstance(checks, list):
            errors.append("checks")
        else:
            for index, item in enumerate(checks):
                if not isinstance(item, dict):
                    errors.append(f"checks[{index}]")
                    continue
                extra_check = set(item) - CHECK_KEYS
                if extra_check:
                    errors.append(f"checks[{index}] extra {sorted(extra_check)}")
                if item.get("check") not in ALLOWED_CHECKS:
                    errors.append(f"checks[{index}] check")
                if not isinstance(item.get("ok"), bool):
                    errors.append(f"checks[{index}] ok")
                reason = item.get("reason")
                if reason is not None and reason not in ALLOWED_CHECK_REASONS:
                    errors.append(f"checks[{index}] reason")
    return errors


__all__ = [
    "ALLOWED_CHECK_REASONS",
    "ALLOWED_CHECKS",
    "ALLOWED_ERROR_CODES",
    "ALLOWED_FAILURE_STAGES",
    "ALLOWED_HR_STATUS",
    "ALLOWED_MISSING",
    "ALLOWED_SESSION",
    "ALLOWED_SITES",
    "ALLOWED_STATUS",
    "ALLOWED_TOOLS",
    "CHECK_KEYS",
    "SCHEMA_VERSION",
    "validate_envelope",
]
