# Unit tests for merging HR-supplied JD conditions (the conversation grill) onto the parsed JD.
from __future__ import annotations

import json

from screening_core.jd_overrides import (
    FINAL_JD_FILENAME,
    ORIGIN_MOVED,
    ORIGIN_SUPPLEMENT,
    merge_structured,
    write_final_jd,
)
from screening_core.report_fingerprint import (
    input_run_payload,
    jd_inputs_changed,
    overrides_changed,
)


# Build a minimal parsed JD envelope carrying the given must/preferred skill names.
def _jd(must: list[str], preferred: list[str]) -> dict:
    def skill(name: str) -> dict:
        token = name.casefold().replace(" ", "_")
        return {
            "skill_id": token,
            "display_name": name,
            "canonical_skill": token,
            "weight": 1.0,
            "provenance": {"source_sentence": f"{name} is required."},
        }

    return {
        "structured_data": {
            "must_skills": [skill(name) for name in must],
            "preferred_skills": [skill(name) for name in preferred],
        }
    }


# A skill HR moved between tiers keeps its JD sentence but is marked as HR-sourced.
def test_merge_moves_skill_and_stamps_hr_origin() -> None:
    merged, summary = merge_structured(
        _jd(["Python", "Docker"], ["Excel"]),
        {"must_skills": ["Python"], "preferred_skills": ["Docker", "Excel"]},
    )

    assert summary["applied"] is True
    assert [item["display_name"] for item in merged["must_skills"]] == ["Python"]
    assert [item["display_name"] for item in merged["preferred_skills"]] == ["Docker", "Excel"]

    moved = merged["preferred_skills"][0]
    assert moved["provenance"]["origin"] == ORIGIN_MOVED
    assert moved["provenance"]["source_sentence"] == "Docker is required."


# A parsed skill that appears in neither of HR's lists was dropped by HR.
def test_merge_drops_skills_hr_removed() -> None:
    merged, _ = merge_structured(
        _jd(["Python", "Airflow"], []),
        {"must_skills": ["Python"], "preferred_skills": []},
    )

    assert [item["display_name"] for item in merged["must_skills"]] == ["Python"]
    assert merged["preferred_skills"] == []


# A name HR typed that the ad never mentioned is added and marked as a supplement.
def test_merge_adds_new_skill_as_hr_supplement() -> None:
    merged, _ = merge_structured(
        _jd(["Python"], []),
        {"must_skills": ["Python"], "preferred_skills": ["Kubernetes"]},
    )

    added = merged["preferred_skills"][0]
    assert added["display_name"] == "Kubernetes"
    assert added["provenance"]["origin"] == ORIGIN_SUPPLEMENT


# With no usable conditions file the parsed JD must come back untouched.
def test_merge_ignores_absent_and_empty_overrides() -> None:
    original = _jd(["Python"], [])

    merged, summary = merge_structured(original, None)
    assert summary["applied"] is False
    assert merged["must_skills"][0]["display_name"] == "Python"

    merged, summary = merge_structured(original, {"extra_notes": "nothing to change"})
    assert summary["applied"] is False
    assert merged["must_skills"][0]["display_name"] == "Python"


# Editing HR conditions must invalidate the scores without re-parsing the JD.
def test_conditions_edit_invalidates_scores_but_not_the_parse(tmp_path) -> None:
    jd_path = tmp_path / "jd-parse.json"
    jd_path.write_text('{"structured_data": {}}', encoding="utf-8")
    overrides = tmp_path / "jd-overrides.yaml"
    overrides.write_text("must_skills:\n  - Python\n", encoding="utf-8")

    def payload() -> dict:
        return input_run_payload(
            engine="matching",
            position="Research Assistant",
            refno="260901004",
            jd_paths=[jd_path],
            cv_hashes={"cv1": "abc"},
            overrides_path=overrides,
        )

    before = payload()
    assert overrides_changed(before, payload()) is False

    overrides.write_text("must_skills:\n  - Python\n  - R\n", encoding="utf-8")
    after = payload()
    assert overrides_changed(before, after) is True
    # The parsed JD is untouched, so must/nice assignment is never re-derived.
    assert jd_inputs_changed(before, after) is False

    jd_path.write_text('{"structured_data": {"must_skills": []}}', encoding="utf-8")
    assert jd_inputs_changed(after, payload()) is True


