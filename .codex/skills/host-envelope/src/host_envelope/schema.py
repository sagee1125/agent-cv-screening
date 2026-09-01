# Checks a projected HostToolReturn object against the WorkBuddy whitelist schema.
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0.0"
ALLOWED_TOOLS = frozenset({"request_jas_access", "screen_refno", "get_run_status", "check_updates"})
ALLOWED_STATUS = frozenset({"success", "partial_success", "need_input", "error"})
ALLOWED_ERROR_CODES = frozenset(
    {
        "envelope_rejected",
        "unauthorized",
        "session_expired",
        "host_not_allowlisted",
        "refno_invalid",
        "fetch_failed",
        "need_input",
        "not_found",
        "pipeline_error",
        "partial_failures",
        "internal",
    }
)
ALLOWED_MISSING = frozenset({"jas_session", "refno", "candidates", "jd", "position", "scope", "input"})
ALLOWED_HR_STATUS = frozenset({"TBC", "P", "S", "N"})
ALLOWED_FAILURE_STAGES = frozenset({"cv-parse", "score", "match", "report-gen", "download"})
ALLOWED_SESSION = frozenset({"missing", "granted", "denied", "expired"})
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
        "ranking",
        "reports",
        "scratch_retained",
        "has_changes",
        "first_check",
        "changes",
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
    return errors


__all__ = [
    "ALLOWED_ERROR_CODES",
    "ALLOWED_FAILURE_STAGES",
    "ALLOWED_HR_STATUS",
    "ALLOWED_MISSING",
    "ALLOWED_SESSION",
    "ALLOWED_STATUS",
    "ALLOWED_TOOLS",
    "SCHEMA_VERSION",
    "validate_envelope",
]
