# Tests CV parsing normalization, privacy masking, and local fallback behavior.
from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf
import pytest

from cv_parser import local_ner as local_ner_module
from cv_parser import CVParserService
from cv_parser.pdf_utils import (
    extract_with_pymupdf,
    render_redacted_pdf_pages_as_data_urls,
)
from cv_parser.ocr import LocalCVDocument, extract_local_cv_document
from cv_parser.pii import (
    contact_values_for_redaction,
    detect_contact_entities,
    mask_pii_text,
)
from cv_parser.service import PARSER_CACHE_VERSION


class DummyCache:
    """Stores parser cache interactions in memory for assertions."""

    def __init__(self, cached: dict[str, Any] | None = None) -> None:
        self.cached = cached
        self.fetched_key: str | None = None
        self.saved_key: str | None = None
        self.saved_value: dict[str, Any] | None = None

    async def md5_for_file(self, _: str) -> str:
        return "abc123"

    async def get(self, key: str) -> dict[str, Any] | None:
        self.fetched_key = key
        return self.cached

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self.saved_key = key
        self.saved_value = value


class DummyLLM:
    """Returns a deterministic payload and records text prompts sent externally."""

    def __init__(self) -> None:
        self.called = False
        self.user_prompt: str | None = None

    async def chat_completion(self, _: str, user_prompt: str, **__: Any) -> dict[str, Any]:
        self.called = True
        self.user_prompt = user_prompt
        return {
            "model": "gpt-4o-mini",
            "parsed": {
                "name": "Alice",
                "email": "alice@example.com",
                "phone": None,
                "education": [],
                "experience": [],
                "skills": ["Python"],
                "publications": [],
            },
        }


@pytest.mark.asyncio
async def test_parse_cv_cache_hit_uses_cached_payload() -> None:
    cache = DummyCache(
        {
            "structured_data": {"name": "Cache User"},
            "raw_llm_response": {"name": "Cache User"},
            "status": "success",
        }
    )
    llm = DummyLLM()
    service = CVParserService(llm_client=llm, cache=cache)

    result = await service.parse_cv("any.pdf")

    assert result["cache_hit"] is True
    assert result["structured_data"]["name"] == "Cache User"
    assert llm.called is False
    assert cache.fetched_key == f"abc123-{PARSER_CACHE_VERSION}"


@pytest.mark.asyncio
async def test_parse_cv_cache_miss_stores_structured_and_raw() -> None:
    cache = DummyCache()
    llm = DummyLLM()
    service = CVParserService(llm_client=llm, cache=cache)

    async def fake_extract(_: str) -> LocalCVDocument:
        # Supplies realistic local contact data without reading a fixture PDF.
        return LocalCVDocument(
            raw_text="Alice Local\nalice.local@example.com\n+852 6123 4567\nSkills\nPython",
            page_texts=(),
            ocr_lines=(),
            ocr_page_indexes=frozenset(),
        )

    service._extract_local_document = fake_extract  # type: ignore[method-assign]

    result = await service.parse_cv("resume.pdf")

    assert result["cache_hit"] is False
    assert result["status"] == "success"
    assert result["structured_data"]["name"] == "Alice Local"
    assert result["structured_data"]["email"] == "alice.local@example.com"
    assert "name" not in result["raw_llm_response"]
    assert "email" not in result["raw_llm_response"]
    assert cache.saved_key == f"abc123-{PARSER_CACHE_VERSION}"
    assert cache.saved_value is not None
    assert [skill["canonical_skill"] for skill in cache.saved_value["structured_data"]["skills"]] == ["python"]
    assert llm.user_prompt is not None
    assert "Alice Local" not in llm.user_prompt
    assert "alice.local@example.com" not in llm.user_prompt
    assert "+852 6123 4567" not in llm.user_prompt


def test_normalize_schema_handles_aliases_and_string_payloads() -> None:
    payload = {
        "name": "Bob",
        "technical_skills": "Python, FastAPI; PostgreSQL",
        "educations": "MSc in Computer Science, MIT 2020",
        "work_experience": {"company": "ACME", "role": "Engineer", "from": "2021-01", "to": "2023-02"},
        "publication": "Efficient CV Parsing 2022",
    }

    normalized = CVParserService._normalize_schema(payload)

    assert [skill["canonical_skill"] for skill in normalized["skills"]] == [
        "python",
        "fastapi",
        "postgresql",
    ]
    assert "MIT 2020" in normalized["education"][0]["school"]
    assert normalized["education"][0]["degree"] == "Master"
    assert normalized["education"][0]["degree_level"] == "master"
    assert normalized["experience"][0]["job_title"] == "Engineer"
    assert normalized["publications"][0]["title"] == "Efficient CV Parsing 2022"


