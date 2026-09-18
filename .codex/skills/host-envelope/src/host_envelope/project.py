# Projects skill stdout onto the WorkBuddy host-visible JSON whitelist.
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from host_envelope.sanitize import looks_like_forbidden_payload, looks_like_secret_ask, sanitize_text
from host_envelope.schema import (
    ALLOWED_ERROR_CODES,
    ALLOWED_FAILURE_STAGES,
    ALLOWED_HR_STATUS,
    ALLOWED_MISSING,
    ALLOWED_SESSION,
    ALLOWED_STATUS,
    ALLOWED_TOOLS,
    SCHEMA_VERSION,
    validate_envelope,
)
from screening_core.candidate_id import appno_from_filename

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# Returns a minimal error envelope the host LLM is allowed to see.
def rejected_envelope(tool: str, message: str) -> dict[str, Any]:
    safe_tool = tool if tool in ALLOWED_TOOLS else "screen_refno"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": safe_tool,
        "status": "error",
        "error_code": "envelope_rejected",
        "error_message": sanitize_text(message, 160) or "envelope rejected",
        "run_id": None,
        "refno": None,
        "post_title": None,
        "engine": None,
        "candidate_count": None,
        "failed_count": None,
        "auth": None,
        "ask": None,
        "conditions": None,
        "ranking": [],
        "reports": None,
        "scratch_retained": None,
        "has_changes": None,
        "first_check": None,
        "changes": None,
    }


# Pulls the pipeline manifest out of a nested screening-agent envelope.
def unwrap_skill_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("result")
    if isinstance(inner, dict) and ("candidates" in inner or inner.get("status") == "need_input" or "ask" in inner):
        merged = dict(inner)
        merged.setdefault("status", payload.get("status"))
        return merged
    return payload


# Maps pipeline status strings onto the host enum.
def _status(value: object) -> str:
    text = str(value or "error")
    return text if text in ALLOWED_STATUS else "error"


# Picks a host error_code from status and skill error text.
def _error_code(status: str, error_message: str | None) -> str | None:
    if status == "need_input":
        return "need_input"
    if status == "conditions_pending":
        return "conditions_pending"
    if status == "partial_success":
        return "partial_failures"
    if status != "error":
        return None
    text = (error_message or "").lower()
    if "allowlist" in text or "not allowlisted" in text:
        return "host_not_allowlisted"
    if "cookie" in text or "unauthor" in text or "401" in text:
        return "unauthorized"
    if "expired" in text:
        return "session_expired"
    if "refno" in text:
        return "refno_invalid"
    if "fetch" in text or "http" in text:
        return "fetch_failed"
    return "pipeline_error"


# Picks the host error_code: an explicit payload code wins when allowed, else derive from text.
def _project_error_code(payload: dict[str, Any], status: str, error_message: str | None) -> str | None:
    code = payload.get("error_code")
    if code in ALLOWED_ERROR_CODES:
        return code
    return _error_code(status, error_message)


# Intersects ask.missing with the host enum; empty lists become ["input"].
def _project_ask(payload: dict[str, Any]) -> dict[str, Any] | None:
    ask = payload.get("ask") if isinstance(payload.get("ask"), dict) else None
    status = payload.get("status")
    missing_raw = []
    questions_raw = []
    if ask:
        missing_raw = ask.get("missing") or payload.get("missing") or []
        questions_raw = ask.get("questions") or payload.get("questions") or []
    else:
        missing_raw = payload.get("missing") or []
        questions_raw = payload.get("questions") or []
    if isinstance(missing_raw, str):
        missing_raw = [missing_raw]
    if isinstance(questions_raw, str):
        questions_raw = [questions_raw]
    missing = [str(item) for item in missing_raw if str(item) in ALLOWED_MISSING]
    if status == "need_input" and not missing:
        missing = ["input"]
    if not missing and status != "need_input":
        return None
    questions = [sanitize_text(item, 120) for item in list(questions_raw)[:6] if str(item).strip()]
    questions = [
        item
        for item in questions
        if item and not looks_like_forbidden_payload(item) and not looks_like_secret_ask(item)
    ][:6]
    if not questions:
        questions = ["Provide the missing screening inputs."]
    projected: dict[str, Any] = {"missing": missing or ["input"], "questions": questions}
    # Conditions the engine is holding back until HR answers: the conversation must be able
    # to read them back, otherwise it can only ask "reuse?" without saying what "them" is.
    if status == "conditions_pending":
        conditions = _project_conditions(ask.get("conditions") if ask else None)
        if conditions:
            projected["conditions"] = conditions
        # A multi-post advertisement also holds back its per-post derivation: HR confirms which
        # requirements belong to which post before any score is produced (FR-9).
        post_deltas = _project_post_deltas(ask.get("post_deltas") if ask else None)
        if post_deltas:
            projected["post_deltas"] = post_deltas
    return projected


