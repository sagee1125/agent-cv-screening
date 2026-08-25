"""Compatibility tests: agent CLI scripts and REST API share one code path.

Both entry points call the same app.skills.* functions:
- REST API routes (backend/app/api/routes/*) -> for the frontend
- Skill CLI scripts (.codex/skills/*/scripts/*) -> for the integrated agent

Each test feeds the same input through the CLI wrapper and the shared
function, then asserts the CLI JSON output equals the function return value,
so the two paths cannot drift.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

# backend/tests/unit/test_skill_cli_compat.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"

SCRIPT_NAMES = {
    "cv-parser": "run_cv_parse.py",
    "jd-parser": "run_jd_parse.py",
    "scorer": "run_score.py",
    "report-gen": "run_report.py",
    "polyu-import": "run_polyu_import.py",
    "pipeline": "run_pipeline.py",
}


def _import_script(skill: str) -> Any:
    """Import a skill CLI script module in-process (executes its _bootstrap)."""
    script_path = SKILLS_DIR / skill / "scripts" / SCRIPT_NAMES[skill]
    sys.path.insert(0, str(script_path.parent))  # make `import _bootstrap` resolve
    module_name = f"skill_{skill.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cli(module: Any, argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    """Run a CLI script main() with the given argv and return (exit_code, stdout JSON)."""
    monkeypatch.setattr(sys, "argv", [module.__file__] + argv)
    exit_code = module.main()
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out)


def _json_default(value: object) -> object:
    # The scorer returns Decimal for total_score; keep it JSON-serializable.
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


SAMPLE_JD = """Senior Backend Engineer

Requirements:
- 3+ years of experience with Python and FastAPI
- Strong SQL and PostgreSQL skills
- Must have Docker
- Nice to have: AWS, Kubernetes, Redis

Preferred:
- Experience with distributed systems

