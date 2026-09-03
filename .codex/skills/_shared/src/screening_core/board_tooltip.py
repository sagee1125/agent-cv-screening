# Builds the allow-listed radar tooltip payload that board rows may carry (no raw CV text).
from __future__ import annotations

from typing import Any

RADAR_TOOLTIP_SCHEMA_VERSION = "board-row/tooltip-v1"
RADAR_TOOLTIP_SUMMARY_MAX = 240
RADAR_TOOLTIP_GAPS_MAX = 3
RADAR_TOOLTIP_REQUIREMENTS_MAX = 3
RADAR_TOOLTIP_GAP_TEXT_MAX = 200


# Truncates a string to the character budget, appending an ellipsis when clipped.
def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# Counts matched CV evidence by section so HTML never carries raw CV sentences.
def evidence_section_counts(evidence: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "").strip()
        if section:
            counts[section] = counts.get(section, 0) + 1
    return counts


# Extracts a short display list from templated requirement/gap records.
def _short_list(values: Any, key: str, limit: int) -> list[str]:
    out: list[str] = []
    for item in values or []:
        text = _clip(item.get(key) if isinstance(item, dict) else item, RADAR_TOOLTIP_GAP_TEXT_MAX)
        if text:
            out.append(text)
    return out[:limit]


# Returns the allow-listed hover fields for one radar dimension record.
def radar_tooltip_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    status = item.get("status")
    if isinstance(status, str) and status:
        payload["status"] = status
    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        payload["confidence"] = float(confidence)
    reasoning = item.get("reasoning")
    if isinstance(reasoning, dict):
        summary = _clip(reasoning.get("summary"), RADAR_TOOLTIP_SUMMARY_MAX)
        if summary:
            payload["summary"] = summary
        facts = reasoning.get("facts")
        if isinstance(facts, dict):
            metric_keys = ("coverage_pct", "ownership_pct", "impact_pct")
            metrics = {
                key: float(facts[key])
                for key in metric_keys
                if isinstance(facts.get(key), (int, float)) and not isinstance(facts.get(key), bool)
            }
            if metrics:
                payload["evidence_metrics"] = metrics
    gaps = _short_list(item.get("gaps"), "text", RADAR_TOOLTIP_GAPS_MAX)
    if gaps:
        payload["gaps"] = gaps
        raw_gap_count = sum(
            1
            for gap in item.get("gaps") or []
            if isinstance(gap, dict) and _clip(gap.get("text"), RADAR_TOOLTIP_GAP_TEXT_MAX)
        )
        overflow = raw_gap_count - len(gaps)
        if overflow > 0:
            payload["gaps_overflow"] = overflow
    requirements = _short_list(item.get("requirements"), "text", RADAR_TOOLTIP_REQUIREMENTS_MAX)
    if requirements:
        payload["requirements"] = requirements
    counts = evidence_section_counts(item.get("evidence"))
    if counts:
        payload["evidence_sections"] = counts
    return payload


# Converts matching detail radar dimensions into the public additive board-row axes.
def public_radar_dimensions(detail: dict[str, Any]) -> list[dict[str, Any]]:
    axes: list[dict[str, Any]] = []
    for item in detail.get("radar_dimensions") or []:
        if not isinstance(item, dict):
            continue
        axis: dict[str, Any] = {
            "id": item.get("dimension_id") or item.get("id"),
            "label": item.get("label"),
            "score": item.get("score"),
        }
        axis.update(radar_tooltip_payload(item))
        axes.append(axis)
    return axes


__all__ = [
    "RADAR_TOOLTIP_GAPS_MAX",
    "RADAR_TOOLTIP_REQUIREMENTS_MAX",
    "RADAR_TOOLTIP_SCHEMA_VERSION",
    "RADAR_TOOLTIP_SUMMARY_MAX",
    "evidence_section_counts",
    "public_radar_dimensions",
    "radar_tooltip_payload",
]
