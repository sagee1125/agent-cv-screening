# Unit tests for the WorkBuddy host-envelope projector.
from __future__ import annotations

import json
from pathlib import Path

from host_envelope.project import project_host_return, rejected_envelope
from host_envelope.schema import validate_envelope

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_STDOUT = REPO_ROOT / ".codex" / "skills" / "host-envelope" / "examples" / "sample-pipeline-stdout.json"
EXAMPLE_JAS = REPO_ROOT / ".codex" / "skills" / "host-envelope" / "examples" / "sample-jas-manifest.json"


# Successful projection drops name/paths and keys the row by appno.
def test_project_strips_name_and_uses_appno() -> None:
    payload = json.loads(EXAMPLE_STDOUT.read_text(encoding="utf-8"))
    jas = json.loads(EXAMPLE_JAS.read_text(encoding="utf-8"))
    envelope = project_host_return(
        tool="screen_refno",
        payload=payload,
        jas_manifest=jas,
        jas_session="granted",
        cookie_file_present=True,
    )
    assert validate_envelope(envelope) == []
    assert envelope["status"] == "success"
    assert envelope["refno"] == "260818001"
    assert envelope["post_title"] == "Project Associate"
    assert "name" not in json.dumps(envelope)
    assert envelope["ranking"][0]["appno"] == "123456"
    assert envelope["ranking"][0]["hr_status"] == "TBC"
    assert envelope["ranking"][0]["match_score"] == 78.5
    assert envelope["ranking"][0]["total_score"] is None
    assert envelope["reports"]["comparison_xlsx"] is True
    assert envelope["reports"]["html_ready"] is True
    assert envelope["reports"]["directory"] is None
    assert envelope["auth"]["jas_session"] == "granted"
    assert "cookie_file" not in envelope["auth"]
    dumped = json.dumps(envelope)
    assert "Alice" not in dumped
    assert "C:\\\\Users" not in dumped and "C:\\Users" not in dumped


# Nested screening-agent result payloads are unwrapped before projection.
def test_project_unwraps_screening_agent_result() -> None:
    inner = json.loads(EXAMPLE_STDOUT.read_text(encoding="utf-8"))
    envelope = project_host_return(
        tool="get_run_status",
        payload={"status": "success", "result": inner, "runs": [{"payload": inner}]},
        jas_manifest=json.loads(EXAMPLE_JAS.read_text(encoding="utf-8")),
    )
    assert envelope["tool"] == "get_run_status"
    assert envelope["ranking"][0]["appno"] == "123456"
    assert "runs" not in envelope


# Unknown ask.missing keys are dropped; empty lists become input.
def test_need_input_missing_keys_are_allowlisted() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "need_input",
            "missing": ["cookies", "refno", "name"],
            "questions": ["Paste the cookie jar", "Confirm the job refno"],
            "ask": {"missing": ["cookies", "refno"], "questions": ["Paste cookies", "Which refno?"]},
        },
    )
    assert envelope["status"] == "need_input"
    assert envelope["ask"]["missing"] == ["refno"]
    assert all("cookie" not in q.lower() for q in envelope["ask"]["questions"])


# HTML or cookie payloads in the projected strings reject the envelope.
def test_html_payload_is_rejected() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={"status": "error", "error_message": "<html><body>Set-Cookie: a=b</body></html>"},
    )
    assert envelope["status"] == "error"
    assert envelope["error_code"] == "envelope_rejected"
    assert "<html" not in (envelope.get("error_message") or "").lower()


# request_jas_access never includes cookie values or file paths.
def test_request_jas_access_auth_only() -> None:
    envelope = project_host_return(tool="request_jas_access", jas_session="missing")
    assert envelope["status"] == "need_input"
    assert envelope["ask"]["missing"] == ["jas_session"]
    assert envelope["auth"]["cookie_file_present"] is False
    granted = project_host_return(
        tool="request_jas_access", jas_session="granted", cookie_file_present=True
    )
    assert granted["status"] == "success"
    assert granted["auth"] == {"jas_session": "granted", "cookie_file_present": True}


# Pipeline name-only rows do not become the host appno.
def test_name_is_not_used_as_appno() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "success",
            "engine": "legacy",
            "candidates": [{"rank": 1, "name": "Alice Chen", "total_score": 10, "tier": "Tier 2"}],
        },
    )
    assert envelope["ranking"][0]["appno"] == "unknown"
    assert envelope["ranking"][0]["total_score"] == 10.0
    assert "Alice" not in json.dumps(envelope)


