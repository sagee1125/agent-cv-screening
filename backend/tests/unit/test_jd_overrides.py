# Unit tests for merging HR-supplied JD conditions (the conversation grill) onto the parsed JD.
from __future__ import annotations

import json

import pytest

from screening_core.jd_overrides import (
    FINAL_JD_FILENAME,
    ORIGIN_MOVED,
    ORIGIN_SUPPLEMENT,
    OVERRIDES_FILENAME,
    OverridesUnreadableError,
    describe_overrides,
    load_overrides,
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


# String-only skill lists keep the parsed weights and add no weight metadata.
def test_string_skill_entries_preserve_existing_merge_shape() -> None:
    parsed = _jd(["Python"], ["R"])
    parsed["structured_data"]["must_skills"][0]["weight"] = 2.5

    merged, summary = merge_structured(
        parsed,
        {"must_skills": ["Python"], "preferred_skills": ["R"]},
    )

    assert merged["must_skills"][0]["weight"] == 2.5
    assert "rejected_weights" not in summary
    assert "must_skill_weights" not in summary


# A valid mapping weight overrides the ad weight on a must-have skill.
def test_mapping_weight_overrides_existing_must_weight() -> None:
    merged, summary = merge_structured(
        _jd(["Python"], []),
        {"must_skills": [{"name": "Python", "weight": 2.5}], "preferred_skills": []},
    )

    assert merged["must_skills"][0]["weight"] == 2.5
    assert summary["must_skill_weights"] == [{"name": "Python", "weight": 2.5}]
    assert summary["counts"] == {"skills": 1}
    assert summary["changed"] == 1


# Bare names and weighted mappings can be mixed in the same must-have list.
def test_mixed_skill_entry_shapes_merge_together() -> None:
    merged, _ = merge_structured(
        _jd(["Python", "R"], ["Docker"]),
        {
            "must_skills": ["Python", {"name": "R", "weight": 2.0}],
            "preferred_skills": ["Docker"],
        },
    )

    assert [item["display_name"] for item in merged["must_skills"]] == ["Python", "R"]
    assert [item["weight"] for item in merged["must_skills"]] == [1.0, 2.0]


# An explicit weight overrides the normal 1.0 reset for preferred-to-must moves.
def test_explicit_weight_overrides_preferred_to_must_reset() -> None:
    merged, _ = merge_structured(
        _jd([], ["Python"]),
        {"must_skills": [{"name": "Python", "weight": 2.5}], "preferred_skills": []},
    )

    moved = merged["must_skills"][0]
    assert moved["weight"] == 2.5
    assert moved["provenance"]["origin"] == ORIGIN_MOVED


# A brand-new skill supplied by HR carries its explicit must-have weight.
def test_new_skill_carries_explicit_weight() -> None:
    merged, _ = merge_structured(
        _jd(["Python"], []),
        {"must_skills": ["Python", {"name": "R", "weight": 2.0}], "preferred_skills": []},
    )

    added = next(item for item in merged["must_skills"] if item["display_name"] == "R")
    assert added["weight"] == 2.0
    assert added["provenance"]["origin"] == ORIGIN_SUPPLEMENT


# Invalid must-have weights are rejected, reported, and never block the merge.
def test_invalid_must_weight_is_rejected_and_reported() -> None:
    for invalid in ("heavy", -1, 0, 99, float("nan")):
        merged, summary = merge_structured(
            _jd(["Python"], []),
            {
                "must_skills": [{"name": "Python", "weight": invalid}],
                "preferred_skills": [],
            },
        )

        assert merged["must_skills"][0]["weight"] == 1.0
        assert summary["applied"] is False
        rejected = summary["rejected_weights"]
        assert rejected[0]["name"] == "Python"
        assert rejected[0]["reason"]


# A weight on a preferred skill is rejected without changing preferred behaviour.
def test_preferred_weight_is_rejected_and_preferred_list_is_unchanged() -> None:
    merged, summary = merge_structured(
        _jd(["Python"], ["Docker"]),
        {
            "must_skills": ["Python"],
            "preferred_skills": [{"name": "Docker", "weight": 3.0}],
        },
    )

    assert merged["preferred_skills"][0]["weight"] == 1.0
    assert summary["applied"] is False
    assert summary["rejected_weights"] == [
        {
            "name": "Docker",
            "weight": 3.0,
            "reason": "weights are only allowed on must-have skills",
        }
    ]


# Duplicate skill tokens keep the maximum explicit weight instead of summing it.
def test_duplicate_must_skills_keep_maximum_weight() -> None:
    merged, summary = merge_structured(
        _jd(["Python"], []),
        {
            "must_skills": [
                "Python",
                {"name": "Python", "weight": 3.0},
                {"name": "Python", "weight": 2.0},
            ],
            "preferred_skills": [],
        },
    )

    assert merged["must_skills"][0]["weight"] == 3.0
    assert summary["changed"] == 1


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
    assert write_final_jd(tmp_path, jd_path, confirmed=True)[0] is None

    (tmp_path / "jd-overrides.yaml").write_text(
        "must_skills:\n  - Python\npreferred_skills:\n  - Docker\n", encoding="utf-8"
    )
    path, summary = write_final_jd(tmp_path, jd_path, confirmed=True)

    assert path is not None and path.name == FINAL_JD_FILENAME
    assert summary["applied"] is True
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["jd_overrides"]["applied"] is True
    assert envelope["structured_data"]["preferred_skills"][0]["display_name"] == "Docker"


# Stored conditions must never be merged until the current conversation confirms them.
def test_write_final_jd_refuses_unconfirmed_conditions(tmp_path) -> None:
    jd_path = tmp_path / "jd-parse.json"
    jd_path.write_text(json.dumps(_jd(["Python"], [])), encoding="utf-8")
    (tmp_path / "jd-overrides.yaml").write_text(
        "must_skills:\n  - Python\npreferred_skills:\n  - Docker\n", encoding="utf-8"
    )

    path, summary = write_final_jd(tmp_path, jd_path)

    assert path is None
    assert summary["applied"] is False
    assert summary["reason"] == "awaiting confirmation"
    assert not (tmp_path / FINAL_JD_FILENAME).exists()


# The conversation is handed the stored conditions so it can read them back to HR.
def test_describe_overrides_summarises_stored_conditions(tmp_path) -> None:
    from screening_core.jd_overrides import describe_overrides

    assert describe_overrides(tmp_path) is None

    (tmp_path / "jd-overrides.yaml").write_text(
        "collected_at: '2026-09-14'\n"
        "must_skills:\n  - Python\n  - R\n"
        "preferred_skills:\n  - Docker\n"
        "language_requirements:\n  - language: Cantonese\n",
        encoding="utf-8",
    )
    summary = describe_overrides(tmp_path)

    assert summary is not None
    assert summary["must_skills"] == ["Python", "R"]
    assert summary["preferred_skills"] == ["Docker"]
    assert summary["languages"] == ["Cantonese"]
    assert summary["collected_at"] == "2026-09-14"


# Stored conditions expose valid weights for readback and report rejected ones.
def test_describe_overrides_surfaces_skill_weights(tmp_path) -> None:
    from screening_core.jd_overrides import describe_overrides

    (tmp_path / "jd-overrides.yaml").write_text(
        "must_skills:\n"
        "  - Python\n"
        "  - name: R\n"
        "    weight: 2.0\n"
        "preferred_skills:\n"
        "  - name: Docker\n"
        "    weight: 3.0\n",
        encoding="utf-8",
    )

    summary = describe_overrides(tmp_path)

    assert summary is not None
    assert summary["must_skills"] == ["Python", "R ×2"]
    assert summary["must_skill_weights"] == [{"name": "R", "weight": 2.0}]
    assert summary["preferred_skills"] == ["Docker"]
    assert summary["rejected_weights"][0]["name"] == "Docker"


# Applying vs discarding conditions must not reuse each other's cached scores.
def test_conditions_applied_flag_invalidates_cached_scores(tmp_path) -> None:
    jd_path = tmp_path / "jd-parse.json"
    jd_path.write_text('{"structured_data": {}}', encoding="utf-8")
    overrides = tmp_path / "jd-overrides.yaml"
    overrides.write_text("must_skills:\n  - Python\n", encoding="utf-8")

    def payload(applied: bool) -> dict:
        return input_run_payload(
            engine="matching",
            position="Research Assistant",
            refno="260901004",
            jd_paths=[jd_path],
            cv_hashes={"cv1": "abc"},
            overrides_path=overrides,
            apply_overrides=applied,
        )

    assert overrides_changed(payload(True), payload(True)) is False
    # Same file, opposite decision: the scores are stale either way.
    assert overrides_changed(payload(True), payload(False)) is True
    # A fingerprint written before the flag existed reads as "not applied", so the first
    # confirmed run recomputes once rather than silently reusing unconfirmed scores.
    legacy = {key: value for key, value in payload(True).items() if key != "overrides_applied"}
    assert overrides_changed(legacy, payload(True)) is True
    assert overrides_changed(legacy, payload(False)) is False


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


# --- Per-post derivation grill (FR-9) ------------------------------------------------------

# The two posts of a multi-post advertisement, each with the sentences it was read from.
_DELTAS = {
    "Research Assistant": ["Applicants for the Research Assistant post need an honours degree."],
    "Research Associate": ["Applicants for the Research Associate post need a master's degree."],
}
# Two labels for the first post and one for the second: two items, not three.
_LABELS = [
    "Research Assistant (Full-time)",
    "Research Assistant (Part-time)",
    "Research Associate (Full-time)",
]


# One grill item per base name, tagged with its post and carrying the source sentences.
def test_post_grill_items_one_per_post_with_its_source_sentences() -> None:
    from screening_core.jd_overrides import post_grill_items

    items = post_grill_items(None, _DELTAS, _LABELS)

    assert [item["post"] for item in items] == ["Research Assistant", "Research Associate"]
    assert all(item["confirmed"] is False for item in items)
    assert items[0]["delta"] == _DELTAS["Research Assistant"]
    assert items[1]["delta"] == _DELTAS["Research Associate"]


# Full-time and part-time variants of one post share one item, so one answer covers both.
def test_post_grill_items_group_variants_by_base_name() -> None:
    from screening_core.jd_overrides import post_grill_items

    items = post_grill_items(None, _DELTAS, _LABELS)

    assert len(items) == 2
    assert items[0]["labels"] == ["Research Assistant (Full-time)", "Research Assistant (Part-time)"]
    # A base name no label states still names itself, so the item is never unlabelled.
    assert items[1]["labels"] == ["Research Associate (Full-time)"]


# A post whose requirements are all shared has no delta, so HR has nothing to confirm about it.
def test_post_grill_items_skip_a_post_with_no_delta() -> None:
    from screening_core.jd_overrides import post_grill_items

    deltas = dict(_DELTAS, **{"Research Fellow": []})
    items = post_grill_items(None, deltas, [*_LABELS, "Research Fellow"])

    assert [item["post"] for item in items] == ["Research Assistant", "Research Associate"]


# A confirmed post is not asked again, so a partially confirmed run asks only about what is left.
def test_pending_post_grill_skips_confirmed_posts() -> None:
    from screening_core.jd_overrides import POSTS_KEY, pending_post_grill

    overrides = {
        POSTS_KEY: [
            {
                "post": "Research Assistant",
                "confirmed": True,
                "delta": _DELTAS["Research Assistant"],
            }
        ]
    }

    assert [item["post"] for item in pending_post_grill(overrides, _DELTAS, _LABELS)] == [
        "Research Associate"
    ]


# Confirming both posts settles the grill, so a later run has nothing left to stop for.
def test_pending_post_grill_is_empty_when_every_post_is_confirmed() -> None:
    from screening_core.jd_overrides import POSTS_KEY, pending_post_grill

    overrides = {
        POSTS_KEY: [
            {"post": name, "confirmed": True, "delta": delta} for name, delta in _DELTAS.items()
        ]
    }

    assert pending_post_grill(overrides, _DELTAS, _LABELS) == []


# A confirmation is about the text HR saw: a changed advertisement re-opens the question rather
# than reusing an answer given about something else.
def test_pending_post_grill_reopens_when_the_derived_delta_changed() -> None:
    from screening_core.jd_overrides import POSTS_KEY, pending_post_grill

    overrides = {
        POSTS_KEY: [
            {
                "post": "Research Assistant",
                "confirmed": True,
                "delta": ["a sentence the advertisement no longer contains"],
            },
            {
                "post": "Research Associate",
                "confirmed": True,
                "delta": _DELTAS["Research Associate"],
            },
        ]
    }

    assert [item["post"] for item in pending_post_grill(overrides, _DELTAS, _LABELS)] == [
        "Research Assistant"
    ]


# The recorded post is matched by base name, so HR's answer survives the variant spelling.
def test_pending_post_grill_matches_the_recorded_post_by_base_name() -> None:
    from screening_core.jd_overrides import POSTS_KEY, pending_post_grill

    overrides = {
        POSTS_KEY: [
            {
                "post": "research assistant",
                "confirmed": True,
                "delta": _DELTAS["Research Assistant"],
            },
            {
                "post": "Research Associate (Full-time)",
                "confirmed": True,
                "delta": _DELTAS["Research Associate"],
            },
        ]
    }

    assert pending_post_grill(overrides, _DELTAS, _LABELS) == []


# A single-post run has no deltas, so the grill carries no post items and nothing changes for it.
def test_pending_post_grill_is_empty_without_deltas() -> None:
    from screening_core.jd_overrides import pending_post_grill

    assert pending_post_grill(None, {}, []) == []
    assert pending_post_grill(None, None, None) == []


# A missing conditions file is simply "no conditions".
def test_load_overrides_returns_none_when_the_file_is_absent(tmp_path) -> None:
    assert load_overrides(tmp_path) is None


# An empty conditions file holds no conditions, which is a valid state rather than a failure.
def test_load_overrides_returns_none_for_an_empty_file(tmp_path) -> None:
    (tmp_path / OVERRIDES_FILENAME).write_text("", encoding="utf-8")
    assert load_overrides(tmp_path) is None


# A conditions file that cannot be parsed is an error, never a silent "no conditions": HR would be
# shown a ranking scored against the job ad alone while believing her conditions were in force.
def test_load_overrides_raises_on_a_malformed_file(tmp_path) -> None:
    (tmp_path / OVERRIDES_FILENAME).write_text("must_skills: [Python\n", encoding="utf-8")

    with pytest.raises(OverridesUnreadableError) as excinfo:
        load_overrides(tmp_path)

    # The message has to name the file and the way out, because the agent acts on it directly.
    message = str(excinfo.value)
    assert OVERRIDES_FILENAME in message
    assert "--conditions discard" in message


# YAML that is not a mapping is HR data we cannot honour either, so it is an error too.
def test_load_overrides_raises_on_a_non_mapping_file(tmp_path) -> None:
    (tmp_path / OVERRIDES_FILENAME).write_text("- Python\n- SQL\n", encoding="utf-8")

    with pytest.raises(OverridesUnreadableError) as excinfo:
        load_overrides(tmp_path)

    assert "mapping" in str(excinfo.value)


# describe_overrides must not answer "no conditions" for a file it could not read either.
def test_describe_overrides_propagates_an_unreadable_file(tmp_path) -> None:
    (tmp_path / OVERRIDES_FILENAME).write_text("must_skills: [Python\n", encoding="utf-8")

    with pytest.raises(OverridesUnreadableError):
        describe_overrides(tmp_path)


# "none" is the parser's sentinel for "no degree level detected", not a degree. A JD that states no
# education requirement must render no line at all, never a false "Education: none" that reads as a
# requirement in its own right.
def test_education_sentinel_is_not_rendered_as_a_requirement() -> None:
    from report_gen.html_board import _parsed_groups

    html = _parsed_groups(
        {
            "education_requirement": {
                "minimum_degree": "none",
                "field_of_study": None,
                "is_mandatory": False,
            }
        }
    )

    assert "Education:" not in html


# A field of study with no stated degree level still renders: the sentinel drops the level, not the
# whole line, and the word "none" never reaches HR.
def test_education_line_keeps_the_field_when_the_degree_is_unstated() -> None:
    from report_gen.html_board import _parsed_groups

    html = _parsed_groups(
        {
            "education_requirement": {
                "minimum_degree": "none",
                "field_of_study": "computer science, software engineering",
                "is_mandatory": False,
            }
        }
    )

    assert "Education:</span> computer science, software engineering" in html
    assert "none" not in html.split("Education:</span>", 1)[1]
