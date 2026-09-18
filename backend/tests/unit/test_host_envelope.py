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


# Accepted and rejected skill weights are exposed as host-safe condition metadata.
def test_project_surfaces_condition_weight_metadata() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "success",
            "refno": "260901004",
            "jd_overrides": {
                "applied": True,
                "changed": 2,
                "must_skill_weights": [{"name": "R", "weight": 3.0}],
                "rejected_weights": [
                    {
                        "name": "Docker",
                        "weight": 3.0,
                        "reason": "weights are only allowed on must-have skills",
                    },
                    {"name": "Python", "weight": 99, "reason": "must-have weight must be between 0.5 and 3"},
                ],
            },
        },
    )

    assert validate_envelope(envelope) == []
    assert envelope["conditions"] == {
        "must_skill_weights": [{"skill": "R", "weight": 3.0}],
        "rejected_weights": [
            {
                "skill": "Docker",
                "reason": "weights are only allowed on must-have skills",
                "weight": "3",
            },
            {
                "skill": "Python",
                "reason": "must-have weight must be between 0.5 and 3",
                "weight": "99",
            },
        ],
        "applied": True,
        "changed": 2,
    }


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


# A conditions file HR saved but we cannot read gets its own code: it is her decision, not a
# pipeline fault, and a generic pipeline_error would have the agent report a crash rather than ask.
def test_project_screen_reports_unreadable_conditions() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "error",
            "error_message": (
                "jd-overrides.yaml could not be parsed (while parsing a flow sequence). Fix the "
                "file, or re-run with --conditions discard to screen against the job ad alone."
            ),
        },
    )
    assert validate_envelope(envelope) == []
    assert envelope["status"] == "error"
    assert envelope["error_code"] == "conditions_unreadable"
    # The filename leads the message on purpose, so it survives the 160-char truncation.
    assert "jd-overrides.yaml" in (envelope.get("error_message") or "")


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


# A multi-post run holds back its per-post derivation, so HR can confirm which requirements
# belong to which post before any score is produced (FR-9).
def test_project_conditions_pending_carries_per_post_deltas() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "conditions_pending",
            "refno": "260907003",
            "missing": ["conditions"],
            "questions": ["Confirm the per-post requirements."],
            "ask": {
                "missing": ["conditions"],
                "questions": ["Confirm the per-post requirements."],
                "post_deltas": [
                    {
                        "post": "Research Assistant",
                        "labels": ["Research Assistant (Full-time)", "Research Assistant (Part-time)"],
                        "confirmed": False,
                        "delta": ["Applicants for the Research Assistant post need honours."],
                    }
                ],
            },
        },
        jas_session="granted",
    )

    assert envelope["status"] == "conditions_pending"
    items = envelope["ask"]["post_deltas"]
    assert items[0]["post"] == "Research Assistant"
    assert items[0]["labels"] == [
        "Research Assistant (Full-time)",
        "Research Assistant (Part-time)",
    ]
    assert items[0]["delta"] == ["Applicants for the Research Assistant post need honours."]
    assert validate_envelope(envelope) == []


# The projected delta is bounded and scrubbed, because it is the one place advertisement prose
# reaches the conversation.
def test_project_post_deltas_bounds_and_scrubs_sentences() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "conditions_pending",
            "refno": "260907003",
            "missing": ["conditions"],
            "questions": ["Confirm the per-post requirements."],
            "ask": {
                "missing": ["conditions"],
                "questions": ["Confirm the per-post requirements."],
                "post_deltas": [
                    {
                        "post": "Research Assistant",
                        "labels": ["Research Assistant"],
                        "confirmed": False,
                        # An email must not survive into the conversation, and a very long
                        # sentence must not arrive unbounded.
                        "delta": ["Write to hr@example.edu for details." + "x" * 500],
                    }
                ],
            },
        },
        jas_session="granted",
    )

    sentence = envelope["ask"]["post_deltas"][0]["delta"][0]
    assert "hr@example.edu" not in sentence
    assert "[redacted]" in sentence
    assert len(sentence) <= 300


# Without per-post items the ask keeps the shape it has always had.
def test_project_conditions_pending_without_post_deltas_is_unchanged() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "conditions_pending",
            "refno": "260818001",
            "missing": ["conditions"],
            "questions": ["Reuse the saved conditions?"],
            "ask": {
                "missing": ["conditions"],
                "questions": ["Reuse the saved conditions?"],
                "conditions": {"must_skills": ["Python"]},
            },
        },
        jas_session="granted",
    )

    assert envelope["ask"]["conditions"]["must_skills"] == ["Python"]
    assert "post_deltas" not in envelope["ask"]


# A multi-post screen envelope states each post's count and top applicant, and each row's post.
def test_project_multi_post_carries_the_post_dimension() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "success",
            "refno": "260907003",
            "engine": "matching",
            "candidates": [
                {
                    "rank": 1,
                    "appno": "111111",
                    "total_score": 73.23,
                    "tier": "medium",
                    "post": "Research Assistant",
                },
                {
                    "rank": 1,
                    "appno": "222222",
                    "total_score": 68.0,
                    "tier": "medium",
                    "post": "Research Associate",
                },
            ],
            "posts": [
                {"post": "Research Assistant", "applicants": 3, "top_appno": "111111", "top_score": 73.23},
                {"post": "Research Associate", "applicants": 2, "top_appno": "222222", "top_score": 68.0},
            ],
            "needs_confirmation": [{"appno": "333333", "post": "Reserch Assistant"}],
        },
        jas_session="granted",
    )

    assert validate_envelope(envelope) == []
    assert envelope["status"] == "success"
    # Both rows carry rank 1, because a rank is only meaningful inside its own post (FR-5).
    assert [row["rank"] for row in envelope["ranking"]] == [1, 1]
    assert [row["post"] for row in envelope["ranking"]] == [
        "Research Assistant",
        "Research Associate",
    ]
    assert envelope["posts"]["groups"] == [
        {"post": "Research Assistant", "applicants": 3, "top_appno": "111111", "top_score": 73.23},
        {"post": "Research Associate", "applicants": 2, "top_appno": "222222", "top_score": 68.0},
    ]
    # The unreadable post reaches HR as it appeared on the page, never replaced by a guess (FR-7).
    assert envelope["posts"]["needs_confirmation"] == [
        {"appno": "333333", "post": "Reserch Assistant"}
    ]


