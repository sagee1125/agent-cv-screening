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
        ["--extracted", str(extracted_file), "--config", str(config_file)],
        monkeypatch,
        capsys,
    )
    assert exit_code == 0

    api_result = score_candidate_skill(SAMPLE_EXTRACTED, SAMPLE_CONFIG)
    api_json = json.loads(json.dumps(api_result, default=_json_default))
    assert cli_json == api_json
    assert "total_score" in cli_json and "tier" in cli_json


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