Responsibilities:
- Design and maintain REST APIs
"""


def test_jd_parser_cli_matches_skill_function(tmp_path, monkeypatch, capsys) -> None:
    """The JD Parser CLI output equals parse_jd_skill() for the same input."""
    from app.skills.jd_parse import parse_jd_skill

    jd_file = tmp_path / "jd.txt"
    jd_file.write_text(SAMPLE_JD, encoding="utf-8")

    module = _import_script("jd-parser")
    exit_code, cli_json = _run_cli(module, ["--jd-file", str(jd_file)], monkeypatch, capsys)
    assert exit_code == 0

    api_json = asyncio.run(parse_jd_skill(SAMPLE_JD))
    assert cli_json == api_json
    assert cli_json["structured_data"]["must_skills"]  # sanity: non-empty parse


SAMPLE_EXTRACTED = {
    "name": "Alice Chen",
    "email": "alice@example.com",
    "phone": None,
    "skills": ["Python", "FastAPI", "Docker", "SQL", "PostgreSQL"],
    "education": [
        {"school": "National Taiwan University", "degree": "MSc", "major": "Computer Science", "period": "2020-2023"}
    ],
    "experience": [
        {
            "company": "Acme",
            "job_title": "Backend Engineer",
            "period": "2021-01 - 2024-01",
            "description": "???????, ?? API ????????",
        }
    ],
    "publications": [{"title": "Scalable REST APIs", "journal": "IEEE", "year": "2023"}],
}

SAMPLE_CONFIG = {
    "required_skills": ["Python", "FastAPI", "Docker"],
    "target_experience_years": 3,
    "target_degrees": ["MSc", "??"],
    "weights": {
        "skill_match": 0.3,
        "experience_match": 0.2,
        "education_match": 0.2,
        "research_quality": 0.15,
        "experience_quality": 0.15,
    },
    "tiers": [
        {"name": "Tier 1", "min_score": 85, "max_score": 100},
        {"name": "Tier 2", "min_score": 70, "max_score": 84.99},
        {"name": "Tier 3", "min_score": 50, "max_score": 69.99},
        {"name": "Tier 4", "min_score": 0, "max_score": 49.99},
    ],
}


def test_scorer_cli_matches_skill_function(tmp_path, monkeypatch, capsys) -> None:
    """The Scorer CLI output equals score_candidate_skill() for the same input."""
    from app.skills.score import score_candidate_skill

    extracted_file = tmp_path / "extracted.json"
    extracted_file.write_text(json.dumps(SAMPLE_EXTRACTED, ensure_ascii=False), encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, ensure_ascii=False), encoding="utf-8")

    module = _import_script("scorer")
    exit_code, cli_json = _run_cli(
        module,
        ["score", "--extracted", str(extracted_file), "--config", str(config_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0

    api_result = score_candidate_skill(SAMPLE_EXTRACTED, SAMPLE_CONFIG)
    api_json = json.loads(json.dumps(api_result, default=_json_default))
    assert cli_json == api_json
    assert "total_score" in cli_json and "tier" in cli_json


SAMPLE_JD_STRUCTURED_PATH = SKILLS_DIR / "scorer" / "examples" / "sample-jd-structured.json"


def test_scorer_build_config_cli_matches_skill_function(monkeypatch, capsys) -> None:
    """The Scorer build-config CLI stdout equals build_scoring_config_from_jd() for the sample JD."""
    from app.skills.score import build_scoring_config_from_jd

    jd_structured = json.loads(SAMPLE_JD_STRUCTURED_PATH.read_text(encoding="utf-8-sig"))
    module = _import_script("scorer")
    exit_code, cli_json = _run_cli(
        module,
        ["build-config", "--jd-structured", str(SAMPLE_JD_STRUCTURED_PATH)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    api_config = build_scoring_config_from_jd(jd_structured)
    api_json = json.loads(json.dumps(api_config, default=_json_default))
    assert cli_json == {"status": "success", "config": api_json}
    assert cli_json["config"]["required_skills"]


def test_scorer_build_config_output_file_is_raw_config(tmp_path, monkeypatch, capsys) -> None:
    """build-config --output writes the raw scoring config (no status/config wrapper)."""
    module = _import_script("scorer")
    out_file = tmp_path / "config.json"
    exit_code, cli_json = _run_cli(
        module,
        ["build-config", "--jd-structured", str(SAMPLE_JD_STRUCTURED_PATH), "--output", str(out_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert cli_json["status"] == "success"  # stdout keeps the envelope
    file_config = json.loads(out_file.read_text(encoding="utf-8"))
    assert "required_skills" in file_config
    assert "status" not in file_config
    assert "config" not in file_config
    assert file_config["required_skills"]


def test_scorer_pipeline_build_config_then_score(tmp_path, monkeypatch, capsys) -> None:
    """The full pipeline build-config --output -> score --config scores with non-empty required_skills."""
    extracted_file = tmp_path / "extracted.json"
    extracted_file.write_text(json.dumps(SAMPLE_EXTRACTED, ensure_ascii=False), encoding="utf-8")
    config_file = tmp_path / "config.json"

    module = _import_script("scorer")
    exit_code, _ = _run_cli(
        module,
        ["build-config", "--jd-structured", str(SAMPLE_JD_STRUCTURED_PATH), "--output", str(config_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    file_config = json.loads(config_file.read_text(encoding="utf-8"))
    assert file_config["required_skills"]

    exit_code, score_json = _run_cli(
        module,
        ["score", "--extracted", str(extracted_file), "--config", str(config_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert "total_score" in score_json and "tier" in score_json
    assert score_json["dimension_scores"]["skill_match"] >= 0


def test_scorer_cli_backward_compat_without_subcommand(tmp_path, monkeypatch, capsys) -> None:
    """A flat invocation without a subcommand defaults to the score subcommand."""
    extracted_file = tmp_path / "extracted.json"
    extracted_file.write_text(json.dumps(SAMPLE_EXTRACTED, ensure_ascii=False), encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, ensure_ascii=False), encoding="utf-8")

    module = _import_script("scorer")
    exit_code, cli_json = _run_cli(
        module,
        ["--extracted", str(extracted_file), "--config", str(config_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert "total_score" in cli_json and "tier" in cli_json


def test_scorer_unwraps_cv_parser_envelope(tmp_path, monkeypatch, capsys) -> None:
    """score auto-unwraps a CV parser envelope so scoring matches the plain profile."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, ensure_ascii=False), encoding="utf-8")

    plain_file = tmp_path / "plain.json"
    plain_file.write_text(json.dumps(SAMPLE_EXTRACTED, ensure_ascii=False), encoding="utf-8")
    envelope_file = tmp_path / "envelope.json"
    envelope_file.write_text(
        json.dumps({"status": "success", "structured_data": SAMPLE_EXTRACTED}, ensure_ascii=False),
        encoding="utf-8",
    )

    module = _import_script("scorer")
    _, plain_json = _run_cli(
        module, ["score", "--extracted", str(plain_file), "--config", str(config_file)], monkeypatch, capsys
    )
    _, envelope_json = _run_cli(
        module, ["score", "--extracted", str(envelope_file), "--config", str(config_file)], monkeypatch, capsys
    )
    assert plain_json == envelope_json
    assert plain_json["dimension_scores"]["skill_match"] > 0