# rejected_envelope stays within the whitelist.
def test_rejected_envelope_validates() -> None:
    envelope = rejected_envelope("screen_refno", "C:\\Users\\hr\\secret.html")
    assert validate_envelope(envelope) == []
    assert envelope["error_code"] == "envelope_rejected"
    assert "Users" not in (envelope["error_message"] or "")


# CLI prints whitelist JSON and drops identity fields from example stdout.
def test_host_envelope_cli_projects_example(tmp_path) -> None:
    import subprocess
    import sys

    script = REPO_ROOT / ".codex" / "skills" / "host-envelope" / "scripts" / "run_host_envelope.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--tool",
            "screen_refno",
            "--input",
            str(EXAMPLE_STDOUT),
            "--jas-manifest",
            str(EXAMPLE_JAS),
            "--jas-session",
            "granted",
            "--cookie-file-present",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["ranking"][0]["appno"] == "123456"
    assert "Alice" not in result.stdout


# check_updates stdout projects into a host-safe envelope with has_changes and changes.
def test_project_check_updates_success() -> None:
    envelope = project_host_return(
        tool="check_updates",
        payload={
            "status": "success",
            "tool": "check_updates",
            "refno": "260818001",
            "post_title": "Project Associate",
            "candidate_count": 3,
            "first_check": False,
            "has_changes": True,
            "changes": {
                "jd_changed": False,
                "added": ["999888"],
                "removed": [],
                "status_changed": {"123456": {"from": "TBC", "to": "S"}},
            },
        },
    )
    assert validate_envelope(envelope) == []
    assert envelope["tool"] == "check_updates"
    assert envelope["status"] == "success"
    assert envelope["refno"] == "260818001"
    assert envelope["has_changes"] is True
    assert envelope["first_check"] is False
    assert envelope["changes"]["added"] == ["999888"]
    assert envelope["changes"]["status_changed"]["123456"] == "S"
    assert envelope["ranking"] == []
    assert envelope["candidate_count"] == 3


# check_updates with first_check=True and has_changes=False still validates.
def test_project_check_updates_first_check() -> None:
    envelope = project_host_return(
        tool="check_updates",
        payload={
            "status": "success",
            "tool": "check_updates",
            "refno": "260818001",
            "post_title": "Project Associate",
            "candidate_count": 2,
            "first_check": True,
            "has_changes": False,
            "changes": {"jd_changed": False, "added": [], "removed": [], "status_changed": {}},
        },
    )
    assert validate_envelope(envelope) == []
    assert envelope["first_check"] is True
    assert envelope["has_changes"] is False
    assert envelope["changes"]["added"] == []


# check_updates need_input maps to ask.missing with refno.
def test_project_check_updates_need_input() -> None:
    envelope = project_host_return(
        tool="check_updates",
        payload={
            "status": "need_input",
            "missing": ["refno"],
            "questions": ["Please send the job reference number."],
        },
    )
    assert envelope["status"] == "need_input"
    assert envelope["ask"]["missing"] == ["refno"]
    assert envelope["has_changes"] is None


# check_updates error maps to error envelope without leaking details.
def test_project_check_updates_error() -> None:
    envelope = project_host_return(
        tool="check_updates",
        payload={
            "status": "error",
            "error_message": "Connection refused to C:\\Users\\hr\\secret.html",
        },
    )
    assert envelope["status"] == "error"
    assert envelope["error_code"] == "pipeline_error"
    assert "C:" not in (envelope.get("error_message") or "")
    assert "Users" not in (envelope.get("error_message") or "")


# A skill-reported not_found error survives projection for screen_refno.
def test_project_screen_preserves_not_found_error_code() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "error",
            "error_code": "not_found",
            "error_message": "no JAS job found for refno 999999999",
        },
    )
    assert validate_envelope(envelope) == []
    assert envelope["status"] == "error"
    assert envelope["error_code"] == "not_found"
    assert envelope["ranking"] == []


# check_updates projection keeps the explicit not_found error code.
def test_project_check_updates_preserves_not_found_error_code() -> None:
    envelope = project_host_return(
        tool="check_updates",
        payload={
            "status": "error",
            "error_code": "not_found",
            "error_message": "no JAS job found for refno 999999999",
        },
    )
    assert validate_envelope(envelope) == []
    assert envelope["status"] == "error"
    assert envelope["error_code"] == "not_found"
    assert envelope["changes"] is None
    assert envelope["has_changes"] is None
