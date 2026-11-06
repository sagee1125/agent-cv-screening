# The portrait's application-form enrichment: parser extracts the two
# post-title/org columns; the portrait masks the form with the CV's name
# detections, verifies form quotes against page 0, and re-keys its cache on
# the form text so an unchanged CV with a corrected form regenerates.
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pymupdf

REPO = Path(__file__).resolve().parents[3]


def _records():
    spec = importlib.util.spec_from_file_location(
        "records_mod", REPO / ".codex" / "skills" / "jas-import" / "src" / "jas_import" / "records.py"
    )
    sys.path.insert(0, str(REPO / ".codex" / "skills" / "_shared" / "src"))
    sys.path.insert(0, str(REPO / ".codex" / "skills" / "jas-import" / "src"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["records_mod"] = module
    spec.loader.exec_module(module)
    return module


def test_parser_extracts_both_employment_columns() -> None:
    records = _records()
    html = """
    <table id="f-list" class="listTable job-detail-table">
    <thead><tr>
      <th>No.</th><th>Application no.</th><th>Post applied for</th>
      <th>Online job application form summary (printable version)</th><th>Status</th>
      <th>Post title and organization of current / most recent full-time job</th>
      <th>Post title and organization of last / second last full-time job</th>
      <th>Curriculum vitae</th>
    </tr></thead>
    <tbody><tr>
      <td>1</td><td>9900001</td><td>Research Assistant</td><td>p</td><td>TBC</td>
      <td>Research Assistant / Test Lab</td>
      <td>Project Coordinator<br/>Chencheng Global</td>
      <td><a href="file.php?t=cv&amp;id=9900001&amp;refno=999990001">cv</a></td>
    </tr></tbody></table>
    <table id="f-list"><tr><td class="f-header">Reference number</td><td>9</td></tr></table>
    """
    job = records.parse_job_html(html, base_url="https://jobs.polyu.edu.hk/internal/records.php?refno=999990001")
    cand = job.candidates[0]
    assert cand.form_employment == "Research Assistant / Test Lab | Project Coordinator Chencheng Global"


def _portrait_service(tmp_path, responses):
    sys.path.insert(0, str(REPO / ".codex" / "skills" / "cv-parser" / "src"))
    sys.path.insert(0, str(REPO / ".codex" / "skills" / "cv-portrait" / "src"))
    from cv_portrait.service import PortraitService
    from screening_core.hash_cache import HashCache

    class Stub:
        def __init__(self):
            self.calls = 0

        async def chat_completion(self, *_a, **_k):
            self.calls += 1
            return {"model": "glm-4-flash", "parsed": responses[min(self.calls - 1, len(responses) - 1)]}

    return PortraitService(llm_client=Stub(), cache=HashCache(str(tmp_path)))


def _write_cv(tmp_path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 90), "Yu, Ziheng")
    page.insert_text((72, 120), "Built tutoring platform with Python in 2025.")
    document.save(tmp_path / "cv.pdf")
    document.close()
    return tmp_path / "cv.pdf"


def test_form_quote_masks_name_and_verifies_on_page0(tmp_path) -> None:
    service = _portrait_service(tmp_path, [{
        "headline": "以教學平台開發為主",
        "overview": [], "capability_tags": ["Python"], "strengths": [], "gaps": [],
        "reliability_flags": [], "interview_probes": [],
    }])
    # Company named after the candidate: must be masked before anything is sent.
    form = "Head Tutor / Yu Ziheng Education Ltd"
    captured = {}
    import cv_portrait.service as svc

    original_mask = svc.mask_pii_text_aggressive
    def spy_mask(text, names=None, sensitive=None):
        if "Education Ltd" in text:
            captured["form_masked_names"] = list(names or [])
        return original_mask(text, names, sensitive)
    svc.mask_pii_text_aggressive = spy_mask
    try:
        asyncio.run(service.build_portrait(str(_write_cv(tmp_path)), form_employment=form))
    finally:
        svc.mask_pii_text_aggressive = original_mask
    masked_with = " ".join(captured.get("form_masked_names") or [])
    assert "Ziheng" in masked_with and "Yu" in masked_with, "CV name must mask the form"


def test_same_cv_different_form_regenerates(tmp_path) -> None:
    payload_a = {
        "headline": "以教學平台開發為主", "overview": [], "capability_tags": ["Python"],
        "strengths": [{"text": "t", "evidence": [{"page": 0, "quote": "Head Tutor"}]}],
        "gaps": [], "reliability_flags": [], "interview_probes": [],
    }
    service = _portrait_service(tmp_path, [payload_a])
    cv = str(_write_cv(tmp_path))
    first = asyncio.run(service.build_portrait(cv, form_employment="Head Tutor / Test Ltd"))
    assert first["cache_hit"] is False
    # Form quote from page 0 verifies against the masked form.
    evidence = first["portrait"]["strengths"][0]["evidence"][0]
    assert evidence["page"] == 0 and evidence["verified"] is True
    # Same CV + same form: cache hit, no second LLM call.
    again = asyncio.run(service.build_portrait(cv, form_employment="Head Tutor / Test Ltd"))
    assert again["cache_hit"] is True and service.llm_client.calls == 1
    # Same CV + corrected form: regenerates once.
    corrected = asyncio.run(service.build_portrait(cv, form_employment="Senior Tutor / Test Ltd"))
    assert corrected["cache_hit"] is False and service.llm_client.calls == 2