def test_scorer_rejects_invalid_extracted(tmp_path, monkeypatch, capsys) -> None:
    """score fails fast with an error envelope for invalid extracted input."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, ensure_ascii=False), encoding="utf-8")
    module = _import_script("scorer")

    for payload in ({}, {"status": "success", "structured_data": None}):
        extracted_file = tmp_path / "extracted.json"
        extracted_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [module.__file__, "score", "--extracted", str(extracted_file), "--config", str(config_file)],
        )
        exit_code = module.main()
        captured = capsys.readouterr()
        assert exit_code == 1
        err = json.loads(captured.err)
        assert err["status"] == "error"
        assert "error_message" in err


def test_scorer_pipeline_cv_envelope_then_score(tmp_path, monkeypatch, capsys) -> None:
    """A cv-parser --output envelope fed to score yields a real skill_match (skills are read)."""
    extracted_file = tmp_path / "extracted.json"
    extracted_file.write_text(
        json.dumps({"status": "success", "structured_data": SAMPLE_EXTRACTED}, ensure_ascii=False),
        encoding="utf-8",
    )
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, ensure_ascii=False), encoding="utf-8")

    module = _import_script("scorer")
    exit_code, cli_json = _run_cli(
        module, ["score", "--extracted", str(extracted_file), "--config", str(config_file)], monkeypatch, capsys
    )
    assert exit_code == 0
    assert cli_json["dimension_scores"]["skill_match"] > 0


def test_scorer_build_config_rejects_invalid_jd(tmp_path, monkeypatch, capsys) -> None:
    """build-config fails fast with an error envelope for invalid JD input."""
    jd_file = tmp_path / "invalid.json"
    jd_file.write_text(json.dumps({"status": "invalid_input", "structured_data": None}), encoding="utf-8")

    module = _import_script("scorer")
    monkeypatch.setattr(sys, "argv", [module.__file__, "build-config", "--jd-structured", str(jd_file)])
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    err = json.loads(captured.err)
    assert err["status"] == "error"
    assert "error_message" in err


REPORT_GEN_DIR = SKILLS_DIR / "report-gen"
REPORT_GEN_SAMPLE_EXTRACTED_PATH = REPORT_GEN_DIR / "examples" / "sample-extracted.json"
REPORT_GEN_SAMPLE_SCORE_PATH = REPORT_GEN_DIR / "examples" / "sample-score.json"


def test_report_gen_candidate_cli_matches_skill_function(tmp_path, monkeypatch, capsys) -> None:
    """The report-gen candidate CLI stdout equals generate_candidate_report_skill() for the same inputs."""
    from app.skills.report import generate_candidate_report_skill

    extracted_file = REPORT_GEN_SAMPLE_EXTRACTED_PATH
    score_file = REPORT_GEN_SAMPLE_SCORE_PATH
    out_file = tmp_path / "candidate.pdf"

    module = _import_script("report-gen")
    exit_code, cli_json = _run_cli(
        module,
        ["candidate", "--extracted", str(extracted_file), "--score", str(score_file),
         "--position", "Backend Engineer", "--rank", "1", "--output", str(out_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    skill_json = generate_candidate_report_skill(
        extracted_data=json.loads(extracted_file.read_text(encoding="utf-8-sig")),
        score_result=json.loads(score_file.read_text(encoding="utf-8-sig")),
        position_name="Backend Engineer",
        rank=1,
        output_path=str(out_file),
    )
    assert cli_json == skill_json
    assert out_file.stat().st_size > 0


def test_report_gen_unwraps_ranked_score_envelope(tmp_path, monkeypatch, capsys) -> None:
    """A ranked {score, ranking} envelope is unwrapped so the PDF uses the real total_score."""
    from pypdf import PdfReader

    score_data = json.loads(REPORT_GEN_SAMPLE_SCORE_PATH.read_text(encoding="utf-8-sig"))
    envelope = {"score": score_data, "ranking": []}
    score_file = tmp_path / "ranked-score.json"
    score_file.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    out_file = tmp_path / "candidate.pdf"

    module = _import_script("report-gen")
    exit_code, cli_json = _run_cli(
        module,
        ["candidate", "--extracted", str(REPORT_GEN_SAMPLE_EXTRACTED_PATH), "--score", str(score_file),
         "--position", "Backend Engineer", "--output", str(out_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert cli_json["status"] == "success" and cli_json["format"] == "pdf"
    assert out_file.stat().st_size > 0
    text = PdfReader(str(out_file)).pages[0].extract_text()
    assert "58.70" in text  # real total_score, not a silent zero


def test_report_gen_rejects_invalid_score(tmp_path, monkeypatch, capsys) -> None:
    """report-gen candidate fails fast with an error envelope for invalid score input."""
    score_file = tmp_path / "invalid-score.json"
    score_file.write_text("{}", encoding="utf-8")
    out_file = tmp_path / "candidate.pdf"

    module = _import_script("report-gen")
    monkeypatch.setattr(
        sys,
        "argv",
        [module.__file__, "candidate", "--extracted", str(REPORT_GEN_SAMPLE_EXTRACTED_PATH),
         "--score", str(score_file), "--position", "Backend Engineer", "--output", str(out_file)],
    )
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    err = json.loads(captured.err)
    assert err["status"] == "error"
    assert "error_message" in err
    assert not out_file.exists()


def test_report_gen_pipeline_score_then_report(tmp_path, monkeypatch, capsys) -> None:
    """The scorer -> report-gen candidate pipeline produces a non-empty PDF."""
    extracted_file = tmp_path / "extracted.json"
    extracted_file.write_text(json.dumps(SAMPLE_EXTRACTED, ensure_ascii=False), encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, ensure_ascii=False), encoding="utf-8")
    score_file = tmp_path / "score.json"
    out_file = tmp_path / "candidate.pdf"

    scorer = _import_script("scorer")
    # score --output writes the result file and prints nothing to stdout, so call main() directly.
    monkeypatch.setattr(
        sys,
        "argv",
        [scorer.__file__, "score", "--extracted", str(extracted_file), "--config", str(config_file),
         "--output", str(score_file)],
    )
    assert scorer.main() == 0
    capsys.readouterr()
    assert score_file.stat().st_size > 0

    module = _import_script("report-gen")
    exit_code, cli_json = _run_cli(
        module,
        ["candidate", "--extracted", str(extracted_file), "--score", str(score_file),
         "--position", "Backend Engineer", "--output", str(out_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert cli_json["status"] == "success" and cli_json["format"] == "pdf"
    assert out_file.stat().st_size > 0


POLYU_LISTING_HTML = """
<table>
  <tr class="ITS_clickableTableRow" data-href="job_detail.php?job=260818008" style="cursor:pointer;">
    <td>Office of Faculty of Science</td>
    <td>Senior Backend Engineer</td>
    <td>24 August 2026</td>
    <td>260818008-IE</td>
  </tr>