# A four-post advertisement keeps the full-time and part-time variants apart and restarts ranks per
# post, so nothing in the envelope invites a comparison between posts (FR-4, FR-5, FR-11).
def test_project_four_post_keeps_variants_apart_and_ranks_per_post() -> None:
    # The real 260917001 shape: SPF/PDF x Full-time/Part-time, four posts, four applicant counts.
    groups = [
        ("Senior Project Fellow (Full-time)", "260917011", "260917012", 65.68),
        ("Senior Project Fellow (Part-time)", "260917009", "260917010", 71.07),
        ("Postdoctoral Fellow (Full-time)", "260917007", "260917006", 70.07),
        ("Postdoctoral Fellow (Part-time)", "260917004", "260917003", 65.76),
    ]
    candidates = []
    for post, top_appno, second_appno, top_score in groups:
        candidates.append(
            {"rank": 1, "appno": top_appno, "total_score": top_score, "tier": "medium", "post": post}
        )
        candidates.append(
            {
                "rank": 2,
                "appno": second_appno,
                "total_score": top_score - 10.0,
                "tier": "medium",
                "post": post,
            }
        )

    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "success",
            "refno": "260917001",
            "engine": "matching",
            "candidates": candidates,
            "posts": [
                {"post": post, "applicants": 2, "top_appno": top_appno, "top_score": top_score}
                for post, top_appno, _, top_score in groups
            ],
            "needs_confirmation": [],
        },
        jas_session="granted",
    )

    assert validate_envelope(envelope) == []
    # FT and PT share a base name, but they are two posts on the page and stay two groups here.
    assert envelope["posts"]["groups"] == [
        {"post": post, "applicants": 2, "top_appno": top_appno, "top_score": top_score}
        for post, top_appno, _, top_score in groups
    ]
    assert envelope["posts"]["needs_confirmation"] == []
    # Every post's ranking starts at 1, so the list never reads as one ranking across posts.
    assert [row["rank"] for row in envelope["ranking"]] == [1, 2, 1, 2, 1, 2, 1, 2]
    assert envelope["candidate_count"] == 8


# A failed applicant has no pipeline row, so their post comes from the records page.
def test_project_failed_applicant_keeps_its_post() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "partial_success",
            "refno": "260907003",
            "failures": [{"appno": "111111", "stage": "cv-parse"}],
        },
        jas_manifest={
            "refno": "260907003",
            "candidates": [{"appno": "111111", "status": "S", "post": "Research Assistant"}],
        },
        jas_session="granted",
    )

    assert validate_envelope(envelope) == []
    assert envelope["ranking"][0]["parse_failed"] is True
    assert envelope["ranking"][0]["post"] == "Research Assistant"


# A single-post screen envelope keeps the post dimension null and the row shape it always had.
def test_project_single_post_has_no_post_dimension() -> None:
    payload = json.loads(EXAMPLE_STDOUT.read_text(encoding="utf-8"))
    envelope = project_host_return(
        tool="screen_refno",
        payload=payload,
        jas_manifest=json.loads(EXAMPLE_JAS.read_text(encoding="utf-8")),
    )

    assert validate_envelope(envelope) == []
    assert envelope["posts"] is None
    assert envelope["ranking"][0]["post"] is None


# The check_updates envelope carries the post dimension and the post change keys (FR-12).
def test_project_check_updates_carries_the_post_dimension() -> None:
    envelope = project_host_return(
        tool="check_updates",
        payload={
            "status": "success",
            "refno": "260907003",
            "candidate_count": 2,
            "has_changes": True,
            "first_check": False,
            "changes": {
                "jd_changed": False,
                "added": [],
                "removed": [],
                "status_changed": {},
                "post_changed": {
                    "111111": {"from": "Research Assistant", "to": "Research Associate"}
                },
                "added_posts": {},
                "removed_posts": {},
                "posts_appeared": ["Research Associate"],
                "posts_disappeared": [],
            },
            "posts": [
                {"post": "Research Assistant", "applicants": 1},
                {"post": "Research Associate", "applicants": 1},
            ],
            "needs_confirmation": [],
        },
    )

    assert validate_envelope(envelope) == []
    assert envelope["has_changes"] is True
    assert envelope["changes"]["post_changed"] == {
        "111111": {"from": "Research Assistant", "to": "Research Associate"}
    }
    assert envelope["changes"]["posts_appeared"] == ["Research Associate"]
    # An update check knows the counts but not the scores, which only a screen produces.
    assert envelope["posts"]["groups"] == [
        {"post": "Research Assistant", "applicants": 1, "top_appno": None, "top_score": None},
        {"post": "Research Associate", "applicants": 1, "top_appno": None, "top_score": None},
    ]


# A post label that looks like markup is still caught before it can reach the conversation.
def test_forbidden_post_label_rejects_the_envelope() -> None:
    envelope = project_host_return(
        tool="screen_refno",
        payload={
            "status": "success",
            "refno": "260907003",
            "posts": [{"post": "<html>Research Assistant", "applicants": 1}],
        },
    )

    assert envelope["status"] == "error"
    assert envelope["error_code"] == "envelope_rejected"
