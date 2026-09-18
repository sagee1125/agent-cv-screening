"""Tests for the multi-post ranking board: one section per post (PRD-Multi_Post step 6)."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_SCRIPT = REPO_ROOT / ".codex" / "skills" / "report-gen" / "scripts" / "run_report.py"


# Import the report-gen CLI module in-process, matching the other skill CLI test modules.
def _import_report_cli() -> Any:
    sys.path.insert(0, str(REPORT_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("skill_report_cli_multi_post", REPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# One board row as the pipeline writes it: a rank, an application number and the post applied for.
def _row(appno: str, post: str, rank: int, score: float, tier: str = "medium") -> dict[str, Any]:
    return {
        "rank": rank,
        "refno": "260901004",
        "appno": appno,
        "post": post,
        "total_score": score,
        "tier": tier,
    }


# Two posts with one applicant each, plus a full-time/part-time pair sharing the first post's JD.
def _rows() -> list[dict[str, Any]]:
    return [
        _row("260901001", "Senior Project Fellow (Full-time)", 1, 80.78),
        _row("260901002", "Senior Project Fellow (Part-time)", 1, 62.1),
        _row("260901003", "Postdoctoral Fellow (Full-time)", 1, 90.83),
        _row("260901004", "Postdoctoral Fellow (Full-time)", 2, 84.95),
    ]


# Per-post JD data as run_report.py reads it out of post-jds.json, keyed by post base name.
def _post_jds() -> dict[str, dict[str, Any]]:
    return {
        "Senior Project Fellow": {
            "jd_text": "Senior Project Fellow duties.",
            "jd_parsed": {
                "must_skills": [{"canonical_skill": "Project Management"}],
                "language_requirements": [{"language": "Cantonese", "is_mandatory": True}],
            },
            "delta": ["The appointee must be fluent in Cantonese and Putonghua."],
        },
        "Postdoctoral Fellow": {
            "jd_text": "Postdoctoral Fellow duties.",
            "jd_parsed": {"must_skills": [{"canonical_skill": "Python"}]},
            "delta": ["A PhD in a related discipline is required."],
        },
    }


# Render a board and return its HTML.
def _board(tmp_path: Path, rows: list[dict[str, Any]], **kwargs: Any) -> str:
    from report_gen.html_board import write_screening_board

    out = tmp_path / "ranking-overview.html"
    write_screening_board(
        str(out),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
        refno="260901004",
        rows=rows,
        **kwargs,
    )
    return out.read_text(encoding="utf-8")


# One collapsible section per post, in post-universe order, and only the first one defaults open.
def test_board_renders_one_section_per_post_in_order(tmp_path: Path) -> None:
    text = _board(tmp_path, _rows(), post_jds=_post_jds())
    assert text.count("<details class='post-section'") == 3
    order = [
        text.index("Senior Project Fellow (Full-time)"),
        text.index("Senior Project Fellow (Part-time)"),
        text.index("Postdoctoral Fellow (Full-time)"),
    ]
    assert order == sorted(order)
    # FR-6.4: the first section is expanded, every other section is collapsed.
    assert text.count("<details class='post-section' open>") == 1
    assert text.index("<details class='post-section' open>") < text.index(
        "Senior Project Fellow (Part-time)"
    )


# Full-time and part-time variants are two posts, so they get two sections sharing one JD panel.
def test_board_variants_share_one_effective_jd(tmp_path: Path) -> None:
    text = _board(tmp_path, _rows(), post_jds=_post_jds())
    assert text.count("Requirements specific to this post") == 3
    assert text.count("The appointee must be fluent in Cantonese and Putonghua.") == 2
    assert text.count("A PhD in a related discipline is required.") == 1


# Each section header states the post label, its applicant count and its top score (FR-6.3).
def test_board_section_header_states_count_and_top_score(tmp_path: Path) -> None:
    text = _board(tmp_path, _rows(), post_jds=_post_jds())
    assert "Postdoctoral Fellow (Full-time)</span><span class='post-count'>2 applicants</span>" in text
    assert "<span class='post-top'>Top score 90.83</span>" in text
    assert "<span class='post-top'>Top score 80.78</span>" in text
    assert "Senior Project Fellow (Part-time)</span><span class='post-count'>1 applicant</span>" in text


# A section ranks its own applicants only, so the same rank number recurs across sections (FR-6.5).
def test_board_ranks_within_a_section_only(tmp_path: Path) -> None:
    text = _board(tmp_path, _rows(), post_jds=_post_jds())
    # Three posts, each with a rank 1 of its own; the second Postdoc row is rank 2 inside its post.
    assert text.count("<td>1</td>") == 3
    assert text.count("<td>2</td>") == 1
    # No merged list: the 90.83 Postdoc row is never given rank 1 of the whole run.
    assert text.count("<td>4</td>") == 0


# The per-post panel carries that post's parsed requirements, not just its delta (FR-6.3).
def test_board_per_post_panel_shows_delta_and_parsed_tags(tmp_path: Path) -> None:
    text = _board(
        tmp_path,
        _rows(),
        jd_parsed={"must_skills": [{"canonical_skill": "Teamwork"}]},
        post_jds=_post_jds(),
    )
    assert "Requirements for this post" in text
    assert "Project Management" in text
    assert "Cantonese" in text
    assert "Python" in text


# A post whose tag groups are the shared ones names them instead of repeating them (FR-6.3).
def test_board_post_panel_does_not_repeat_the_shared_tag_groups(tmp_path: Path) -> None:
    shared = {
        "must_skills": [{"canonical_skill": "Python"}],
        "language_requirements": [{"language": "Cantonese", "is_mandatory": True}],
    }
    post_jds = {
        "Senior Project Fellow": {
            "jd_text": "Senior Project Fellow duties.",
            "jd_parsed": {
                "must_skills": [{"canonical_skill": "Python"}],
                "language_requirements": [{"language": "Cantonese", "is_mandatory": True}],
            },
            "delta": ["The appointee must be fluent in Cantonese and Putonghua."],
        },
    }
    text = _board(
        tmp_path,
        [_row("260901001", "Senior Project Fellow (Full-time)", 1, 80.78)],
        jd_parsed=shared,
        post_jds=post_jds,
    )
    assert "The appointee must be fluent in Cantonese and Putonghua." in text
    assert (
        "Shared with the panel at the top of this page: Must Skills, Language Requirements." in text
    )
    # Only the shared panel's two groups are rendered; the post panel repeats neither.
    assert text.count("<div class='tag-group'>") == 2


# Only the groups a post does not share are printed, so nothing is hidden and nothing repeats.
def test_board_post_panel_keeps_the_group_it_does_not_share(tmp_path: Path) -> None:
    post_jds = {
        "Senior Project Fellow": {
            "jd_text": "Senior Project Fellow duties.",
            "jd_parsed": {
                "must_skills": [{"canonical_skill": "Python"}],
                "language_requirements": [{"language": "Cantonese", "is_mandatory": True}],
            },
            "delta": ["The appointee must be fluent in Cantonese."],
        },
    }
    text = _board(
        tmp_path,
        [_row("260901001", "Senior Project Fellow (Full-time)", 1, 80.78)],
        jd_parsed={"must_skills": [{"canonical_skill": "Python"}]},
        post_jds=post_jds,
    )
    assert "Shared with the panel at the top of this page: Must Skills." in text
    # The post's own language group is printed; the shared must group is not repeated.
    assert text.count("<div class='tag-group'>") == 2
    assert text.index("Language Requirements") < text.index("Shared with the panel")


# A post's group is compared on the requirements it states, not on the order they were ranked in.
def test_board_post_panel_ignores_pill_order_when_matching_the_shared_panel(tmp_path: Path) -> None:
    post_jds = {
        "Senior Project Fellow": {
            "jd_text": "Senior Project Fellow duties.",
            "jd_parsed": {
                "must_skills": [{"canonical_skill": "Tableau"}, {"canonical_skill": "Python"}]
            },
            "delta": ["The appointee must be fluent in Cantonese."],
        },
    }
    text = _board(
        tmp_path,
        [_row("260901001", "Senior Project Fellow (Full-time)", 1, 80.78)],
        jd_parsed={
            "must_skills": [{"canonical_skill": "Python"}, {"canonical_skill": "Tableau"}]
        },
        post_jds=post_jds,
    )
    assert "Shared with the panel at the top of this page: Must Skills." in text
    assert text.count("<div class='tag-group'>") == 1


# The shared panel keeps the whole advertisement text with the shared tags (FR-6.2).
def test_board_shared_panel_is_the_full_advertisement(tmp_path: Path) -> None:
    text = _board(
        tmp_path,
        _rows(),
        jd_text="Research Assistant\nPost title: Senior Project Fellow / Postdoctoral Fellow",
        jd_parsed={"must_skills": [{"canonical_skill": "Teamwork"}]},
        post_jds=_post_jds(),
    )
    # The advertisement's own field survives, and its tags are the shared ones only.
    assert "<dt>Post title</dt><dd>Senior Project Fellow / Postdoctoral Fellow</dd>" in text
    assert "Teamwork" in text
    assert "Project Management" in text
    # The shared panel is rendered once, outside every section.
    assert text.count("Job Description &amp; Parsed Requirements") == 1
    assert text.index("Teamwork") < text.index("<details class='post-section'")


# A post whose requirements are all shared has no delta, so its section says so (FR-4).
def test_board_post_without_delta_points_at_the_shared_panel(tmp_path: Path) -> None:
    rows = _rows() + [_row("260901005", "Research Assistant", 1, 71.0)]
    post_jds = dict(_post_jds())
    post_jds["Research Assistant"] = {"jd_text": None, "jd_parsed": None, "delta": []}
    text = _board(tmp_path, rows, post_jds=post_jds)
    assert text.count("This post adds no requirements of its own.") == 1
    assert "Requirements specific to this post" not in text.split("Research Assistant")[-1]


# An applicant whose post could not be read is listed for HR instead of being dropped (FR-7).
def test_board_lists_unplaced_rows_for_hr(tmp_path: Path) -> None:
    rows = _rows() + [_row("260901009", "", 0, 55.0)]
    text = _board(tmp_path, rows, post_jds=_post_jds())
    assert "Needs HR confirmation" in text
    assert "no post value on the records page" in text
    assert "260901009" in text
    # An unplaced row is never given a rank of its own.
    assert text.count("<td>1</td>") == 3


# A multi-post page where no applicant's post could be read still explains itself (FR-7).
def test_board_all_unplaced_still_explains_itself(tmp_path: Path) -> None:
    text = _board(tmp_path, [_row("260901009", "", 0, 55.0)], post_jds=_post_jds())
    assert "Needs HR confirmation" in text
    assert "<details class='post-section'" not in text


# Without post_jds the board keeps the original flat table, even when the rows carry a post.
# A single-post run numbers its rows 1..n, which is what the flat table must keep rendering.
def test_board_without_post_jds_is_unchanged(tmp_path: Path) -> None:
    flat = [
        _row("260901003", "Postdoctoral Fellow (Full-time)", 1, 90.83),
        _row("260901004", "Postdoctoral Fellow (Full-time)", 2, 84.95),
        _row("260901001", "Senior Project Fellow (Full-time)", 3, 80.78),
        _row("260901002", "Senior Project Fellow (Part-time)", 4, 62.1),
    ]
    text = _board(tmp_path, flat)
    assert "<details class='post-section'" not in text
    assert text.count("<table>") == 1
    for rank in ("1", "2", "3", "4"):
        assert f"<td>{rank}</td>" in text
    # One merged list: the flat board still ranks every row against every other row.
    assert text.count("<td>1</td>") == 1


# The candidate match page restates the post the applicant was scored against (FR-8).
def test_match_page_states_post_applied_for(tmp_path: Path) -> None:
    from report_gen.html_board import write_candidate_match_html

    out = tmp_path / "260901001.html"
    write_candidate_match_html(
        str(out),
        row=_row("260901001", "Senior Project Fellow (Full-time)", 1, 80.78),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
    )
    text = out.read_text(encoding="utf-8")
    assert "Post applied for: Senior Project Fellow (Full-time)" in text


# A single-post match page carries no post line, so its output is unchanged.
def test_match_page_omits_post_line_without_a_post(tmp_path: Path) -> None:
    from report_gen.html_board import write_candidate_match_html

    out = tmp_path / "260901001.html"
    write_candidate_match_html(
        str(out),
        row=_row("260901001", "", 1, 80.78),
        position_name="Research Assistant",
        report_date=datetime(2026, 1, 1),
    )
    assert "Post applied for" not in out.read_text(encoding="utf-8")


# post-jds.json is keyed by base name, so a variant label finds its post's JD and delta.
def test_read_post_jds_keys_by_base_name(tmp_path: Path) -> None:
    module = _import_report_cli()
    post_text = tmp_path / "jd-post-Senior_Project_Fellow.txt"
    post_text.write_text("Senior Project Fellow duties.", encoding="utf-8")
    post_json = tmp_path / "jd-post-Senior_Project_Fellow.json"
    post_json.write_text(
        json.dumps({"structured_data": {"must_skills": [{"canonical_skill": "Python"}]}}),
        encoding="utf-8",
    )
    payload = {
        "version": "post-jd-v1",
        "base": {"jd_json": str(tmp_path / "jd-parse.json"), "text": "base"},
        "unclaimed": [],
        "mentioned": [],
        "posts": [
            {
                "post": "Senior Project Fellow",
                "slug": "Senior_Project_Fellow",
                "jd_json": str(post_json),
                "jd_text": str(post_text),
                "delta": ["Fluent Cantonese is required."],
            },
            {"post": "Research Assistant", "slug": "Research_Assistant", "jd_json": None, "delta": []},
        ],
    }
    path = tmp_path / "post-jds.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    by_post = module._read_post_jds(str(path))
    assert set(by_post) == {"Senior Project Fellow", "Research Assistant"}
    assert by_post["Senior Project Fellow"]["delta"] == ["Fluent Cantonese is required."]
    assert by_post["Senior Project Fellow"]["jd_text"] == "Senior Project Fellow duties."
    # structured_data is unwrapped, matching every other JD reader in this CLI.
    assert by_post["Senior Project Fellow"]["jd_parsed"]["must_skills"] == [
        {"canonical_skill": "Python"}
    ]
    # A post with no delta of its own carries no parse and no delta.
    assert by_post["Research Assistant"] == {"jd_text": None, "jd_parsed": None, "delta": []}


# No post-jds.json means a single-post board, so the reader returns nothing.
def test_read_post_jds_absent_or_malformed_returns_none(tmp_path: Path) -> None:
    module = _import_report_cli()
    assert module._read_post_jds(None) is None
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    assert module._read_post_jds(str(broken)) is None
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"posts": []}), encoding="utf-8")
    assert module._read_post_jds(str(empty)) is None


# A records-page post the advertisement's title never mentions is shown above the sections, because
# it questions the split itself rather than one post's ranking (FR-3, FR-7). The label is printed as
# HR saw it on the page, which is the only thing they can check it against.
def test_board_warns_about_a_post_the_advertisement_never_names(tmp_path: Path) -> None:
    text = _board(
        tmp_path,
        _rows(),
        post_jds=_post_jds(),
        unmatched_posts=["Research Fellow"],
    )
    assert "aria-label='Post cross-check warning'" in text
    assert "Research Fellow" in text
    # A warning, not a block: every post still has its own ranked section.
    assert text.count("<details class='post-section'") == 3
    assert text.index("Post cross-check warning") < text.index("<details class='post-section'")


# The warning is absent whenever nothing disagrees, so its presence always means something.
def test_board_has_no_cross_check_warning_when_every_post_is_named(tmp_path: Path) -> None:
    for extra in ({}, {"unmatched_posts": []}, {"unmatched_posts": None}):
        text = _board(tmp_path, _rows(), post_jds=_post_jds(), **extra)
        assert "Post cross-check warning" not in text


# A single-post board has no post universe, so it can never carry the warning — the single-post page
# must stay byte-identical to what it was before the post dimension existed.
def test_single_post_board_never_warns_about_posts(tmp_path: Path) -> None:
    text = _board(tmp_path, [_row("260901001", "", 1, 80.78)], unmatched_posts=["Research Fellow"])
    assert "Post cross-check warning" not in text
