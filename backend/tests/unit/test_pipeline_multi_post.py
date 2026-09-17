"""Tests for multi-post scoring groups and cache keys (PRD-Multi_Post step 5)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

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
