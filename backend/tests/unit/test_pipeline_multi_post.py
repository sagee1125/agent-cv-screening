"""Tests for multi-post scoring groups, cache keys and the per-post grill (PRD steps 5-7)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SCRIPT = REPO_ROOT / ".codex" / "skills" / "pipeline" / "scripts" / "run_pipeline.py"


# Import the pipeline CLI module in-process, matching the other pipeline test modules.
def _import_pipeline() -> Any:
    sys.path.insert(0, str(PIPELINE_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("skill_pipeline_multi_post", PIPELINE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A slug must be usable as a file name: safe_pack_id leaves "Fellow__Full-time_", so runs collapse.
def test_post_slug_collapses_underscore_runs() -> None:
    from screening_core.post_jds import post_slug

    assert post_slug("Senior Project Fellow") == "Senior_Project_Fellow"
    assert post_slug("Senior Project Fellow (Full-time)") == "Senior_Project_Fellow_Full-time"
    assert post_slug("") == "post"


# Full-time and part-time variants of one post share one base name, in first-appearance order.
def test_base_names_of_dedupes_variants_but_keeps_order() -> None:
    from screening_core.post_jds import base_names_of

    labels = [
        "Senior Project Fellow (Full-time)",
        "Senior Project Fellow (Part-time)",
        "Postdoctoral Fellow (Full-time)",
    ]
    assert base_names_of(labels) == ["Senior Project Fellow", "Postdoctoral Fellow"]


# Each applicant is scored against their own post's JD; an unknown post falls back to the base.
def test_jd_sources_resolves_each_post_and_its_config_name(tmp_path: Path) -> None:
    module = _import_pipeline()
    base = tmp_path / "jd-parse.json"
    spf = tmp_path / "jd-post-Senior_Project_Fellow.json"
    sources = module.JdSources(
        default=base,
        base_names=["Senior Project Fellow"],
        by_post={"Senior Project Fellow": spf},
        multi_post=True,
    )
    assert sources.for_post("Senior Project Fellow (Full-time)") == spf
    assert sources.for_post("Senior Project Fellow (Part-time)") == spf
    assert sources.for_post("Unknown Post") == base
    assert sources.for_post(None) == base
    assert sources.config_name("Senior Project Fellow (Full-time)") == "config-Senior_Project_Fellow.json"
    assert sources.jd_paths == [base, spf]


# A single-post job keeps exactly one JD and the original config name, so it is unchanged.
def test_jd_sources_single_post_is_unchanged(tmp_path: Path) -> None:
    module = _import_pipeline()
    base = tmp_path / "jd-parse.json"
    sources = module.JdSources(default=base)
    assert sources.multi_post is False
    assert sources.for_post(None) == base
    assert sources.config_name(None) == "config.json"
    assert sources.jd_paths == [base]


# The post dimension comes from the post universe, never from whether any post had a delta:
# an advertisement whose requirements are all shared still ranks and renders per post.
def test_post_dimension_survives_when_no_post_has_a_delta(tmp_path: Path) -> None:
    module = _import_pipeline()
    sources = module.JdSources(default=tmp_path / "jd-parse.json", multi_post=True, base_names=["A", "B"])
    assert sources.multi_post is True
    assert sources.by_post == {}


# Rows are ranked inside their own post group; groups are never merged into one ordered list (FR-5).
def test_rank_rows_ranks_within_each_post_group() -> None:
    module = _import_pipeline()
    rows = [
        {"appno": "1", "post": "A", "total_score": 50.0},
        {"appno": "2", "post": "B", "total_score": 90.0},
        {"appno": "3", "post": "A", "total_score": 70.0},
    ]
    unassigned = module._rank_rows(rows, multi_post=True)
    assert unassigned == []
    ranked = {(r["post"], r["appno"]): r["rank"] for r in rows}
    # B's only applicant is rank 1 even though A holds a higher-scoring pair overall.
    assert ranked[("A", "3")] == 1 and ranked[("A", "1")] == 2
    assert ranked[("B", "2")] == 1


# Ranking keeps the groups in the order their posts first appeared, because that order is what the
# board's sections follow — and the pipeline is handed the CVs in the records page's own order, so
# the sections come out in page order (FR-6.3).
def test_rank_rows_keeps_the_group_order_the_cvs_arrived_in() -> None:
    module = _import_pipeline()
    rows = [
        {"appno": "5", "post": "Research Associate", "total_score": 70.0},
        {"appno": "4", "post": "Research Assistant", "total_score": 90.0},
        {"appno": "3", "post": "Research Associate", "total_score": 50.0},
    ]
    module._rank_rows(rows, multi_post=True)
    # Groups in first-appearance order, members by score inside their own group.
    assert [(r["post"], r["appno"]) for r in rows] == [
        ("Research Associate", "5"),
        ("Research Associate", "3"),
        ("Research Assistant", "4"),
    ]


# A blank post value cannot be placed and must be reported, never guessed at (FR-7).
def test_rank_rows_returns_rows_with_no_post() -> None:
    module = _import_pipeline()
    rows = [
        {"appno": "1", "post": "A", "total_score": 50.0},
        {"appno": "2", "post": "", "total_score": 99.0},
    ]
    unassigned = module._rank_rows(rows, multi_post=True)
    assert [r["appno"] for r in unassigned] == ["2"]
    assert [r["appno"] for r in rows] == ["1"]


# A single-post job keeps one ranking over every row, exactly as it always has.
def test_rank_rows_single_post_keeps_one_ranking() -> None:
    module = _import_pipeline()
    rows = [
        {"appno": "1", "post": None, "total_score": 50.0},
        {"appno": "2", "post": None, "total_score": 90.0},
    ]
    assert module._rank_rows(rows, multi_post=False) == []
    assert [(r["appno"], r["rank"]) for r in rows] == [("2", 1), ("1", 2)]


# The post universe is the distinct labels in first-appearance order, first spelling wins (FR-3).
def test_post_labels_dedupes_case_insensitively() -> None:
    module = _import_pipeline()

    class _Args:
        cv_post = ["1=Senior Fellow", "2=senior fellow", "3=Junior Fellow", "4="]

    assert module._post_labels(_Args()) == ["Senior Fellow", "Junior Fellow"]
    assert module._post_map(_Args()) == {"1": "Senior Fellow", "2": "senior fellow", "3": "Junior Fellow"}


# A board command needs a stand-in args namespace, a row, and a report folder (PRD step 6).
def _report_args(report_dir: Path) -> Any:
    import argparse

    return argparse.Namespace(
        skip_reports=False,
        position="Research Assistant",
        engine="legacy",
        refno="260901004",
        max_retries=0,
        fail_fast=False,
        report_dir=str(report_dir),
    )


# One candidate row plus the cached score files a board render reads.
def _report_row(tmp_path: Path) -> dict:
    extracted = tmp_path / "extracted-123456.json"
    extracted.write_text('{"structured_data": {}}', encoding="utf-8")
    score = tmp_path / "score-123456.json"
    score.write_text('{"total_score": 80}', encoding="utf-8")
    return {
        "rank": 1,
        "refno": "260901004",
        "appno": "123456",
        "post": "Senior Project Fellow (Full-time)",
        "display_label": "260901004/123456",
        "total_score": 80,
        "tier": "Tier 2",
        "_extracted": extracted,
        "_score": score,
        "_source": "123456.pdf",
    }


# A multi-post run must hand the board its post-jds.json, or the board cannot section by post.
def test_generate_reports_passes_post_jds_to_the_board(tmp_path: Path, monkeypatch: Any) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "pipeline"
    out_dir.mkdir()
    (out_dir / "post-jds.json").write_text('{"posts": []}', encoding="utf-8")
    commands: list[list[str]] = []

    # Record every board command instead of shelling out to the skill CLIs.
    def fake_retries(cmd: list[str], _max_retries: int) -> tuple[int, None]:
        commands.append(list(cmd))
        if cmd[2] == "board":
            output = Path(cmd[cmd.index("--output") + 1])
            output.write_text("<html></html>", encoding="utf-8")
        else:
            output = Path(cmd[cmd.index("--output") + 1])
            output.write_bytes(b"%PDF-fake" if output.suffix == ".pdf" else b"<html></html>")
        return 1, None

    monkeypatch.setattr(module, "_run_with_retries", fake_retries)
    sources = module.JdSources(default=out_dir / "jd-parse.json", multi_post=True)
    module._generate_reports(
        _report_args(tmp_path / "reports"), out_dir, [_report_row(tmp_path)], [], jd_sources=sources
    )
    board = next(cmd for cmd in commands if cmd[2] == "board")
    assert board[board.index("--post-jds") + 1] == str(out_dir / "post-jds.json")


# A multi-post run without post-jds.json must not fall back to one merged ranking (FR-5).
def test_generate_reports_refuses_a_multi_post_board_without_post_jds(
    tmp_path: Path, monkeypatch: Any
) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "pipeline"
    out_dir.mkdir()
    commands: list[list[str]] = []

    # Record every command so the test can prove no board was rendered.
    def fake_retries(cmd: list[str], _max_retries: int) -> tuple[int, None]:
        commands.append(list(cmd))
        output = Path(cmd[cmd.index("--output") + 1])
        output.write_bytes(b"%PDF-fake" if output.suffix == ".pdf" else b"<html></html>")
        return 1, None

    monkeypatch.setattr(module, "_run_with_retries", fake_retries)
    sources = module.JdSources(default=out_dir / "jd-parse.json", multi_post=True)
    failures: list = []
    reports = module._generate_reports(
        _report_args(tmp_path / "reports"), out_dir, [_report_row(tmp_path)], failures, jd_sources=sources
    )
    assert "board" not in [cmd[2] for cmd in commands]
    assert "ranking_overview_html" not in reports
    assert len(failures) == 1
    assert "post-jds.json" in failures[0].error_message


# An applicant whose post could not be read still reaches the board, so FR-7 can list it.
def test_generate_reports_hands_unplaced_rows_to_the_board(tmp_path: Path, monkeypatch: Any) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "pipeline"
    out_dir.mkdir()
    (out_dir / "post-jds.json").write_text('{"posts": []}', encoding="utf-8")

    # Write the report files the board command is expected to produce.
    def fake_retries(cmd: list[str], _max_retries: int) -> tuple[int, None]:
        output = Path(cmd[cmd.index("--output") + 1])
        output.write_bytes(b"%PDF-fake" if output.suffix == ".pdf" else b"<html></html>")
        return 1, None

    monkeypatch.setattr(module, "_run_with_retries", fake_retries)
    sources = module.JdSources(default=out_dir / "jd-parse.json", multi_post=True)
    ranked = _report_row(tmp_path)
    unplaced = dict(ranked, appno="999999", post="", rank=None)
    module._generate_reports(
        _report_args(tmp_path / "reports"),
        out_dir,
        [ranked],
        [],
        jd_sources=sources,
        unassigned=[unplaced],
    )
    board_rows = json.loads((out_dir / "rows.json").read_text(encoding="utf-8"))
    assert [row["appno"] for row in board_rows] == ["123456", "999999"]
    assert board_rows[1]["post"] == ""


# --- The per-post derivation gate (FR-9) ----------------------------------------------------

# The two posts of one advertisement, with the sentence each was read from.
_GATE_DELTAS = {"Research Assistant": ["Applicants for the Research Assistant post need honours."]}
# Two labels for one post: the item must name both variants, because HR answers once for both.
_GATE_LABELS = ["Research Assistant (Full-time)", "Research Assistant (Part-time)"]


# Write a jd-overrides.yaml carrying HR's per-post confirmation of the derived deltas.
def _confirm_posts(out_dir: Path, deltas: dict[str, list[str]]) -> None:
    lines = ["collected_at: '2026-09-17'", "posts:"]
    for name, sentences in deltas.items():
        lines.append(f"  - post: {name}")
        lines.append("    confirmed: true")
        lines.append("    delta:")
        for sentence in sentences:
            lines.append("      - " + json.dumps(sentence))
    (out_dir / "jd-overrides.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


# An unconfirmed derivation stops the run before anything is parsed, carrying one item per post.
def test_gate_stops_for_unconfirmed_post_deltas(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(module.NeedInputError) as excinfo:
        module._require_conditions_decision(
            argparse.Namespace(), out_dir, post_deltas=_GATE_DELTAS, post_labels=_GATE_LABELS
        )

    error = excinfo.value
    assert error.status == "conditions_pending"
    assert error.missing == ["conditions"]
    items = error.details["post_deltas"]
    assert [item["post"] for item in items] == ["Research Assistant"]
    # One item covers both variants, and it carries the source sentence HR must check.
    assert items[0]["labels"] == _GATE_LABELS
    assert items[0]["delta"] == _GATE_DELTAS["Research Assistant"]
    assert items[0]["confirmed"] is False
    # No conditions file exists, so nothing about stored conditions is asked.
    assert "conditions" not in error.details


# Once HR has confirmed every post, the run has nothing left to stop for.
def test_gate_passes_when_every_post_is_confirmed(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _confirm_posts(out_dir, _GATE_DELTAS)

    # No raise: the derivation is settled and there are no stored conditions.
    module._require_conditions_decision(
        argparse.Namespace(), out_dir, post_deltas=_GATE_DELTAS, post_labels=_GATE_LABELS
    )


# A partially confirmed run asks only about the posts HR has not answered yet.
def test_gate_asks_only_about_the_unconfirmed_post(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    deltas = dict(_GATE_DELTAS, **{"Research Associate": ["The Research Associate post needs a PhD."]})
    _confirm_posts(out_dir, _GATE_DELTAS)

    with pytest.raises(module.NeedInputError) as excinfo:
        module._require_conditions_decision(
            argparse.Namespace(), out_dir, post_deltas=deltas, post_labels=_GATE_LABELS
        )

    assert [item["post"] for item in excinfo.value.details["post_deltas"]] == ["Research Associate"]


# HR's explicit answer settles the question, so the run proceeds without asking again.
def test_gate_passes_on_an_explicit_hr_answer(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    for flag in ("_conditions_confirmed", "_discard_conditions"):
        module._require_conditions_decision(
            argparse.Namespace(**{flag: True}),
            out_dir,
            post_deltas=_GATE_DELTAS,
            post_labels=_GATE_LABELS,
        )


# A single-post run has no derivation to confirm, so the gate stays silent for it.
def test_gate_is_silent_without_a_post_dimension(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    module._require_conditions_decision(argparse.Namespace(), out_dir)


# Only the posts that have a delta of their own are items: a shared-requirements post asks nothing.
def test_post_deltas_keeps_only_the_posts_with_their_own_requirements() -> None:
    module = _import_pipeline()

    class _Split:
        def delta_for(self, name: str) -> list[str]:
            return ["only this post"] if name == "A" else []

    assert module._post_deltas(_Split(), ["A", "B"]) == {"A": ["only this post"]}


# A file holding only the per-post confirmation is not a conditions file: there is nothing for HR
# to read back, so the run must not stop to ask about conditions that do not exist.
def test_gate_does_not_ask_about_conditions_when_the_file_holds_only_confirmations(
    tmp_path: Path,
) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _confirm_posts(out_dir, _GATE_DELTAS)

    # describe_overrides must report nothing to reuse, so no conditions question is raised.
    # The file is readable and does hold the confirmations, so this is not a parse failure.
    assert module.load_overrides(out_dir) is not None
    assert module.describe_overrides(out_dir) is None
    module._require_conditions_decision(
        argparse.Namespace(), out_dir, post_deltas=_GATE_DELTAS, post_labels=_GATE_LABELS
    )


# A stored degree gate is still a condition HR must be asked about, so the check is not narrowed
# to the skill lists alone.
def test_gate_still_asks_when_the_file_holds_only_an_eligibility_rule(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "jd-overrides.yaml").write_text(
        """eligibility_rules:
  - rule: minimum_degree
    value: master
