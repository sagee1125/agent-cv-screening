# Unit tests for salary and HKID PII detection and masking.
from __future__ import annotations

import sys
from pathlib import Path

# backend/tests/unit/test_pii_patterns.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_SRC = REPO_ROOT / ".codex" / "skills" / "_shared" / "src"
CV_PARSER_SRC = REPO_ROOT / ".codex" / "skills" / "cv-parser" / "src"
for path in (SHARED_SRC, CV_PARSER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cv_parser.pii import (
    HKID_PATTERN,
    SALARY_PATTERN,
    contact_values_for_redaction,
    detect_contact_entities,
    extract_contact_hints_local,
    mask_pii_text,
)


# HKID pattern matches standard format with check digit in parentheses.
def test_hkid_pattern_matches_standard_format() -> None:
    assert HKID_PATTERN.search("AB123456(7)")
    assert HKID_PATTERN.search("A123456(0)")
    assert HKID_PATTERN.search("Z987654(A)")


# HKID pattern matches with a space before the check-digit parentheses.
def test_hkid_pattern_matches_space_before_parentheses() -> None:
    assert HKID_PATTERN.search("AB123456 (7)")
    assert HKID_PATTERN.search("HKID: A123456 (0)")


# HKID pattern matches without parentheses (appended check digit).
def test_hkid_pattern_matches_without_parentheses() -> None:
    assert HKID_PATTERN.search("My ID is AB1234567")
    assert HKID_PATTERN.search("ID: A1234560")


# HKID pattern does not match ordinary numbers.
def test_hkid_pattern_rejects_plain_numbers() -> None:
    assert not HKID_PATTERN.search("12345678")
    assert not HKID_PATTERN.search("Phone: 98765432")


# Salary pattern matches common Hong Kong salary expressions.
def test_salary_pattern_matches_hkd() -> None:
    assert SALARY_PATTERN.search("HKD 25,000 per month")
    assert SALARY_PATTERN.search("HK$30,000/month")
    assert SALARY_PATTERN.search("HK$ 45,000 monthly")


# Salary pattern matches plain-digit amounts without thousand separators.
def test_salary_pattern_matches_plain_digit_amounts() -> None:
    assert SALARY_PATTERN.search("HKD 10000 per month")
    assert SALARY_PATTERN.search("HK$30000")
    assert SALARY_PATTERN.search("$5000/mo")
    match = SALARY_PATTERN.search("HKD 10000 per month")
    assert match is not None
    assert "10000" in match.group(0)
    assert "100" != match.group(0).strip()[-5:]


# Salary pattern matches USD and bare dollar amounts.
def test_salary_pattern_matches_usd_and_bare_dollar() -> None:
    assert SALARY_PATTERN.search("USD 60,000 per annum")
    assert SALARY_PATTERN.search("$5,000/mo")
    assert SALARY_PATTERN.search("Expected salary: $30,000")


# Salary pattern matches RMB and annual suffixes.
def test_salary_pattern_matches_rmb_and_annual() -> None:
    assert SALARY_PATTERN.search("RMB 15,000 monthly")
    assert SALARY_PATTERN.search("CNY 200,000 per annum")
    assert SALARY_PATTERN.search("€40,000 annually")


# detect_contact_entities finds HKID in CV text.
def test_detect_finds_hkid_in_cv_text() -> None:
    raw_text = "Name: Chan Tai Man\nHKID: AB123456(7)\nEmail: chan@example.com"
    entities = detect_contact_entities(raw_text)
    kinds = {entity.kind for entity in entities}
    assert "hkid" in kinds
    hkid_entity = next(e for e in entities if e.kind == "hkid")
    assert hkid_entity.value == "AB123456(7)"


# detect_contact_entities finds salary expressions in CV text.
def test_detect_finds_salary_in_cv_text() -> None:
    raw_text = "Current salary: HKD 35,000 per month\nExpected: HK$40,000"
    entities = detect_contact_entities(raw_text)
    kinds = {entity.kind for entity in entities}
    assert "salary" in kinds


# mask_pii_text replaces HKID with a placeholder.
def test_mask_replaces_hkid() -> None:
    raw_text = "HKID: AB123456(7)\nEngineer at ACME"
    masked = mask_pii_text(raw_text)
    assert "AB123456(7)" not in masked
    assert "[HKID_REDACTED]" in masked
    assert "Engineer at ACME" in masked


# mask_pii_text replaces salary with a placeholder.
def test_mask_replaces_salary() -> None:
    raw_text = "Salary: HKD 25,000 per month\nPython developer"
    masked = mask_pii_text(raw_text)
    assert "HKD 25,000" not in masked
    assert "[SALARY_REDACTED]" in masked
    assert "Python developer" in masked


# extract_contact_hints_local includes hkid and salary fields.
def test_extract_hints_includes_hkid_and_salary() -> None:
    raw_text = "HKID: AB123456(7)\nSalary: HKD 30,000 per month"
    hints = extract_contact_hints_local(raw_text)
    assert hints["hkid"] == "AB123456(7)"
    assert hints["salary"] is not None
    assert "30,000" in hints["salary"]


# contact_values_for_redaction includes HKID and salary values for PDF redaction.
def test_contact_values_includes_hkid_and_salary() -> None:
    raw_text = "HKID: AB123456(7)\nSalary: HKD 30,000 per month\nEmail: a@b.com"
    values = contact_values_for_redaction(raw_text)
    assert "AB123456(7)" in values
    assert any("30,000" in v for v in values)
    assert "a@b.com" in values


# Salary and HKID do not interfere with existing PII detection.
def test_hkid_and_salary_coexist_with_other_pii() -> None:
    raw_text = (
        "Chan Tai Man\n"
        "Email: david.chan@example.com\n"
        "Phone: +852 9876 5432\n"
        "HKID: AB123456(7)\n"
        "Salary: HKD 25,000 per month\n"
        "LinkedIn: linkedin.com/in/davidchan\n"
        "Engineer at ACME 2021 - 2024"
    )
    entities = detect_contact_entities(raw_text)
    kinds = {entity.kind for entity in entities}
    assert "name" in kinds
    assert "email" in kinds
    assert "phone" in kinds
    assert "url" in kinds
    assert "hkid" in kinds
    assert "salary" in kinds
    masked = mask_pii_text(raw_text)
    assert "AB123456(7)" not in masked
    assert "HKD 25,000" not in masked
    assert "david.chan@example.com" not in masked
    assert "Engineer at ACME" in masked
