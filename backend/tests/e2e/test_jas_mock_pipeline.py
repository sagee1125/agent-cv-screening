# End-to-end tests for the JAS mock data: generate, parse, and screen.
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# backend/tests/e2e/test_jas_mock_pipeline.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
SCREENING_SCRIPT = SKILLS_DIR / "jas-import" / "scripts" / "run_jas_screening.py"
IMPORT_SCRIPT = SKILLS_DIR / "jas-import" / "scripts" / "run_jas_import.py"

from cv_parser.service import PARSER_CACHE_VERSION  # noqa: E402
from jas_import.mock import MOCK_REFNO, generate_mock_jas_dir  # noqa: E402
from jas_import.skill import parse_job_skill, parse_list_skill  # noqa: E402


def _import_screening_module():
    """Import the offline JAS screening CLI module in-process."""
    sys.path.insert(0, str(SCREENING_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_jas_screening", SCREENING_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _screening_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    """Build the screening orchestrator Namespace with defaults."""
    values = {
        "records_html": None,
        "cvs_dir": None,
        "cv": [],
        "output_dir": str(tmp_path / "out"),
        # A screening run records job state under the refno it screened. Left unset that defaults to
        # the repo's data/jas_state, so a test run overwrites the developer's real snapshot for
        # whatever refno the mock uses (found 2026-09-18: the real 260818001 snapshot was replaced by
        # mock applicants and 100 mock history entries). Every test gets its own state dir instead,
        # and test_mock_screening_never_writes_the_repo_state_dir holds that guarantee in place.
        "state_dir": str(tmp_path / "state"),
        "engine": "legacy",
        "max_retries": 2,
        "skip_reports": False,
        "no_open": True,
        "resume": False,
        "fail_fast": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


# The generator writes the full mock JAS folder.
def test_generate_mock_dir(tmp_path) -> None:
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    assert (jas_dir / "records.html").is_file()
    assert (jas_dir / "list.html").is_file()
    assert (jas_dir / "cvs" / "123456.pdf").is_file()
    assert (jas_dir / "cvs" / "654321.pdf").is_file()
    assert (jas_dir / "README.txt").is_file()


# The mock HTML parses into JD text and appno-keyed candidate references.
def test_parse_mock_list_and_job(tmp_path) -> None:
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")

    list_payload = parse_list_skill(jas_dir / "list.html")
    assert list_payload["status"] == "success"
    assert list_payload["items"][0]["refno"] == MOCK_REFNO
    assert list_payload["items"][0]["post_title"] == "Project Associate"

    job_payload = parse_job_skill(jas_dir / "records.html")
    assert job_payload["status"] == "success"
    assert job_payload["refno"] == MOCK_REFNO
    assert job_payload["job"]["post_title"] == "Project Associate"
    assert "Python" in job_payload["jd_text"]
    assert "SQL" in job_payload["jd_text"]

    candidates = job_payload["candidates"]
    assert [candidate["appno"] for candidate in candidates] == ["123456", "654321"]
    assert candidates[0]["status"] == "S"
    assert candidates[1]["status"] == "TBC"
    assert candidates[0]["cv_url"].endswith(f"file.php?t=cv&id=123456&refno={MOCK_REFNO}")


# The offline orchestrator delegates to the pipeline with CVs in appno order.
def test_screening_orchestration_ranks_mock(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    captured_cmd: list[list[str]] = []

    def fake_run_pipeline(cmd):
        captured_cmd.append(cmd)
        return 0, {
            "status": "success",
            "candidates": [
                {"rank": 1, "appno": "123456", "refno": MOCK_REFNO, "total_score": 45.31},
                {"rank": 2, "appno": "654321", "refno": MOCK_REFNO, "total_score": 0.0},
            ],
        }

    monkeypatch.setattr(module, "_run_pipeline", fake_run_pipeline)
    exit_code = module.run_jas_screening(jas_dir, _screening_args(tmp_path, engine="matching"))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    assert captured_cmd, "pipeline was not invoked"
    cmd = captured_cmd[0]
    assert "--position" in cmd and "Project Associate" in cmd
    assert any("123456.pdf" in token for token in cmd)
    assert any("654321.pdf" in token for token in cmd)

    out_dir = tmp_path / "out"
    manifest = json.loads(
        (out_dir / MOCK_REFNO / "_pipeline" / "jas-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["refno"] == MOCK_REFNO
    assert [candidate["appno"] for candidate in manifest["candidates"]] == ["123456", "654321"]
    assert manifest["candidates_without_cv"] == []


# Optional live end-to-end run (JD parse + CV parse via LLM + matching ranking).
@pytest.mark.skipif(
    "JAS_MOCK_E2E" not in os.environ,
    reason="set JAS_MOCK_E2E=1 to run the live-LLM end-to-end ranking test",
)
def test_real_e2e_ranking(tmp_path) -> None:
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCREENING_SCRIPT),
            "--jas-dir",
            str(jas_dir),
            "--output-dir",
            str(out_dir),
            "--engine",
            "matching",
            # Same reason as _screening_args: never let a test run write the repo's job state.
            "--state-dir",
            str(tmp_path / "state"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "success"
    ranks = payload["candidates"]
    assert len(ranks) == 2
    assert ranks[0]["appno"] == "123456"
    assert ranks[1]["appno"] == "654321"
    assert "name" not in ranks[0]
    assert ranks[0]["total_score"] > ranks[1]["total_score"]
    job_dir = out_dir / MOCK_REFNO
    assert (job_dir / "ranking-overview.html").is_file()
    assert (job_dir / "123456.html").is_file()
    assert (job_dir / "_pipeline" / "jas-manifest.json").is_file()


# A mock run must never write the repo's job-state directory.
#
# A state file is the baseline the update check diffs a real job against, so a mock run that writes
# under a real refno destroys it silently: the real 260818001 snapshot was replaced by the mock
# applicants and 100 mock history entries before this was found (2026-09-18). Two things now prevent
# that — MOCK_REFNO is a refno no real job can have, and every test passes its own state_dir — and
# this test holds both: it runs the mock flow the way the tests run it and then requires the repo
# state dir to be untouched, while still seeing the run record its state in the isolated dir.
def test_mock_screening_never_writes_the_repo_state_dir(tmp_path, monkeypatch, capsys) -> None:
    module = _import_screening_module()
    jas_dir = generate_mock_jas_dir(tmp_path / "jas")
    repo_state = REPO_ROOT / "data" / "jas_state"
    before = {path.name: path.stat().st_mtime_ns for path in repo_state.glob("*.json")}

    monkeypatch.setattr(
        module,
        "_run_pipeline",
        lambda cmd: (
            0,
            {
                "status": "success",
                "candidates": [
                    {"rank": 1, "appno": "123456", "refno": MOCK_REFNO, "total_score": 45.31},
                    {"rank": 2, "appno": "654321", "refno": MOCK_REFNO, "total_score": 0.0},
                ],
            },
        ),
    )
    exit_code = module.run_jas_screening(jas_dir, _screening_args(tmp_path))
    capsys.readouterr()

    assert exit_code == module.EXIT_OK
    after = {path.name: path.stat().st_mtime_ns for path in repo_state.glob("*.json")}
    assert after == before, "the mock run added or rewrote a file in the repo job-state dir"
    # Positive control: the run did record its state, just in the dir it was handed.
    assert (tmp_path / "state" / f"{MOCK_REFNO}.json").is_file(), "the run recorded no state at all"


# ---------------------------------------------------------------------------------------------
# The Integration row of the PRD's test plan (docs/PRD-Multi_Post_v1.0.md §9): "a multi-post
# fixture runs the full wrapper chain and produces one report with the expected per-post counts".
# ---------------------------------------------------------------------------------------------

# The cv-parser output for the two fixture CVs, keyed by application number.
#
# The row under test is the multi-post wiring — the page's `Post applied for` column, the post
# universe, the per-post JD and the per-post report — not CV understanding, so the parser's answer
# is supplied instead of inferred. These are the facts the mock CVs actually state (mock.py's own
# `_MOCK_PROFILES`), written in the shape a real cache entry holds, and they are the keys the scorer
# reads: `skills[].canonical_skill`, `education`, `experience`, `languages`. `name`/`email`/`phone`
# are null on purpose — the fixture then also proves no artifact needs a candidate's identity.
_OFFLINE_CV_PROFILES: dict[str, dict] = {
    "123456": {
        "name": None,
        "email": None,
        "phone": None,
        "location": {"raw": "", "country": "", "city": "", "region": None},
        "work_authorization": {"status": "unknown", "raw": None},
        "summary": (
            "Data analyst with 4 years of experience in data analytics, data governance and "
            "business intelligence."
        ),
        "education": [
            {
                "school": "The Hong Kong Polytechnic University",
                "degree": "MSc",
                "degree_level": "master",
                "major": "Data Science",
                "period": "2020 - 2022",
                "start_date": "2020",
                "end_date": "2022",
                "graduation_date": "2022",
            }
        ],
        "experience": [
            {
                "company": "ABC Data Services Limited",
                "job_title": "Data Analyst",
                "period": "Sep 2024 - Present",
                "start_date": "2024-09",
                "end_date": None,
                "is_current": True,
                "description": (
                    "Built ETL pipelines in Python and SQL; developed Power BI dashboards; "
                    "implemented data quality checks and data governance documentation."
                ),
                "skills_used": ["Python", "SQL", "Power BI", "ETL", "Data Governance"],
            }
        ],
        "skills": [
            {"raw": skill, "canonical_skill": skill, "skill_id": "", "source": "cv"}
            for skill in (
                "Python",
                "SQL",
                "Power BI",
                "Tableau",
                "Excel",
                "Data Governance",
                "ETL",
                "Statistics",
            )
        ],
        "languages": [{"language": "English", "level": "fluent"}, {"language": "Chinese", "level": "fluent"}],
        "certifications": [],
        "projects": [],
        "publications": [],
    },
    "654321": {
        "name": None,
        "email": None,
        "phone": None,
        "location": {"raw": "", "country": "", "city": "", "region": None},
        "work_authorization": {"status": "unknown", "raw": None},
        "summary": "Administrative assistant with 2 years of experience in office administration.",
        "education": [
            {
                "school": "City University of Hong Kong",
                "degree": "BA",
                "degree_level": "bachelor",
                "major": "Business Administration",
                "period": "2018 - 2022",
                "start_date": "2018",
                "end_date": "2022",
                "graduation_date": "2022",
            }
        ],
        "experience": [
            {
                "company": "DEF Group Limited",
                "job_title": "Administrative Assistant",
                "period": "Jan 2024 - Present",
                "start_date": "2024-01",
                "end_date": None,
                "is_current": True,
                "description": "Maintained office records and databases; prepared reports and presentations.",
                "skills_used": ["Excel", "Word", "Document Management"],
            }
        ],
        "skills": [
            {"raw": skill, "canonical_skill": skill, "skill_id": "", "source": "cv"}
            for skill in ("Excel", "Word", "PowerPoint", "Outlook", "Document Management")
        ],
        "languages": [{"language": "English", "level": "fluent"}, {"language": "Chinese", "level": "fluent"}],
        "certifications": [],
        "projects": [],
        "publications": [],
    },
}

# Every string the fixture's records page carries that must never reach an artifact (§13.5.4).
_MOCK_PII_TOKENS = (
    "CHAN Tai Man",
    "LEE Wai Yan",
    "chan.taiman@example.com",
    "lee.waiyan@example.com",
    "6123 4567",
    "9876 5432",
    "A123",
    "B456",
    "28,000",
    "32,000",
    "18,000",
    "22,000",
)


# Seed the cv-parser hash cache for every fixture CV, so no parser call reaches the network.
#
# The key is the PDF's own md5 plus the parser cache version — the key the service builds — and it
# is computed here rather than hardcoded because the mock PDFs embed a creation timestamp: their
# bytes, and therefore the key, change on every generation. That also means a stale entry can never
# be picked up by accident, and that this fixture can never collide with the repo's real cache.
def _seed_cv_cache(cache_dir: Path, jas_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted((jas_dir / "cvs").glob("*.pdf"))
    # Fail loudly rather than fall through to the network if the fixture ever gains a third CV.
    assert {pdf.stem for pdf in pdfs} == set(_OFFLINE_CV_PROFILES), (
        "the multi-post fixture has a CV the offline profiles do not cover, so this test would "
        "stop being hermetic"
    )
    for pdf in pdfs:
        key = f"{hashlib.md5(pdf.read_bytes()).hexdigest()}-{PARSER_CACHE_VERSION}"
        payload = {
            "structured_data": _OFFLINE_CV_PROFILES[pdf.stem],
            "raw_llm_response": None,
            "extraction_model": "mock-fixture",
            "extraction_seed": 42,
            "status": "success",
            "parse_path": "mock_fixture",
            "error_message": None,
        }
        (cache_dir / f"{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# Run the folder branch of the wrapper chain offline, from the HR entry point down.
#
# This is the only test that runs every link the HR path uses on a multi-post advertisement, so it is
# the only place the post dimension is proved end to end instead of per module. The link above
# run_jas_import — host-envelope's `screen_refno` — cannot be driven offline: it accepts no
# --output-dir, so it would write the HR pack to the real Desktop and the job state into the repo.
# Its multi-post projection is covered in backend/tests/unit/test_host_envelope.py.
def _run_folder_chain(jas_dir: Path, tmp_path: Path, cache_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # The cv-parser's hash cache defaults to the repo's data/cache; moving it into tmp_path keeps
    # this run hermetic and leaves no mock entry behind in the developer's cache.
    env["CACHE_DIR"] = str(cache_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [
            sys.executable,
            str(IMPORT_SCRIPT),
            str(jas_dir),
            "--output-dir",
            str(tmp_path / "out"),
            # Same reason as _screening_args: a run records job state under the refno it screened.
            "--state-dir",
            str(tmp_path / "state"),
            "--scratch-dir",
            str(tmp_path / "scratch"),
            # A test must never pop a browser open.
            "--no-open",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


# The multi-post fixture drives the whole chain into one report holding both posts.
#
# The cv-parser's LLM call is replaced at its own cache rather than at extracted-*.json: seeding the
# pipeline's artifacts would skip the cv-parser link entirely, while a warm hash cache keeps it in
# the chain and replaces only the network call.
def test_multi_post_fixture_runs_the_whole_chain(tmp_path) -> None:
    jas_dir = generate_mock_jas_dir(tmp_path / "jas", multi_post=True)
    cache_dir = tmp_path / "cache"
    _seed_cv_cache(cache_dir, jas_dir)

    proc = _run_folder_chain(jas_dir, tmp_path, cache_dir)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "success"
    assert payload["multi_post"] is True
    assert payload["failures"] == []

    # Each applicant is filed under the post the page's own `Post applied for` column names (FR-2),
    # and each post's group ranks from 1: the two are never ranked against one another (FR-5).
    assert [(c["appno"], c["post"], c["rank"]) for c in payload["candidates"]] == [
        ("123456", "Project Associate", 1),
        ("654321", "Project Assistant", 1),
    ]

    # The posts come out in the order the records page lists applicants, each with its own count,
    # and nothing needed confirming (FR-6.3, FR-7).
    assert [(p["post"], p["applicants"], p["top_appno"]) for p in payload["posts"]] == [
        ("Project Associate", 1, "123456"),
        ("Project Assistant", 1, "654321"),
    ]
    assert payload["needs_confirmation"] == []
    assert payload["unmatched_posts"] == []

    # One job folder holding one report — never one folder or one board per post (§13.5.2).
    assert [path.name for path in (tmp_path / "out").iterdir()] == [MOCK_REFNO]
    job_dir = tmp_path / "out" / MOCK_REFNO
    board = job_dir / "ranking-overview.html"
    assert board.is_file()
    assert sorted(path.name for path in job_dir.glob("*.html")) == [
        "123456.html",
        "654321.html",
        "ranking-overview.html",
    ]
    # Positive control for the --state-dir the conftest guard insists on.
    assert (tmp_path / "state" / f"{MOCK_REFNO}.json").is_file()

    # One <details class='post-section'> per post, in the records page's order, and each section
    # holds its own applicant and no other.
    html = board.read_text(encoding="utf-8")
    sections = html.split("<details class='post-section'")[1:]
    assert len(sections) == 2
    bodies = [section.split("</details>", 1)[0] for section in sections]
    for body, post, appno, other in (
        (bodies[0], "Project Associate", "123456", "654321"),
        (bodies[1], "Project Assistant", "654321", "123456"),
    ):
        assert post in body, f"{post} has no section"
        assert "1 applicant" in body, f"{post}'s section does not count its applicant"
        assert appno in body, f"{post}'s section does not list {appno}"
        assert other not in body, f"{post}'s section leaked {other} from the other post"

    # §13.5.4: the page this fixture mirrors carries names, emails, phones, HKIDs and salaries. The
    # run is handed all of it and none of it may appear in a delivered artifact.
    for artifact in (board, job_dir / "123456.html", job_dir / "654321.html"):
        text = artifact.read_text(encoding="utf-8")
        leaked = [token for token in _MOCK_PII_TOKENS if token in text]
        assert not leaked, f"{artifact.name} carries {leaked}"