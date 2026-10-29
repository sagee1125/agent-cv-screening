# Every application absent from the ranking must be visible to HR with a
# reason: parse failures and JAS's no-CV list flow into one board note.
import json
from pathlib import Path

def test_collect_unparsed_note_merges_failures_and_no_cv(tmp_path) -> None:
    import importlib.util
    import sys

    scripts = Path(__file__).resolve().parents[3] / ".codex" / "skills" / "pipeline" / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("rp_note", scripts / "run_pipeline.py")
    rp = importlib.util.module_from_spec(spec)
    sys.modules["rp_note"] = rp
    spec.loader.exec_module(rp)

    (tmp_path / "jas-manifest.json").write_text(
        json.dumps({"candidates_without_cv": ["300001"]}), encoding="utf-8"
    )
    failures = [
        rp.Failure(
            source="C:/x/300885.pdf",
            stage="cv-parse",
            attempts=1,
            error_message="Could not convert this .doc file to PDF locally. word com failed",
        ),
        rp.Failure(source="C:/x/300885.pdf", stage="score", attempts=1, error_message="ignored"),
    ]
    lines = rp._collect_unparsed_note(tmp_path, failures)
    assert len(lines) == 2
    assert "300885" in lines[0] and "Could not convert" in lines[0]
    assert "300001" in lines[1] and "no CV" in lines[1]


def test_board_renders_unparsed_note(tmp_path) -> None:
    from datetime import datetime

    from report_gen.html_board import write_screening_board

    out = tmp_path / "board.html"
    write_screening_board(
        str(out),
        position_name="Test",
        rows=[],
        report_date=datetime(2026, 1, 1),
        unparsed_note=[
            "Application No. 300885 - not scored: Could not convert this .doc file",
            "Application No. 300001 - no CV was submitted, so there is nothing to score",
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "Applicants not in this ranking" in text
    assert "300885" in text and "300001" in text
    # Empty note renders nothing.
    empty = tmp_path / "empty.html"
    write_screening_board(
        str(empty), position_name="T", rows=[], report_date=datetime(2026, 1, 1), unparsed_note=[]
    )
    assert "Applicants not in this ranking" not in empty.read_text(encoding="utf-8")