""",
        encoding="utf-8",
    )
    # A file the loader cannot read would make this test pass for the wrong reason.
    assert module.load_overrides(out_dir) is not None

    with pytest.raises(module.NeedInputError) as excinfo:
        module._require_conditions_decision(argparse.Namespace(), out_dir)

    assert excinfo.value.details["conditions"] is not None


# A conditions file the gate cannot read must stop the run, never be read as "no conditions": the
# ranking would otherwise be scored against the job ad alone while HR believes her conditions are
# in force. The way past this is --conditions discard, which is HR's answer, not our inference.
def test_gate_propagates_an_unreadable_conditions_file(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "jd-overrides.yaml").write_text("must_skills: [Python\n", encoding="utf-8")

    with pytest.raises(module.OverridesUnreadableError) as excinfo:
        module._require_conditions_decision(argparse.Namespace(), out_dir)

    assert "jd-overrides.yaml" in str(excinfo.value)


# An explicit HR answer releases the run even when the file cannot be read, because "screen against
# the job ad alone" is exactly what discard means.
def test_gate_lets_an_explicit_discard_past_an_unreadable_file(tmp_path: Path) -> None:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "jd-overrides.yaml").write_text("must_skills: [Python\n", encoding="utf-8")

    module._require_conditions_decision(
        argparse.Namespace(_discard_conditions=True), out_dir
    )


# Builds a two-applicant, two-post out_dir plus the args a re-run would pass.
def _resync_fixture(tmp_path: Path) -> tuple[Path, dict, Any]:
    module = _import_pipeline()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    jd = tmp_path / "jd.txt"
    jd.write_text("role A", encoding="utf-8")
    cvs = {}
    for appno in ("260907001", "260907002"):
        path = tmp_path / f"{appno}.pdf"
        path.write_bytes(b"%PDF-1.4 " + appno.encode())
        cvs[appno] = path
        for prefix in ("extracted-", "score-", "detail-"):
            (out_dir / f"{prefix}{appno}.json").write_text("{}", encoding="utf-8")
    (out_dir / "jd-parse.json").write_text("{}", encoding="utf-8")

    def args_for(posts: dict[str, str]) -> argparse.Namespace:
        return argparse.Namespace(
            resume=True,
            engine="matching",
            position="PA",
            refno="1",
            jd_file=str(jd),
            jd_json=None,
            cv=[str(p) for p in cvs.values()],
            extracted=[],
            cv_post=[f"{appno}={label}" for appno, label in posts.items()],
        )

    return out_dir, {"args_for": args_for, "cvs": cvs}, module


# FR-10, at the level that actually matters: when one applicant changes post, the other group's
# artifacts must survive untouched. Asserting only that the moved applicant was rebuilt would pass
# even if every CV in every group had been re-parsed, which is the bug FR-10 exists to remove.
def test_resync_keeps_the_untouched_group_cached(tmp_path: Path) -> None:
    out_dir, fixture, module = _resync_fixture(tmp_path)
    args_for = fixture["args_for"]
    before = {"260907001": "Research Assistant", "260907002": "Research Associate"}

    # A first run establishes the baseline fingerprint.
    first = args_for(before)
    module._sync_resume_with_inputs(first, out_dir)
    module._persist_fingerprints(out_dir, first)

    # A re-run finds one applicant moved to the other post; the advertisement is unchanged.
    moved = args_for({"260907001": "Research Assistant", "260907002": "Research Assistant"})
    module._sync_resume_with_inputs(moved, out_dir)

    # The run still resumes, so nothing is re-parsed wholesale and the JD parse survives.
    assert moved.resume is True
    assert (out_dir / "jd-parse.json").is_file()
    # The moved applicant keeps their parsed CV but loses the score computed against the old post.
    assert (out_dir / "extracted-260907002.json").is_file()
    assert not (out_dir / "score-260907002.json").exists()
    assert not (out_dir / "detail-260907002.json").exists()
    # The untouched group is left completely alone.
    assert (out_dir / "extracted-260907001.json").is_file()
    assert (out_dir / "score-260907001.json").is_file()
    assert (out_dir / "detail-260907001.json").is_file()


# The other FR-10 trigger: a replaced CV rebuilds that applicant only. Their score goes with it,
# and the group that did not change keeps every artifact.
def test_resync_rebuilds_only_the_replaced_cv(tmp_path: Path) -> None:
    out_dir, fixture, module = _resync_fixture(tmp_path)
    args_for = fixture["args_for"]
    posts = {"260907001": "Research Assistant", "260907002": "Research Associate"}

    first = args_for(posts)
    module._sync_resume_with_inputs(first, out_dir)
    module._persist_fingerprints(out_dir, first)

    fixture["cvs"]["260907002"].write_bytes(b"%PDF-1.4 revised")
    second = args_for(posts)
    module._sync_resume_with_inputs(second, out_dir)

    assert second.resume is True
    assert (out_dir / "jd-parse.json").is_file()
    assert not (out_dir / "extracted-260907002.json").exists()
    assert not (out_dir / "score-260907002.json").exists()
    assert (out_dir / "extracted-260907001.json").is_file()
    assert (out_dir / "score-260907001.json").is_file()
    assert (out_dir / "detail-260907001.json").is_file()


# A changed advertisement still invalidates everything: a post's requirements can move between
# posts when the ad is rewritten, so FR-10's "only one group changed" does not apply.
def test_resync_still_rebuilds_everything_when_the_ad_changes(tmp_path: Path) -> None:
    out_dir, fixture, module = _resync_fixture(tmp_path)
    args_for = fixture["args_for"]
    posts = {"260907001": "Research Assistant", "260907002": "Research Associate"}

    first = args_for(posts)
    module._sync_resume_with_inputs(first, out_dir)
    module._persist_fingerprints(out_dir, first)

    Path(first.jd_file).write_text("role A, revised", encoding="utf-8")
    second = args_for(posts)
    module._sync_resume_with_inputs(second, out_dir)

    # Resume off is the guarantee that matters: every reuse site is gated on `args.resume and
    # _is_usable_json(...)`, so the surviving score files below are inert rather than reused.
    assert second.resume is False
    assert not (out_dir / "jd-parse.json").exists()


# post-jds.json records the requirements an unclaimed post was attributed, because those sentences
# are excluded from the base and then appear in no rendered artifact: without this the run would
# drop a requirement and nothing HR can read would say which one (FR-3, FR-4).
def test_post_jd_payload_records_what_an_unclaimed_post_lost() -> None:
    from screening_core.post_jds import post_jd_payload

    payload = post_jd_payload(
        base_jd_json="/tmp/jd-parse.json",
        base_text="shared bullet",
        posts=[
            {
                "post": "Research Assistant",
                "slug": "Research_Assistant",
                "jd_json": None,
                "delta": [],
            }
        ],
        mentioned=["Research Assistant"],
        unclaimed=["Research Fellow"],
        unclaimed_sentences={
            "Research Fellow": ["Applicants for the Research Fellow post need a PhD."]
        },
    )

    assert payload["unclaimed"] == ["Research Fellow"]
    assert payload["unclaimed_sentences"] == {
        "Research Fellow": ["Applicants for the Research Fellow post need a PhD."]
    }
    # `mentioned` stays scoped to the post universe, so HR is never asked to confirm a derivation
    # for a post that has no section.
    assert payload["mentioned"] == ["Research Assistant"]
    # Always present, so a reader never has to tell "none were dropped" from "not recorded".
    assert (
        post_jd_payload(base_jd_json="/tmp/jd-parse.json", base_text="shared", posts=[])[
            "unclaimed_sentences"
        ]
        == {}
    )
