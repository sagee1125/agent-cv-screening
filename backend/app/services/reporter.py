# Generates candidate PDF one-pagers and Excel comparison reports for the Reporter service.
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# Register the built-in CJK font so Chinese candidate content renders correctly.
if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

_CJK = "STSong-Light"
_BOLD = "Helvetica-Bold"
_REGULAR = "Helvetica"

# Canonical display labels for scorer and matching-engine dimension ids.
_DIMENSION_LABELS = {
    "skill_match": "Skill Match",
    "experience_match": "Experience Match",
    "education_match": "Education Match",
    "research_quality": "Research Quality",
    "experience_quality": "Experience Quality",
    "language_match": "Language",
    "work_authorization_match": "Work Authorization",
    "location_match": "Location",
    "core_skill_match": "Core Skill Match",
    "relevant_experience": "Relevant Experience",
    "role_seniority_fit": "Role and Seniority Fit",
    "evidence_impact": "Evidence and Impact",
    "education_certification": "Education and Certification",
    "job_specific_match": "Job-Specific Match",
}


class ReporterService:
    """Builds candidate PDF one-pagers and Excel comparison reports."""

    # Generates a candidate PDF report with radar, dimension details, and interview questions.
    def generate_candidate_one_pager_pdf(
        self,
        output_path: str,
        *,
        candidate_name: str,
        position_name: str,
        report_date: datetime,
        total_score: float,
        tier: str,
        rank: int,
        education: list[dict[str, Any]],
        experience: list[dict[str, Any]],
        skill_hit: list[Any],
        skill_miss: list[Any],
        hit_rate: float,
        dimension_scores: dict[str, float],
        interview_suggestions: list[dict[str, str]],
        version: str,
        radar_dimensions: list[dict[str, Any]] | None = None,
        interview_questions: list[dict[str, Any]] | None = None,
        eligibility: dict[str, Any] | None = None,
        evidence_confidence: float | None = None,
        fit_band: str | None = None,
        top_strengths: list[str] | None = None,
        key_gaps: list[str] | None = None,
    ) -> None:
        file_path = Path(output_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        c = canvas.Canvas(str(file_path), pagesize=A4)
        width, height = A4
        margin = 40
        y = height - margin

        def new_page_if_needed(needed: float) -> None:
            nonlocal y
            if y - needed < margin:
                self._footer(c, width, margin, version)
                c.showPage()
                y = height - margin

        # Header
        c.setFont(_BOLD, 15)
        c.drawString(margin, y, "Candidate Match")
        y -= 20
        c.setFont(_CJK, 11)
        c.drawString(margin, y, str(candidate_name))
        c.setFont(_CJK, 9)
        c.drawString(margin + 180, y, f"Applied Position: {position_name}")
        y -= 13
        c.drawString(margin, y, f"Report Date: {report_date.strftime('%Y-%m-%d')}")
        y -= 24

        # Summary stat cards
        cards = [
            ("Match Score", f"{float(total_score):.2f}"),
            ("Tier", str(tier)),
            ("Rank", str(rank) if rank else "-"),
            (
                "Evidence Confidence",
                f"{float(evidence_confidence):.0f}" if evidence_confidence is not None else (str(fit_band) if fit_band else "-"),
            ),
        ]
        gap = 10
        card_w = (width - 2 * margin - 3 * gap) / 4
        card_h = 42
        for i, (label, value) in enumerate(cards):
            x = margin + i * (card_w + gap)
            c.setFillColor(colors.Color(0.969, 0.973, 0.98))
            c.setStrokeColor(colors.Color(0.886, 0.91, 0.941))
            c.rect(x, y - card_h, card_w, card_h, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont(_CJK, 8)
            c.drawString(x + 8, y - 13, label)
            c.setFont(_REGULAR, 15)
            c.drawString(x + 8, y - 34, value)
        y -= card_h + 14

        # Radar Profile + side panels
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Radar Profile")
        y -= 16

        radar_items = self._radar_items(radar_dimensions, dimension_scores)
        radar_size = 220
        c.setStrokeColor(colors.black)
        c.rect(margin, y - radar_size, radar_size, radar_size, fill=0, stroke=1)
        self._draw_radar(c, margin + 12, y - radar_size + 12, radar_size - 24, radar_items)
        side_x = margin + radar_size + 16
        side_w = width - margin - side_x
        side_y = y
        if top_strengths:
            c.setFont(_BOLD, 10)
            c.drawString(side_x, side_y, "Top Strengths")
            side_y -= 12
            c.setFont(_CJK, 8)
            for strength in top_strengths[:4]:
                side_y = self._draw_wrapped(c, side_x + 4, side_y, f"- {strength}", _CJK, 8, 62, 10)
                side_y -= 2
            side_y -= 6
        if key_gaps:
            c.setFont(_BOLD, 10)
            c.drawString(side_x, side_y, "Key Gaps")
            side_y -= 12
            c.setFont(_CJK, 8)
            for gap in key_gaps[:4]:
                side_y = self._draw_wrapped(c, side_x + 4, side_y, f"- {gap}", _CJK, 8, 62, 10)
                side_y -= 2
            side_y -= 6
        if eligibility:
            status = eligibility.get("status", "")
            c.setFont(_BOLD, 10)
            c.drawString(side_x, side_y, f"Eligibility: {status}")
            side_y -= 12
            c.setFont(_CJK, 8)
            for result in (eligibility.get("results") or [])[:5]:
                line = f"- {result.get('rule_id', '')}: {result.get('status', '')}"
                if result.get("reason_code"):
                    line += f" ({result.get('reason_code')})"
                side_y = self._draw_wrapped(c, side_x + 4, side_y, line, _CJK, 8, 62, 10)
                side_y -= 2
        y -= radar_size + 16

        # Dimension Details
        new_page_if_needed(60)
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Dimension Details")
        y -= 16
        details = self._dimension_details(radar_dimensions, dimension_scores)
        for detail in details:
            needed = 34 + len(detail.get("gaps", [])) * 10
            new_page_if_needed(needed)
            c.setStrokeColor(colors.Color(0.886, 0.91, 0.941))
            c.setFillColor(colors.white)
            c.rect(margin, y - 30, width - 2 * margin, 30, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont(_CJK, 9)
            c.drawString(margin + 6, y - 12, detail["label"])
            value_text = f"{detail['score']:.1f}" if detail["score"] is not None else "N/A"
            status_text = detail.get("status", "")
            weight_text = f"weight {detail['weight']:.2f}" if detail.get("weight") is not None else ""
            c.setFont(_REGULAR, 9)
            c.drawRightString(margin + 200, y - 12, value_text)
            c.setFont(_CJK, 8)
            c.drawRightString(margin + 270, y - 12, status_text)
            c.drawRightString(margin + width - 2 * margin - 6, y - 12, weight_text)
            y -= 34
            if detail.get("reasoning"):
                c.setFont(_CJK, 8)
                y = self._draw_wrapped(c, margin + 6, y, detail["reasoning"], _CJK, 8, 96, 10)
                y -= 2
            for gap in detail.get("gaps", []):
                c.setFont(_CJK, 8)
                y = self._draw_wrapped(c, margin + 16, y, f"- {gap}", _CJK, 8, 90, 10)
                y -= 2
            y -= 6

        # Suggested Interview Questions
        new_page_if_needed(40)
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Suggested Interview Questions")
        y -= 16
        questions = interview_questions if interview_questions else [
            {
                "question": f"[{s.get('severity', 'low')}] {s.get('text', '')}",
                "priority": s.get("severity", ""),
                "template_id": s.get("rule_id", ""),
            }
            for s in interview_suggestions
        ]
        for index, question in enumerate(questions, start=1):
            text = str(question.get("question", ""))
            wrapped = self._wrap_text(text, 100)
            needed = len(wrapped) * 11 + 16
            new_page_if_needed(needed)
            c.setFont(_CJK, 9)
            y = self._draw_wrapped(c, margin + 6, y, f"{index}. {text}", _CJK, 9, 100, 11)
            meta = f"Priority: {question.get('priority', '')}"
            if question.get("template_id"):
                meta += f"  Template: {question.get('template_id')}"
            c.setFont(_CJK, 8)
            c.drawString(margin + 20, y, meta)
            y -= 4
            y -= 8

        # Education
        new_page_if_needed(40)
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Education")
        y -= 16
        c.setFont(_CJK, 9)
        if education:
            for item in education[:4]:
                line = f"- {item.get('school', '')} | {item.get('degree', '')} | {item.get('major', '')} | {item.get('period', item.get('year', ''))}"
                y = self._draw_wrapped(c, margin + 6, y, line, _CJK, 9, 100, 12)
                y -= 2
        else:
            c.drawString(margin + 6, y, "- None")
            y -= 14
        y -= 6

        # Experience
        new_page_if_needed(40)
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Experience")
        y -= 16
        c.setFont(_CJK, 9)
        if experience:
            for item in experience[:5]:
                period = item.get("period", "")
                if not period:
                    period = f"{item.get('start_date', '')} ~ {item.get('end_date', 'Present')}"
                line = f"- {item.get('company', '')} | {item.get('job_title', item.get('title', ''))} | {period}"
                y = self._draw_wrapped(c, margin + 6, y, line, _CJK, 9, 100, 12)
                y -= 2
        else:
            c.drawString(margin + 6, y, "- None")
            y -= 14

        self._footer(c, width, margin, version)
        c.save()

    # Generates an Excel comparison report from ranked candidate rows.
    def generate_comparison_excel(
        self,
        output_path: str,
        *,
        position_name: str,
        report_date: datetime,
        rows: list[dict[str, Any]],
    ) -> None:
        file_path = Path(output_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Comparison"

        sheet.append([f"Position: {position_name}", f"Report Date: {report_date.strftime('%Y-%m-%d')}"])
        sheet.append([])
        sheet.append(
            [
                "Rank",
                "Name",
                "Total Score",
                "Skill Match",
                "Experience Match",
                "Education Match",
                "Research Quality",
                "Tier",
                "Interview Suggestion Summary",
            ]
        )
        for item in rows:
            sheet.append(
                [
                    item.get("rank"),
                    item.get("name"),
                    item.get("total_score"),
                    item.get("skill_match"),
                    item.get("experience_match"),
                    item.get("education_match"),
                    item.get("research_quality"),
                    item.get("tier"),
                    item.get("suggestion_summary"),
                ]
            )
        workbook.save(str(file_path))

    # Wraps text into lines of at most max_chars columns (CJK characters count double).
    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for char in str(text):
            if char == "\n":
                if current:
                    lines.append(current)
                    current = ""
                continue
            width = 2 if ord(char) > 0x2E80 else 1
            if len(current) + width > max_chars and current:
                lines.append(current)
                current = char
            else:
                current += char
        if current:
            lines.append(current)
        return lines or [""]

    # Draws wrapped text lines starting at (x, y) and returns the next y position.
    @staticmethod
    def _draw_wrapped(
        c: canvas.Canvas,
        x: float,
        y: float,
        text: str,
        font: str,
        size: float,
        max_chars: int,
        line_height: float,
    ) -> float:
        c.setFont(font, size)
        for line in ReporterService._wrap_text(text, max_chars):
            c.drawString(x, y, line)
            y -= line_height
        return y

    # Draws a dependency-free radar polygon for 0-100 scores (mirrors the frontend SVG).
    @staticmethod
    def _draw_radar(
        c: canvas.Canvas,
        x: float,
        y: float,
        size: float,
        items: list[tuple[str, float | None]],
    ) -> None:
        total = len(items)
        if total < 3:
            c.setFont(_CJK, 8)
            c.drawString(x, y + size / 2, "Not enough radar dimensions.")
            return
        center_x = x + size / 2
        center_y = y + size / 2
        radius = size / 2 - 30
        rings = (0.2, 0.4, 0.6, 0.8, 1.0)
        max_value = 100.0

        def angle_deg(index: int) -> float:
            return -90.0 + (360.0 / total) * index

        def polar(ratio: float, index: int) -> tuple[float, float]:
            rad = math.radians(angle_deg(index))
            return center_x + radius * ratio * math.cos(rad), center_y + radius * ratio * math.sin(rad)

        # Grid rings
        c.setStrokeColor(colors.Color(0.886, 0.91, 0.941))
        c.setLineWidth(1)
        for ring in rings:
            pts = [polar(ring, i) for i in range(total)]
            path = c.beginPath()
            path.moveTo(*pts[0])
            for pt in pts[1:]:
                path.lineTo(*pt)
            path.close()
            c.drawPath(path, stroke=1, fill=0)

        # Axis spokes
        for i in range(total):
            px, py = polar(1.0, i)
            c.line(center_x, center_y, px, py)

        # Data polygon
        data_points: list[tuple[float, float] | None] = []
        for i, (_, value) in enumerate(items):
            if value is None:
                data_points.append(None)
            else:
                ratio = min(1.0, max(0.0, float(value) / max_value))
                data_points.append(polar(ratio, i))
        valid = [p for p in data_points if p is not None]
        if len(valid) >= 3:
            path = c.beginPath()
            path.moveTo(*valid[0])
            for pt in valid[1:]:
                path.lineTo(*pt)
            path.close()
            c.setFillColor(colors.Color(0.055, 0.647, 0.914, alpha=0.25))
            c.setStrokeColor(colors.Color(0.01, 0.518, 0.78))
            c.setLineWidth(1.6)
            c.drawPath(path, stroke=1, fill=1)

        # Points, values, and labels
        for i, (label, value) in enumerate(items):
            pt = data_points[i]
            axis_x, axis_y = polar(1.0, i)
            if pt is None:
                c.setStrokeColor(colors.Color(0.796, 0.835, 0.882))
                c.setDash(2, 2)
                c.circle(axis_x, axis_y, 2.5, stroke=1, fill=0)
                c.setDash()
                label_text = f"{label} (N/A)"
            else:
                c.setFillColor(colors.Color(0.01, 0.518, 0.78))
                c.circle(pt[0], pt[1], 2.8, stroke=0, fill=1)
                c.setFillColor(colors.black)
                c.setFont(_REGULAR, 7)
                c.drawCentredString(pt[0], pt[1] + 4, f"{value:.0f}")
                label_text = label
            lx, ly = polar((radius + 12) / radius, i)
            c.setFont(_CJK, 7)
            anchor = "middle" if abs(lx - center_x) < 1 else ("start" if lx < center_x else "end")
            if anchor == "middle":
                c.drawCentredString(lx, ly, label_text)
            elif anchor == "start":
                c.drawString(lx, ly, label_text)
            else:
                c.drawRightString(lx, ly, label_text)

    # Builds radar items (label, score) from matching-detail or legacy dimension scores.
    @staticmethod
    def _radar_items(
        radar_dimensions: list[dict[str, Any]] | None,
        dimension_scores: dict[str, float],
    ) -> list[tuple[str, float | None]]:
        if radar_dimensions:
            items: list[tuple[str, float | None]] = []
            for dim in radar_dimensions:
                score = dim.get("score")
                items.append((str(dim.get("label", dim.get("dimension_id", ""))), None if score is None else float(score)))
            return items
        order = [
            "core_skill_match",
            "skill_match",
            "relevant_experience",
            "experience_match",
            "role_seniority_fit",
            "education_certification",
            "education_match",
            "evidence_impact",
            "research_quality",
            "experience_quality",
            "job_specific_match",
            "language_match",
            "work_authorization_match",
            "location_match",
        ]
        used = [(key, order.index(key)) for key in dimension_scores if key in order]
        used.sort(key=lambda item: item[1])
        return [
            (_DIMENSION_LABELS.get(key, key), float(dimension_scores[key]))
            for key, _ in used
        ]

    # Builds per-dimension detail rows with score, status, weight, reasoning, and gaps.
    @staticmethod
    def _dimension_details(
        radar_dimensions: list[dict[str, Any]] | None,
        dimension_scores: dict[str, float],
    ) -> list[dict[str, Any]]:
        if radar_dimensions:
            details: list[dict[str, Any]] = []
            for dim in radar_dimensions:
                reasoning = dim.get("reasoning") or {}
                detail: dict[str, Any] = {
                    "label": str(dim.get("label", dim.get("dimension_id", ""))),
                    "score": None if dim.get("score") is None else float(dim["score"]),
                    "status": str(dim.get("status", "")),
                    "weight": None if dim.get("normalized_weight") is None else float(dim["normalized_weight"]),
                    "reasoning": str(reasoning.get("summary", "")) if reasoning.get("summary") else "",
                    "gaps": [str(g.get("text", "")) for g in (dim.get("gaps") or []) if g.get("text")],
                }
                details.append(detail)
            return details
        return [
            {
                "label": _DIMENSION_LABELS.get(key, key),
                "score": float(value),
                "status": "",
                "weight": None,
                "reasoning": "",
                "gaps": [],
            }
            for key, value in dimension_scores.items()
        ]

    # Draws the footer disclaimer and version on the current page.
    @staticmethod
    def _footer(c: canvas.Canvas, width: float, margin: float, version: str) -> None:
        c.setFont(_CJK, 8)
        c.drawString(margin, 25, f"Disclaimer: This report supports screening only and does not constitute a hiring decision. Version: {version}")