def test_apply_content_fallback_recovers_sections_when_arrays_empty() -> None:
    service = CVParserService(llm_client=DummyLLM(), cache=DummyCache())
    raw_text = """
    Skills:
    Python, FastAPI, Docker
    Education:
    MPhil in Computer Science, National Taiwan University 2021
    Experience:
    Backend Engineer at ACME 2021-2024
    Publications:
    Practical LLM Systems 2023
    """

    enriched = service._apply_content_fallback(
        raw_text,
        {"skills": [], "education": [], "experience": [], "publications": []},
    )

    assert [skill["canonical_skill"] for skill in enriched["skills"]] == [
        "python",
        "fastapi",
        "docker",
    ]
    assert "National Taiwan University" in enriched["education"][0]["school"]
    assert enriched["education"][0]["degree"] == "MPhil"
    assert enriched["education"][0]["degree_level"] == "master"
    assert "ACME" in enriched["experience"][0]["description"]
    assert enriched["publications"][0]["year"] == "2023"


def test_normalize_experience_extracts_fields_from_text_line() -> None:
    payload = {
        "experience": [
            "Senior Backend Engineer at ACME Corp 2021-01 - 2024-03 built APIs and services"
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    first = normalized["experience"][0]
    assert first["job_title"] is not None
    assert first["company"] == "ACME Corp"
    assert first["start_date"] == "2021-01"
    assert first["end_date"] == "2024-03"


def test_merge_contact_hints_prefers_bracket_phone_format() -> None:
    merged = CVParserService._merge_contact_hints(
        {"phone": "+852 61234567"},
        {"phone": "+852 (6123) 4567", "email": None, "name": None},
    )
    assert merged["phone"] == "+852 (6123) 4567"


def test_normalize_education_uses_major_for_degree_only_line() -> None:
    payload = {
        "education": [
            "Master of Engineering (MEng) in Aerospace Engineering",
            "Imperial College London",
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    assert normalized["education"][0]["school"] == "Aerospace Engineering"
    assert normalized["education"][0]["degree"] == "Master"
    assert normalized["education"][1]["school"] == "Imperial College London"


def test_normalize_education_drops_date_location_only_line() -> None:
    payload = {
        "education": [
            "01/2008 - 01/2012 London",
            "Bachelor of Engineering (BEng) in Mechanical Engineering",
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    schools = [item["school"] for item in normalized["education"]]
    assert "01/2008 - 01/2012 London" not in schools
    assert "Mechanical Engineering" in schools


# Verifies experience date normalization, is_current flag, and skills_used.
def test_normalize_experience_produces_iso_dates_and_skills_used() -> None:
    payload = {
        "experience": [
            {
                "company": "ACME",
                "job_title": "Backend Engineer",
                "period": "Jan 2021 - Present",
                "description": "Built APIs with Python and FastAPI.",
                "skills_used": ["Python", "FastAPI"],
            }
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    first = normalized["experience"][0]
    assert first["start_date"] == "2021-01"
    assert first["end_date"] == "Present"
    assert first["is_current"] is True
    assert first["skills_used"] == ["python", "fastapi"]


# Verifies education date normalization and degree_level mapping.
def test_normalize_education_produces_iso_dates_and_degree_level() -> None:
    payload = {
        "education": [
            {
                "school": "NTU",
                "degree": "PhD",
                "major": "Computer Science",
                "period": "09/2018 - 06/2022",
            }
        ]
    }

    normalized = CVParserService._normalize_schema(payload)
    first = normalized["education"][0]
    assert first["degree_level"] == "phd"
    assert first["start_date"] == "2018-09"
    assert first["end_date"] == "2022-06"
    assert first["graduation_date"] == "2022-06"


# Verifies language tokens mixed into skills are routed to the languages field.
def test_normalize_schema_routes_language_tokens_to_languages() -> None:
    payload = {"skills": ["Python", "English", "Mandarin"], "languages": ["Chinese"]}

    normalized = CVParserService._normalize_schema(payload)
    skill_canonicals = [skill["canonical_skill"] for skill in normalized["skills"]]
    assert skill_canonicals == ["python"]
    language_names = {item["language"] for item in normalized["languages"]}
    assert language_names == {"English", "Mandarin", "Chinese"}


# Verifies structured skill objects carry canonical_skill and skill_id.
def test_normalize_skill_items_builds_structured_objects() -> None:
    from cv_parser.helpers import normalize_skill_items

    skills = normalize_skill_items(["Python", "pytorch", "Python"])
    assert [skill["canonical_skill"] for skill in skills] == ["python", "pytorch"]
    assert skills[0]["skill_id"] == "python_1"
    assert skills[0]["raw"] == "Python"
    assert skills[0]["source"] == "skills_section"


# Verifies month-name and MM/YYYY date tokens parse into ISO YYYY-MM.
def test_parse_cv_date_handles_multiple_formats() -> None:
    from cv_parser.helpers import parse_cv_date

    assert parse_cv_date("Jan 2021") == "2021-01"
    assert parse_cv_date("January 2021") == "2021-01"
    assert parse_cv_date("01/2021") == "2021-01"
    assert parse_cv_date("2021-01") == "2021-01"
    assert parse_cv_date("2021") == "2021"
    assert parse_cv_date("Present") is None
    assert parse_cv_date(None) is None


# Verifies the matcher accepts structured skill dicts and folds in skills_used.
def test_skill_matcher_accepts_structured_skills_and_skills_used() -> None:
    from screening_core.taxonomy import SkillTaxonomyLoader
    from app.services.skill_matcher import SkillMatcherService

    taxonomy = SkillTaxonomyLoader("data/taxonomy/skill_taxonomy.yaml")
    taxonomy.load()
    matcher = SkillMatcherService(taxonomy)

    result = matcher.match(
        candidate_skills=[{"raw": "Python", "canonical_skill": "python", "skill_id": "python_1"}],
        required_skills=["Python"],
        experience_items=[{"description": "...", "skills_used": ["fastapi"]}],
    )
    assert result["hits"] == [{"required": "Python", "matched_with": "python"}]
    assert result["misses"] == []


# Verifies the scorer matches degrees via degree_level and falls back to substring.
def test_scorer_matches_degree_by_level_and_substring_fallback() -> None:
    from screening_core.taxonomy import SkillTaxonomyLoader
    from app.services.scorer import ScorerService
    from app.services.skill_matcher import SkillMatcherService

    taxonomy = SkillTaxonomyLoader("data/taxonomy/skill_taxonomy.yaml")
    taxonomy.load()
    scorer = ScorerService(SkillMatcherService(taxonomy))

    # New-format education with degree_level; target_degrees given as a level.
    extracted = {
        "skills": [],
        "education": [{"degree": "MSc", "degree_level": "master"}],
        "experience": [],
        "publications": [],
    }
    config = {"target_degrees": ["master"], "weights": {}}
    assert scorer._has_required_degree(extracted, config["target_degrees"]) is True

    # Old-format education (no degree_level) still matches via substring.
    old_extracted = {"education": [{"degree": "硕士"}]}
    assert scorer._has_required_degree(old_extracted, ["硕士"]) is True


# Verifies P1 fields (location, work_authorization, certifications, projects, summary).
def test_normalize_schema_produces_p1_fields() -> None:
    payload = {
        "summary": "Backend engineer with 5 years of Python experience.",
        "location": {"raw": "Hong Kong", "country": "HK", "city": "Hong Kong"},
        "work_authorization": {"status": "permanent_resident", "raw": "Permanent resident of HK"},
        "certifications": [{"name": "AWS Certified Solutions Architect", "issuer": "Amazon", "year": "2023"}],
        "projects": [
            {
                "name": "Resume Parser",
                "description": "Built an LLM-based resume parser.",
                "period": "2022-01 - 2022-06",
                "skills_used": ["Python", "FastAPI"],
            }
        ],
    }

    normalized = CVParserService._normalize_schema(payload)
    assert normalized["summary"].startswith("Backend engineer")
    assert normalized["location"]["country"] == "HK"
    assert normalized["location"]["city"] == "Hong Kong"
    assert normalized["work_authorization"]["status"] == "permanent_resident"
    assert normalized["certifications"][0]["name"] == "AWS Certified Solutions Architect"
    assert normalized["certifications"][0]["year"] == "2023"
    assert normalized["projects"][0]["name"] == "Resume Parser"
    assert normalized["projects"][0]["skills_used"] == ["python", "fastapi"]


# Verifies work authorization fallback infers status from sponsorship cues.
def test_normalize_work_authorization_infers_status_from_raw() -> None:
    from cv_parser.helpers import normalize_work_authorization

    assert normalize_work_authorization("Require visa sponsorship")["status"] == "requires_sponsorship"
    assert normalize_work_authorization("Authorized to work in the US")["status"] == "has_work_permit"
    assert normalize_work_authorization(None)["status"] == "unknown"
    assert normalize_work_authorization({"status": "citizen", "raw": "US citizen"})["status"] == "citizen"


# Verifies apply_content_fallback fills P1 sections from CV text.
def test_apply_content_fallback_recovers_p1_sections() -> None:
    service = CVParserService(llm_client=DummyLLM(), cache=DummyCache())
    raw_text = """
    Summary:
    Backend engineer specializing in Python APIs.
    Certifications:
    AWS Certified Solutions Architect 2023
    Projects:
    Resume Parser - LLM-based CV parsing tool
    Location:
    Hong Kong
    """

    enriched = service._apply_content_fallback(
        raw_text,
        {
            "skills": [], "languages": [], "education": [], "experience": [],
            "publications": [], "certifications": [], "projects": [],
            "summary": None, "location": None, "work_authorization": None,
        },
    )

    assert enriched["summary"] is not None
    assert "Backend engineer" in enriched["summary"]
    assert any("AWS" in cert["name"] for cert in enriched["certifications"])
    assert any("Resume Parser" in (proj["description"] or "") for proj in enriched["projects"])
    assert enriched["location"] is not None
    assert "Hong Kong" in (enriched["location"]["raw"] or "")


# Verifies project skills_used count toward skill matching via additional_skills.
def test_scorer_folds_project_skills_into_match() -> None:
    from screening_core.taxonomy import SkillTaxonomyLoader
    from app.services.scorer import ScorerService
    from app.services.skill_matcher import SkillMatcherService

    taxonomy = SkillTaxonomyLoader("data/taxonomy/skill_taxonomy.yaml")
    taxonomy.load()
    scorer = ScorerService(SkillMatcherService(taxonomy))

    extracted = {
        "skills": [],
        "experience": [],
        "projects": [{"name": "p", "description": "...", "skills_used": ["python"]}],
        "publications": [],
    }
    config = {"required_skills": ["Python"], "weights": {}}
    result = scorer.score_candidate(extracted, config)
    assert result["full_snapshot"]["skill_match_details"]["hit"] == [
        {"required": "Python", "matched_with": "python"}
    ]


# Verifies local PII replacement does not destroy useful experience text.
def test_local_pii_masking_preserves_non_identity_cv_content() -> None:
    raw_text = (
        "陳大文\n"
        "Email: david.chan@example.com\n"
        "Phone: +852 6123 4567\n"
        "LinkedIn: linkedin.com/in/david-chan\n"
        "Experience\n"
        "Engineer at ACME 2021 - 2024"
    )

    entities = detect_contact_entities(raw_text)
    masked = mask_pii_text(raw_text)

    assert {entity.kind for entity in entities} == {"name", "email", "phone", "url"}
    assert "陳大文" not in masked
    assert "david.chan@example.com" not in masked
    assert "+852 6123 4567" not in masked
    assert "linkedin.com/in/david-chan" not in masked
    assert "Engineer at ACME 2021 - 2024" in masked


# Verifies coordinate redaction succeeds before a page image is produced.
def test_redacted_pdf_renderer_removes_detected_text_before_rendering(tmp_path: Path) -> None:
    pdf_path = tmp_path / "candidate.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Alice Local\nalice.local@example.com\n+852 6123 4567\nPython Engineer",
        fontsize=11,
    )
    document.save(pdf_path)
    document.close()

    raw_text = extract_with_pymupdf(pdf_path)
    image_urls = render_redacted_pdf_pages_as_data_urls(
        str(pdf_path),
        max_pages=1,
        pii_values=contact_values_for_redaction(raw_text),
    )

    assert raw_text.startswith("Alice Local")
    assert len(image_urls) == 1
    assert image_urls[0].startswith("data:image/")


# Verifies PDFs without a local text layer never reach an external model.
@pytest.mark.asyncio
async def test_image_only_pdf_fails_closed_before_calling_llm(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(pdf_path)
    document.close()
    llm = DummyLLM()
    service = CVParserService(llm_client=llm, cache=DummyCache())

    with pytest.raises(ValueError, match="Failed to extract PDF text with local OCR"):
        await service.parse_cv(str(pdf_path))

    assert llm.called is False


# Verifies uncertain local name extraction blocks both Vision and text LLM calls.
@pytest.mark.asyncio
async def test_missing_local_name_uses_privacy_rule_fallback() -> None:
    llm = DummyLLM()
    service = CVParserService(llm_client=llm, cache=DummyCache())

    async def fake_extract(_: str) -> LocalCVDocument:
        # Supplies content with contact details but no safely identifiable name.
        return LocalCVDocument(
            raw_text="Email: candidate@example.com\nPhone: +852 6123 4567\nSkills\nPython",
            page_texts=(),
            ocr_lines=(),
            ocr_page_indexes=frozenset(),
        )

    service._extract_local_document = fake_extract  # type: ignore[method-assign]

    result = await service.parse_cv("resume.pdf")

    assert result["status"] == "fallback"
    assert result["parse_path"] == "privacy_rule_fallback"
    assert result["structured_data"]["email"] == "candidate@example.com"
    assert llm.called is False


# Verifies image-only CV pages are OCRed locally with reusable redaction coordinates.
def test_scanned_pdf_uses_local_ocr_and_renders_masked_image(tmp_path: Path) -> None:
    source_document = pymupdf.open()
    source_page = source_document.new_page(width=900, height=360)
    source_page.insert_text((60, 80), "Alice Local", fontsize=28)
    source_page.insert_text((60, 140), "alice.local@example.com", fontsize=24)
    source_page.insert_text((60, 200), "+852 6123 4567", fontsize=24)
    source_page.insert_text((60, 280), "Python Engineer", fontsize=24)
    raster_bytes = source_page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
    source_document.close()

    scan_path = tmp_path / "scanned-candidate.pdf"
    scan_document = pymupdf.open()
    scan_page = scan_document.new_page(width=900, height=360)
    scan_page.insert_image(scan_page.rect, stream=raster_bytes)
    scan_document.save(scan_path)
    scan_document.close()

    local_document = extract_local_cv_document(scan_path)
    values = contact_values_for_redaction(local_document.raw_text)
    image_urls = render_redacted_pdf_pages_as_data_urls(
        str(scan_path),
        max_pages=1,
        pii_values=values,
        ocr_lines=local_document.ocr_lines,
    )

    assert local_document.ocr_page_indexes == frozenset({0})
    assert "alice.local@example.com" in local_document.raw_text
    assert len(local_document.ocr_lines) >= 3
    assert image_urls[0].startswith("data:image/")


# Verifies local NER names can augment header heuristics without external requests.
def test_local_ner_returns_unique_names_in_document_order(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNERModel:
        """Returns deterministic local person entities for NER integration testing."""

        # Simulates GLiNER person extraction without loading model weights.
        def predict_entities(
            self,
            _: str,
            __: list[str],
            *,
            threshold: float,
        ) -> list[dict[str, object]]:
            assert threshold > 0
            return [
                {"text": "Alice Chan", "start": 20, "label": "person"},
                {"text": "1 Example Road", "start": 50, "label": "full address"},
                {"text": "Bob Lee", "start": 80, "label": "person name"},
                {"text": "Alice Chan", "start": 100, "label": "person"},
            ]

    monkeypatch.setattr(local_ner_module.settings, "cv_local_ner_enabled", True)
    monkeypatch.setattr(local_ner_module, "_NER_MODEL", FakeNERModel())
    monkeypatch.setattr(local_ner_module, "_NER_LOAD_FAILED", False)

    local_pii = local_ner_module.detect_local_pii("Local CV text")

    assert local_pii.names == ("Alice Chan", "Bob Lee")
    assert local_pii.sensitive_values == ("1 Example Road",)