# Projects the per-post derivations HR must confirm, one entry per post base name (FR-9).
# Each carries the post's own labels, its confirmation state, and the advertisement sentences the
# requirements were read from, so HR checks the attribution against the source. Sentences are
# bounded because this is the one place advertisement prose reaches the conversation.
def _project_post_deltas(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    out: list[dict[str, Any]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        post = sanitize_text(item.get("post"), 80)
        if not post or looks_like_forbidden_payload(post):
            continue
        labels = [
            label
            for label in (sanitize_text(value, 80) for value in list(item.get("labels") or [])[:4])
            if label and not looks_like_forbidden_payload(label)
        ]
        sentences = [
            sentence
            for sentence in (
                sanitize_text(value, 300) for value in list(item.get("delta") or [])[:12]
            )
            if sentence and not looks_like_forbidden_payload(sentence)
        ]
        if not sentences:
            continue
        out.append(
            {
                "post": post,
                "labels": labels,
                "confirmed": item.get("confirmed") is True,
                "delta": sentences,
            }
        )
    return out or None


# Keeps the stored conditions readable to HR while staying inside the host whitelist.
def _project_conditions(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("must_skills", "preferred_skills", "languages"):
        values = raw.get(key)
        if isinstance(values, list):
            cleaned = [sanitize_text(item, 80) for item in values[:40] if str(item).strip()]
            out[key] = [item for item in cleaned if item and not looks_like_forbidden_payload(item)]
    accepted_weights = _project_skill_weights(raw.get("must_skill_weights"))
    if accepted_weights:
        out["must_skill_weights"] = accepted_weights
    rejected_weights = _project_rejected_weights(raw.get("rejected_weights"))
    if rejected_weights:
        out["rejected_weights"] = rejected_weights
    collected = raw.get("collected_at")
    if collected:
        out["collected_at"] = sanitize_text(collected, 40)
    for key in ("target_seniority", "min_relevant_years"):
        value = raw.get(key)
        if value is not None:
            out[key] = sanitize_text(value, 40)
    applied = raw.get("applied")
    if isinstance(applied, bool):
        out["applied"] = applied
    changed = raw.get("changed")
    if isinstance(changed, int) and not isinstance(changed, bool):
        out["changed"] = max(0, min(changed, 1000))
    return out or None


# Projects accepted must-have weights into bounded host-safe records.
def _project_skill_weights(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values[:40]:
        if not isinstance(item, dict):
            continue
        name = sanitize_text(item.get("name"), 80)
        if not name or looks_like_forbidden_payload(name):
            continue
        try:
            weight = float(item.get("weight"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(weight) or not 0.5 <= weight <= 3.0:
            continue
        out.append({"skill": name, "weight": weight})
    return out


# Projects rejected must-have weights and reasons without exposing raw payloads.
def _project_rejected_weights(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values[:20]:
        if not isinstance(item, dict):
            continue
        name = sanitize_text(item.get("name"), 80)
        reason = sanitize_text(item.get("reason"), 160)
        if not name or not reason:
            continue
        if looks_like_forbidden_payload(name) or looks_like_forbidden_payload(reason):
            continue
        record: dict[str, Any] = {"skill": name, "reason": reason}
        raw_weight = item.get("weight")
        if isinstance(raw_weight, bool):
            record["weight"] = str(raw_weight).lower()
        elif isinstance(raw_weight, (int, float)):
            record["weight"] = (
                f"{raw_weight:g}" if math.isfinite(float(raw_weight)) else str(raw_weight)
            )
        else:
            weight_text = sanitize_text(raw_weight, 40)
            if weight_text and not looks_like_forbidden_payload(weight_text):
                record["weight"] = weight_text
        out.append(record)
    return out


# Projects only weight-related run conditions into the top-level host envelope.
def _project_run_conditions(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if not raw.get("must_skill_weights") and not raw.get("rejected_weights"):
        return None
    return _project_conditions(raw)


# Restricts an appno to the host schema charset; never copies a personal name field.
def _safe_appno(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", (value or "").strip())[:32]
    return cleaned or "unknown"


# Resolves application no. from a ranking row or a CV filename / URL.
def _appno_from_row(row: dict[str, Any], refno: str | None) -> str:
    if row.get("appno"):
        return _safe_appno(str(row["appno"]))
    source = str(row.get("source") or row.get("cv_path") or "")
    if source:
        return _safe_appno(appno_from_filename(Path(source).name or source, refno))
    return "unknown"


# Maps one pipeline candidate or failure onto a ranking row.
def _ranking_row(
    *,
    rank: int,
    appno: str,
    hr_status: str | None,
    engine: str | None,
    row: dict[str, Any] | None,
    parse_failed: bool,
    failure_stage: str | None,
) -> dict[str, Any]:
    status = hr_status if hr_status in ALLOWED_HR_STATUS else None
    stage = failure_stage if failure_stage in ALLOWED_FAILURE_STAGES else None
    total_score = None
    tier = None
    match_score = None
    fit_band = None
    eligible = None
    if row and not parse_failed:
        score = row.get("match_score", row.get("total_score"))
        band = row.get("fit_band") or row.get("tier")
        if engine == "matching":
            match_score = float(score) if score is not None and score != "" else None
            fit_band = str(band) if band else None
        else:
            total_score = float(score) if score is not None and score != "" else None
            tier = str(band) if band else None
        if isinstance(row.get("eligible"), bool):
            eligible = row["eligible"]
    return {
        "rank": rank,
        "appno": appno[:32],
        "hr_status": status,
        "total_score": total_score,
        "tier": sanitize_text(tier, 64) if tier else None,
        "match_score": match_score,
        "fit_band": sanitize_text(fit_band, 64) if fit_band else None,
        "eligible": eligible,
        "parse_failed": parse_failed,
        "failure_stage": stage,
    }


# Builds ranking from pipeline candidates, JAS HR status, and failures.
def _project_ranking(
    payload: dict[str, Any],
    jas: dict[str, Any],
    refno: str | None,
    engine: str | None,
) -> tuple[list[dict[str, Any]], int]:
    status_by_appno = {
        str(item.get("appno")): item.get("status")
        for item in (jas.get("candidates") or [])
        if isinstance(item, dict) and item.get("appno")
    }
    ranking: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in payload.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        appno = _appno_from_row(row, refno)
        seen.add(appno)
        ranking.append(
            _ranking_row(
                rank=int(row.get("rank") or (len(ranking) + 1)),
                appno=appno,
                hr_status=status_by_appno.get(appno),
                engine=engine,
                row=row,
                parse_failed=False,
                failure_stage=None,
            )
        )
    failed_count = 0
    for item in payload.get("failures") or []:
        if not isinstance(item, dict):
            continue
        failed_count += 1
        appno = _appno_from_row(item, refno)
        if appno in seen:
            for row in ranking:
                if row["appno"] == appno:
                    row["parse_failed"] = True
                    row["failure_stage"] = item.get("stage") if item.get("stage") in ALLOWED_FAILURE_STAGES else row["failure_stage"]
            continue
        seen.add(appno)
        ranking.append(
            _ranking_row(
                rank=len(ranking) + 1,
                appno=appno,
                hr_status=status_by_appno.get(appno),
                engine=engine,
                row=None,
                parse_failed=True,
                failure_stage=str(item.get("stage") or "") or None,
            )
        )
    for extra in jas.get("download_failures") or []:
        if not isinstance(extra, dict):
            continue
        appno = str(extra.get("appno") or "").strip()
        if not appno or appno in seen:
            continue
        failed_count += 1
        seen.add(appno)
        ranking.append(
            _ranking_row(
                rank=len(ranking) + 1,
                appno=appno,
                hr_status=status_by_appno.get(appno),
                engine=engine,
                row=None,
                parse_failed=True,
                failure_stage="download",
            )
        )
    return ranking[:200], failed_count


# Turns report paths into booleans/counts so filesystem paths stay off the model.
def _project_reports(payload: dict[str, Any]) -> dict[str, Any] | None:
    reports = payload.get("reports") if isinstance(payload.get("reports"), dict) else {}
    pdfs = 0
    for row in payload.get("candidates") or []:
        if isinstance(row, dict) and row.get("report_pdf"):
            pdfs += 1
    xlsx = bool(reports.get("comparison_xlsx")) if reports else False
    html_ready = bool(
        reports.get("ranking_overview_html") or reports.get("screening_board_html")
    )
    if not xlsx and not pdfs and not html_ready:
        return None
    return {
        "directory": None,
        "comparison_xlsx": xlsx,
        "pdf_count": min(pdfs, 200),
        "html_ready": html_ready,
        "open_hint": "open_in_panel",
    }


# Builds a safe run_id from an explicit value or the job refno.
def _run_id(run_id: str | None, refno: str | None) -> str | None:
    if run_id and _RUN_ID_RE.fullmatch(run_id):
        return run_id
    if refno and str(refno).isdigit():
        return f"run_{refno}"[:64]
    return None


# Walks JSON values and returns True when HTML, cookies, or multiline blobs appear.
def _payload_is_dirty(value: Any) -> bool:
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str) and looks_like_forbidden_payload(current):
            return True
    return False


# Projects a check_updates stdout payload into the host envelope (no ranking, just change summary).
def _project_check_updates(payload: dict[str, Any], jas_session: str | None, cookie_file_present: bool | None) -> dict[str, Any]:
    status = _status(payload.get("status"))
    refno = str(payload.get("refno") or "").strip() or None
    if refno and not str(refno).isdigit():
        refno = None
    title = sanitize_text(payload.get("post_title"), 120) if payload.get("post_title") else None
    if title and looks_like_forbidden_payload(title):
        title = None
    err_text = sanitize_text(payload.get("error_message"), 160) if payload.get("error_message") else None
    if err_text and looks_like_forbidden_payload(err_text):
        err_text = "update check failed"
    raw_changes = payload.get("changes") or {}
    changes = {
        "jd_changed": bool(raw_changes.get("jd_changed", False)),
        "added": [str(a) for a in (raw_changes.get("added") or [])][:200],
        "removed": [str(r) for r in (raw_changes.get("removed") or [])][:200],
        "status_changed": {
            str(k): str(v) if isinstance(v, str) else str(v.get("to", "")) if isinstance(v, dict) else ""
            for k, v in (raw_changes.get("status_changed") or {}).items()
        } if isinstance(raw_changes.get("status_changed"), dict) else {},
    }
    session = jas_session if jas_session in ALLOWED_SESSION else None
    auth = None
    if session is not None:
        auth = {"jas_session": session, "cookie_file_present": bool(cookie_file_present)}
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": "check_updates",
        "status": status,
        "error_code": _project_error_code(payload, status, err_text),
        "error_message": err_text if status == "error" else None,
        "run_id": _run_id(None, refno),
        "refno": refno,
        "post_title": title,
        "engine": None,
        "candidate_count": payload.get("candidate_count"),
        "failed_count": None,
        "auth": auth,
        "ask": _project_ask({**payload, "status": status}) if status == "need_input" else None,
        "conditions": None,
        "ranking": [],
        "reports": None,
        "scratch_retained": None,
        "has_changes": payload.get("has_changes"),
        "first_check": payload.get("first_check"),
        "changes": changes if status != "error" else None,
    }
    errors = validate_envelope(envelope)
    if errors or _payload_is_dirty(envelope):
        return rejected_envelope("check_updates", "check_updates envelope failed validation")
    return envelope


# Projects skill stdout (and optional JAS manifest) into a HostToolReturn object.
def project_host_return(
    *,
    tool: str,
    payload: dict[str, Any] | None = None,
    jas_manifest: dict[str, Any] | None = None,
    run_id: str | None = None,
    jas_session: str | None = None,
    cookie_file_present: bool | None = None,
    scratch_retained: bool | None = None,
    post_title: str | None = None,
) -> dict[str, Any]:
    safe_tool = tool if tool in ALLOWED_TOOLS else "screen_refno"
    jas = jas_manifest if isinstance(jas_manifest, dict) else {}
    if safe_tool == "request_jas_access":
        session = jas_session if jas_session in ALLOWED_SESSION else "missing"
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "tool": "request_jas_access",
            "status": "success" if session == "granted" else "need_input",
            "error_code": None if session == "granted" else "need_input",
            "error_message": None,
            "run_id": _run_id(run_id, None),
            "refno": None,
            "post_title": None,
            "engine": None,
            "candidate_count": None,
            "failed_count": None,
            "auth": {"jas_session": session, "cookie_file_present": bool(cookie_file_present)},
            "ask": None
            if session == "granted"
            else {
                "missing": ["jas_session"],
                "questions": ["Allow WorkBuddy to use your current JAS login. Do not paste session values."],
            },
            "conditions": None,
            "ranking": [],
            "reports": None,
            "scratch_retained": None,
            "has_changes": None,
            "first_check": None,
            "changes": None,
        }
        if session != "granted":
            envelope["status"] = "need_input"
        errors = validate_envelope(envelope)
        if errors or _payload_is_dirty(envelope):
            return rejected_envelope(safe_tool, "auth envelope failed validation")
        return envelope

    if safe_tool == "check_updates":
        skill = unwrap_skill_payload(payload) if payload else {}
        if _payload_is_dirty(skill) or (payload and _payload_is_dirty(payload)):
            return rejected_envelope(safe_tool, "skill stdout contained a forbidden payload")
        return _project_check_updates(skill, jas_session, cookie_file_present)

    skill = unwrap_skill_payload(payload)
    if _payload_is_dirty(skill) or _payload_is_dirty(payload):
        return rejected_envelope(safe_tool, "skill stdout contained a forbidden payload")
    status = _status(skill.get("status"))
    engine_raw = skill.get("engine")
    engine = engine_raw if engine_raw in ("legacy", "matching") else None
    refno = str(jas.get("refno") or skill.get("refno") or "").strip() or None
    if refno and not str(refno).isdigit():
        refno = None
    title = post_title or jas.get("post_title") or skill.get("post_title")
    title = sanitize_text(title, 120) if title else None
    if title and looks_like_forbidden_payload(title):
        title = None
    ranking, failed_count = _project_ranking(skill, jas, refno, engine)
    err_text = skill.get("error_message")
    err_text = sanitize_text(err_text, 160) if err_text else None
    if err_text and looks_like_forbidden_payload(err_text):
        err_text = "screening failed"
    session = jas_session if jas_session in ALLOWED_SESSION else None
    auth = None
    if session is not None:
        auth = {"jas_session": session, "cookie_file_present": bool(cookie_file_present)}
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": safe_tool,
        "status": status,
        "error_code": _project_error_code(skill, status, err_text),
        "error_message": err_text if status == "error" else None,
        "run_id": _run_id(run_id, refno),
        "refno": refno,
        "post_title": title,
        "engine": engine,
        "candidate_count": len([row for row in ranking if not row["parse_failed"]]),
        "failed_count": failed_count,
        "auth": auth,
        "ask": _project_ask({**skill, "status": status})
        if status in ("need_input", "conditions_pending")
        else None,
        "conditions": _project_run_conditions(skill.get("jd_overrides")),
        "ranking": ranking,
        "reports": _project_reports(skill),
        "scratch_retained": scratch_retained,
        "has_changes": None,
        "first_check": None,
        "changes": None,
    }
    errors = validate_envelope(envelope)
    if errors or _payload_is_dirty(envelope):
        return rejected_envelope(safe_tool, "projected envelope failed validation")
    return envelope


__all__ = ["project_host_return", "rejected_envelope", "unwrap_skill_payload"]