</table>
"""
POLYU_DETAIL_HTML = """
<main class="page-content">
  <h2><strong>Senior Backend Engineer</strong></h2>
  <p><strong>Duties</strong></p>
  <p>The appointee will be required to design and maintain REST APIs.</p>
  <p><strong>Requirements</strong></p>
  <p>3+ years of experience with Python and FastAPI.</p>
  <p>Strong SQL and PostgreSQL skills. Must have Docker.</p>
  <p>Nice to have: AWS, Kubernetes, Redis.</p>
  <p>The closing date for application is 24 August 2026.</p>
  Posting date: 18 August 2026
</main>
"""


# Install async network stubs on the polyu-import skill module using the PolyU HTML fixtures.
def _stub_polyu_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.skills.polyu_import as polyu_skill
    from app.services.polyu_jobs import parse_detail_html, parse_listing_html

    async def fake_listings():
        return parse_listing_html(POLYU_LISTING_HTML)

    async def fake_detail(listing):
        return parse_detail_html(POLYU_DETAIL_HTML)

    monkeypatch.setattr(polyu_skill, "fetch_polyu_listings", fake_listings)
    monkeypatch.setattr(polyu_skill, "fetch_polyu_detail", fake_detail)


def test_build_config_unwraps_polyu_fetch_and_parse_output(tmp_path, monkeypatch, capsys) -> None:
    """build-config unwraps a polyu fetch-and-parse envelope (jd_parse.structured_data)."""
    jd_structured = json.loads(SAMPLE_JD_STRUCTURED_PATH.read_text(encoding="utf-8-sig"))
    envelope = {
        "status": "success",
        "external_ref": "260818008-IE",
        "jd_parse": {"status": "success", "structured_data": jd_structured},
    }
    jd_file = tmp_path / "polyu-parsed.json"
    jd_file.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")

    module = _import_script("scorer")
    exit_code, cli_json = _run_cli(module, ["build-config", "--jd-structured", str(jd_file)], monkeypatch, capsys)
    assert exit_code == 0
    assert cli_json["status"] == "success"
    assert cli_json["config"]["required_skills"]


def test_polyu_fetch_and_parse_includes_top_level_structured_data(monkeypatch) -> None:
    """fetch-and-parse mirrors jd_parse.structured_data at the top level."""
    import app.skills.polyu_import as polyu_skill

    _stub_polyu_network(monkeypatch)
    result = asyncio.run(polyu_skill.fetch_and_parse_polyu_job_skill(external_ref="260818008-IE"))
    assert result["status"] == "success"
    assert result["structured_data"] == result["jd_parse"]["structured_data"]
    assert result["structured_data"]["must_skills"]


def test_polyu_fetch_and_parse_fails_on_invalid_jd_parse(tmp_path, monkeypatch, capsys) -> None:
    """fetch-and-parse exits 1 with an error envelope when the JD parser fails."""
    import app.skills.jd_parse as jd_parse_mod

    _stub_polyu_network(monkeypatch)

    async def fake_parse(jd_text: str, *, parser: Any = None, mode: str | None = None) -> dict[str, Any]:
        return {"status": "invalid_input", "structured_data": None, "error_message": "empty JD"}

    monkeypatch.setattr(jd_parse_mod, "parse_jd_skill", fake_parse)
    module = _import_script("polyu-import")
    monkeypatch.setattr(sys, "argv", [module.__file__, "fetch-and-parse", "--external-ref", "260818008-IE"])
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    err = json.loads(captured.err)
    assert err["status"] == "error"
    assert "JD parse failed" in err["error_message"]


def test_polyu_fetch_external_ref_not_in_catalog_error_message(tmp_path, monkeypatch, capsys) -> None:
    """fetch with an unknown external-ref and no detail-url errors with a fallback hint."""
    _stub_polyu_network(monkeypatch)
    module = _import_script("polyu-import")
    monkeypatch.setattr(sys, "argv", [module.__file__, "fetch", "--external-ref", "999999-X"])
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    err = json.loads(captured.err)
    assert "not found" in err["error_message"] and "detail-url" in err["error_message"]


def test_polyu_pipeline_fetch_and_parse_then_build_config(tmp_path, monkeypatch, capsys) -> None:
    """polyu fetch-and-parse output feeds straight into scorer build-config."""
    _stub_polyu_network(monkeypatch)

    parsed_file = tmp_path / "polyu-parsed.json"
    module = _import_script("polyu-import")
    monkeypatch.setattr(
        sys,
        "argv",
        [module.__file__, "fetch-and-parse", "--external-ref", "260818008-IE", "--output", str(parsed_file)],
    )
    assert module.main() == 0
    capsys.readouterr()
    assert parsed_file.stat().st_size > 0

    scorer = _import_script("scorer")
    exit_code, cli_json = _run_cli(
        scorer,
        ["build-config", "--jd-structured", str(parsed_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert cli_json["status"] == "success"
    assert cli_json["config"]["required_skills"]


def test_cv_parser_cli_wraps_skill_function(tmp_path, monkeypatch, capsys) -> None:
    """The CV Parser CLI passes args through and serializes the shared function output.

    Parsing itself requires the live LLM, so this verifies the wrapper plumbing
    (arg forwarding + JSON serialization) with a stubbed parse_cv_skill.
    """
    module = _import_script("cv-parser")

    fake_result = {
        "file_hash": "abc123",
        "cache_hit": False,
        "status": "success",
        "parse_path": "vision",
        "structured_data": {
            "name": "Test User",
            "email": None,
            "phone": None,
            "skills": ["Python"],
            "education": [],
            "experience": [],
            "publications": [],
        },
        "raw_llm_response": None,
        "extraction_model": "fake-model",
        "extraction_seed": 42,
        "error_message": None,
    }
    calls: list[tuple[str, str | None]] = []

    async def fake_parse_cv_skill(file_path: str, jd_text: str | None = None, *, parser: Any = None) -> dict[str, Any]:
        calls.append((file_path, jd_text))
        return fake_result

    monkeypatch.setattr(module, "parse_cv_skill", fake_parse_cv_skill)
    cv_path = tmp_path / "cv.pdf"

    exit_code, cli_json = _run_cli(
        module,
        ["--file", str(cv_path), "--jd-text", "Some JD context"],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert cli_json == fake_result
    assert calls == [(str(cv_path), "Some JD context")]


def test_pipeline_rejects_orphan_polyu_detail_url(tmp_path, monkeypatch, capsys) -> None:
    """--polyu-detail-url without --polyu-ref fails fast instead of overriding --jd-file."""
    module = _import_script("pipeline")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--jd-file",
            str(tmp_path / "jd.txt"),
            "--polyu-detail-url",
            "https://jobs.polyu.edu.hk/job_detail.php?job=123",
            "--extracted",
            str(REPORT_GEN_SAMPLE_EXTRACTED_PATH),
            "--skip-reports",
        ],
    )
    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    err = json.loads(captured.err)
    assert err["status"] == "error"
    assert "polyu-detail-url" in err["error_message"]


def test_pipeline_matching_offline_skip_reports(tmp_path, monkeypatch, capsys) -> None:
    """Pipeline matching engine runs end-to-end with pre-parsed JD + extracted JSON (no LLM)."""
    module = _import_script("pipeline")
    out_dir = tmp_path / "pipeline_out"
    exit_code, manifest = _run_cli(
        module,
        [
            "--jd-json",
            str(SAMPLE_JD_STRUCTURED_PATH),
            "--extracted",
            str(REPORT_GEN_SAMPLE_EXTRACTED_PATH),
            "--engine",
            "matching",
            "--skip-reports",
            "--output-dir",
            str(out_dir),
        ],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0
    assert manifest["status"] == "success"
    assert manifest["engine"] == "matching"
    assert manifest["candidates"][0]["detail_json"]
    assert manifest["candidates"][0]["score_json"] is None
    row = manifest["candidates"][0]
    assert row["total_score"] >= 0
    assert (out_dir / "detail-1.json").is_file()
