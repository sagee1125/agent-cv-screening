"""Unit tests for the screen-job runner aggregation helpers (no network / LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = REPO_ROOT / ".codex/agents/cv-screening-agent/scripts"
sys.path.insert(0, str(RUNNER_DIR))

import run_screen_job as runner  # noqa: E402


def test_cv_stem_normalizes_filename() -> None:
    assert runner.cv_stem(Path("Alice Chen Resume.PDF")) == "alice_chen_resume"


def test_build_rank_items_reads_total_score(tmp_path: Path) -> None:
    score_path = tmp_path / "alice.score.json"
    score_path.write_text(
        json.dumps({"total_score": 58.7, "tier": "Tier 3"}),
        encoding="utf-8",
    )
    items = runner.build_rank_items([score_path])
    assert items == [{"candidate_id": "alice", "total_score": 58.7}]


def test_build_comparison_rows_maps_fields(tmp_path: Path) -> None:
    workspace = tmp_path
    (workspace / "scores").mkdir()
    (workspace / "cvs").mkdir()
    ranking = {
        "score": {},
        "ranking": [{"candidate_id": "alice", "total_score": 58.7, "rank": 1}],
    }
    (workspace / "scores" / "ranking.json").write_text(json.dumps(ranking), encoding="utf-8")
    (workspace / "scores" / "alice.score.json").write_text(
        json.dumps(
            {
                "total_score": 58.7,
                "tier": "Tier 3",
                "dimension_scores": {
                    "skill_match": 86.5,
                    "experience_match": 0.0,
                    "education_match": 100.0,
                    "research_quality": 30.0,
                },
                "full_snapshot": {
                    "interview_suggestions": [
                        {"rule_id": "LOW-EXPERIENCE_MATCH", "severity": "high"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (workspace / "cvs" / "alice.extracted.json").write_text(
        json.dumps({"structured_data": {"name": "Alice Chen"}}),
        encoding="utf-8",
    )
    rows = runner.build_comparison_rows(ranking_path=workspace / "scores" / "ranking.json", workspace=workspace)
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice Chen"
    assert rows[0]["rank"] == 1
    assert rows[0]["skill_match"] == 86.5
    assert "LOW-EXPERIENCE_MATCH:high" in rows[0]["suggestion_summary"]


def test_jd_only_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """JD file → parse → build-config without CVs (--jd-only)."""
    workspace = tmp_path / "demo"
    jd_file = REPO_ROOT / ".codex/skills/jd-parser/examples/sample-jd.txt"
    argv = [
        "run_screen_job.py",
        "--workspace",
        str(workspace),
        "--job-source",
        "jd_file",
        "--jd-file",
        str(jd_file),
        "--position-title",
        "Backend Engineer",
        "--yes",
        "--jd-only",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert runner.main() == 0
    assert (workspace / "jd.structured.json").exists()
    assert (workspace / "scoring.config.json").exists()
    config = json.loads((workspace / "scoring.config.json").read_text(encoding="utf-8"))
    assert config.get("required_skills")