# jd-final.json is only written when the merge actually changed something.
def test_write_final_jd_is_skipped_when_nothing_changes(tmp_path) -> None:
    jd_path = tmp_path / "jd-parse.json"
    jd_path.write_text(json.dumps(_jd(["Python"], [])), encoding="utf-8")
    assert write_final_jd(tmp_path, jd_path)[0] is None

    (tmp_path / "jd-overrides.yaml").write_text(
        "must_skills:\n  - Python\npreferred_skills:\n  - Docker\n", encoding="utf-8"
    )
    path, summary = write_final_jd(tmp_path, jd_path)

    assert path is not None and path.name == FINAL_JD_FILENAME
    assert summary["applied"] is True
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["jd_overrides"]["applied"] is True
    assert envelope["structured_data"]["preferred_skills"][0]["display_name"] == "Docker"


# The report tooltip must label conversation-sourced requirements differently from the ad.
def test_hr_sourced_tooltip_is_labelled_as_conversation() -> None:
    from report_gen.html_board import _parsed_groups

    parsed = {
        "must_skills": [
            {
                "display_name": "Python",
                "canonical_skill": "python",
                "provenance": {"source_sentence": "Python is required."},
            }
        ],
        "preferred_skills": [
            {
                "display_name": "Docker",
                "canonical_skill": "docker",
                "provenance": {"origin": ORIGIN_MOVED, "source_sentence": "Docker is required."},
            }
        ],
    }

    html = _parsed_groups(parsed)

    assert "Moved by HR (conversation)" in html
    assert "tag-meta-hr" in html
    # An untouched requirement still reads as auto-extracted from the ad.
    assert "JD source (auto-extracted)" in html


# The summary counts every requirement HR moved, added or dropped.
def test_merge_counts_every_requirement_hr_touched() -> None:
    _, summary = merge_structured(
        _jd(["Python", "Docker"], ["Excel"]),
        {"must_skills": ["Python", "R"], "preferred_skills": ["Docker", "Excel"]},
    )

    # Docker moved down, R added.
    assert summary["counts"] == {"skills": 2}
    assert summary["changed"] == 2


# An education gate HR changed is stamped so the report can mark it.
def test_merge_marks_education_when_hr_changes_the_gate() -> None:
    parsed = {
        "structured_data": {
            "must_skills": [],
            "preferred_skills": [],
            "education_requirement": {"minimum_degree": "bachelor", "is_mandatory": False},
        }
    }

    merged, summary = merge_structured(
        parsed,
        {"eligibility_rules": [{"rule": "minimum_degree", "value": "master", "is_mandatory": True}]},
    )

    assert summary["counts"] == {"education": 1}
    assert merged["education_requirement"]["minimum_degree"] == "master"
    assert merged["education_requirement"]["provenance"]["origin"] == ORIGIN_SUPPLEMENT


# The report states which conditions produced the ranking.
def test_conditions_label_reports_hr_supplement_count() -> None:
    from report_gen.html_board import _conditions_line

    assert "Conditions: job ad only" in _conditions_line({})
    assert "Conditions: job ad only" in _conditions_line(
        {"hr_conditions": {"applied": False, "changed": 0}}
    )

    labelled = _conditions_line(
        {"hr_conditions": {"applied": True, "changed": 7, "collected_at": "2026-09-14"}}
    )
    assert "Conditions: job ad + 7 HR supplements" in labelled

    single = _conditions_line({"hr_conditions": {"applied": True, "changed": 1}})
    assert "Conditions: job ad + 1 HR supplement<" in single


# Education and work-authorisation lines carry an HR marker when HR changed them.
def test_education_gate_shows_hr_marker_in_the_report() -> None:
    from report_gen.html_board import _parsed_groups

    html = _parsed_groups(
        {
            "education_requirement": {
                "minimum_degree": "master",
                "is_mandatory": True,
                "provenance": {"origin": ORIGIN_SUPPLEMENT},
            }
        }
    )

    assert "Education:" in html
    assert "hr-mark" in html
    assert "Added by HR (conversation)" in html
