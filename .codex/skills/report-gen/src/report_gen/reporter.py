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

# Shorter radar-axis labels so they stay inside the chart box.
_RADAR_SHORT = {
    "Education and Certification": "Education",
    "Role and Seniority Fit": "Seniority",
    "Evidence and Impact": "Evidence",
    "Relevant Experience": "Experience",
    "Core Skill Match": "Core skills",
    "Job-Specific Match": "Job-specific",
    "Work Authorization": "Work auth",
}


class ReporterService:
    """Builds candidate PDF one-pagers and Excel comparison reports."""

    # Generates a candidate PDF report with radar, dimension details, and interview questions.
    def generate_candidate_one_pager_pdf(
        self,
        output_path: str,
        *,
        display_label: str | None = None,
        candidate_name: str | None = None,
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
        content_w = width - 2 * margin
        y = height - margin

        def new_page_if_needed(needed: float) -> None:
            nonlocal y
            if y - needed < margin + 18:
                self._footer(c, width, margin, version)
                c.showPage()
                y = height - margin

        # Header
        c.setFont(_BOLD, 15)
        c.drawString(margin, y, "Candidate Match")
        y -= 18
        c.setFont(_CJK, 10)
        _ = candidate_name
        y = self._draw_wrapped(c, margin, y, str(display_label or "Application"), _CJK, 10, content_w, 13)
        y = self._draw_wrapped(
            c, margin, y, f"Applied Position: {position_name}", _CJK, 9, content_w, 12
        )
        c.setFont(_CJK, 9)
        c.drawString(margin, y, f"Report Date: {report_date.strftime('%Y-%m-%d')}")
        y -= 22

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
        card_w = (content_w - 3 * gap) / 4
        card_h = 42
        for i, (label, value) in enumerate(cards):
            x = margin + i * (card_w + gap)
            c.setFillColor(colors.Color(0.969, 0.973, 0.98))
            c.setStrokeColor(colors.Color(0.886, 0.91, 0.941))
            c.rect(x, y - card_h, card_w, card_h, fill=1, stroke=1)
            c.setFillColor(colors.black)
            inner_w = card_w - 16
            label_size = 8
            while label_size > 6 and pdfmetrics.stringWidth(label, _CJK, label_size) > inner_w:
                label_size -= 0.5
            c.setFont(_CJK, label_size)
            c.drawString(x + 8, y - 13, label)
            value_size = 15
            while value_size > 8 and pdfmetrics.stringWidth(value, _REGULAR, value_size) > inner_w:
                value_size -= 1
            c.setFont(_REGULAR, value_size)
            c.drawString(x + 8, y - 34, value)
        y -= card_h + 14

        # Radar Profile + side panels
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Radar Profile")
        y -= 16

        radar_items = self._radar_items(radar_dimensions, dimension_scores)
        radar_size = 220
        side_x = margin + radar_size + 16
        side_w = width - margin - side_x
        c.setStrokeColor(colors.black)
        c.rect(margin, y - radar_size, radar_size, radar_size, fill=0, stroke=1)
        self._draw_radar(c, margin + 8, y - radar_size + 8, radar_size - 16, radar_items)
        side_y = y
        if top_strengths:
            c.setFont(_BOLD, 10)
            c.drawString(side_x, side_y, "Top Strengths")
            side_y -= 13
            for strength in top_strengths[:4]:
                side_y = self._draw_wrapped(c, side_x, side_y, f"- {strength}", _CJK, 8, side_w, 11)
                side_y -= 3
            side_y -= 6
        if key_gaps:
            c.setFont(_BOLD, 10)
            c.drawString(side_x, side_y, "Key Gaps")
            side_y -= 13
            for gap in key_gaps[:4]:
                side_y = self._draw_wrapped(c, side_x, side_y, f"- {gap}", _CJK, 8, side_w, 11)
                side_y -= 3
            side_y -= 6
        if eligibility:
            status = eligibility.get("status", "")
            c.setFont(_BOLD, 10)
            side_y = self._draw_wrapped(c, side_x, side_y, f"Eligibility: {status}", _BOLD, 10, side_w, 12)
            side_y -= 4
            for result in (eligibility.get("results") or [])[:5]:
                line = f"- {result.get('rule_id', '')}: {result.get('status', '')}"
                if result.get("reason_code"):
                    line += f" ({result.get('reason_code')})"
                side_y = self._draw_wrapped(c, side_x, side_y, line, _CJK, 8, side_w, 11)
                side_y -= 3
        y -= radar_size + 16

        # Dimension Details
        new_page_if_needed(60)
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Dimension Details")
        y -= 16
        details = self._dimension_details(radar_dimensions, dimension_scores)
        for detail in details:
            value_text = f"{detail['score']:.1f}" if detail["score"] is not None else "N/A"
            status_text = str(detail.get("status") or "")
            weight_text = f"weight {detail['weight']:.2f}" if detail.get("weight") is not None else ""
            metrics = "   ".join(part for part in (value_text, status_text, weight_text) if part)
            c.setFont(_REGULAR, 8)
            metrics_w = pdfmetrics.stringWidth(metrics, _REGULAR, 8) if metrics else 0
            label_w = max(90.0, content_w - 18 - metrics_w)
            label_lines = self._wrap_to_width(str(detail["label"]), _CJK, 9, label_w)
            header_h = max(26.0, 10 + len(label_lines) * 11)
            reason = str(detail.get("reasoning") or "").strip()
            reason_h = self._text_height(reason, _CJK, 8, content_w - 12, 11) if reason else 0
            gaps_h = 0.0
            wrapped_gaps: list[list[str]] = []
            for gap in detail.get("gaps") or []:
                lines = self._wrap_to_width(f"- {gap}", _CJK, 8, content_w - 22)
                wrapped_gaps.append(lines)
                gaps_h += len(lines) * 11 + 3
            needed = header_h + 8 + reason_h + (6 if reason else 0) + gaps_h + 10
            new_page_if_needed(needed)
            c.setStrokeColor(colors.Color(0.886, 0.91, 0.941))
            c.setFillColor(colors.white)
            c.rect(margin, y - header_h, content_w, header_h, fill=1, stroke=1)
            c.setFillColor(colors.black)
            label_y = y - 12
            for line in label_lines:
                c.setFont(_CJK, 9)
                c.drawString(margin + 6, label_y, line)
                label_y -= 11
            if metrics:
                c.setFont(_REGULAR, 8)
                c.drawRightString(margin + content_w - 6, y - 12, metrics)
            y -= header_h + 8
            if reason:
                y = self._draw_wrapped(c, margin + 6, y, reason, _CJK, 8, content_w - 12, 11)
                y -= 6
            for lines in wrapped_gaps:
                c.setFont(_CJK, 8)
                for line in lines:
                    c.drawString(margin + 14, y, line)
                    y -= 11
                y -= 3
            y -= 8

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
            text = f"{index}. {question.get('question', '')}"
            meta = f"Priority: {question.get('priority', '')}"
            if question.get("template_id"):
                meta += f"  Template: {question.get('template_id')}"
            needed = self._text_height(text, _CJK, 9, content_w - 12, 12) + 16
            new_page_if_needed(needed)
            y = self._draw_wrapped(c, margin + 6, y, text, _CJK, 9, content_w - 12, 12)
            y = self._draw_wrapped(c, margin + 16, y, meta, _CJK, 8, content_w - 22, 11)
            y -= 8

        # Education
        new_page_if_needed(40)
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Education")
        y -= 16
        if education:
            for item in education[:4]:
                line = f"- {item.get('school', '')} | {item.get('degree', '')} | {item.get('major', '')} | {item.get('period', item.get('year', ''))}"
                y = self._draw_wrapped(c, margin + 6, y, line, _CJK, 9, content_w - 12, 12)
                y -= 3
        else:
            c.setFont(_CJK, 9)
            c.drawString(margin + 6, y, "- None")
            y -= 14
        y -= 6

        # Experience
        new_page_if_needed(40)
        c.setFont(_BOLD, 12)
        c.drawString(margin, y, "Experience")
        y -= 16
        if experience:
            for item in experience[:5]:
                period = item.get("period", "")
                if not period:
                    period = f"{item.get('start_date', '')} ~ {item.get('end_date', 'Present')}"
                line = f"- {item.get('company', '')} | {item.get('job_title', item.get('title', ''))} | {period}"
                y = self._draw_wrapped(c, margin + 6, y, line, _CJK, 9, content_w - 12, 12)
                y -= 3
        else:
            c.setFont(_CJK, 9)
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
                "Ref no",
                "Application no",
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
                    item.get("refno") or "",
                    item.get("appno") or item.get("display_label") or "",
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

    # Writes a browser HTML board with ranking and SVG radar charts (no personal names).
    def generate_screening_board_html(
        self,
        output_path: str,
        *,
        position_name: str,
        rows: list[dict[str, Any]],
        report_date: datetime,
        refno: str | None = None,
    ) -> None:
        from report_gen.html_board import write_screening_board

        write_screening_board(
            output_path,
            position_name=position_name,
            rows=rows,
            report_date=report_date,
            refno=refno,
        )

    # Writes one candidate HTML match page (application-no. filename).
    def generate_candidate_match_html(
        self,
        output_path: str,
        *,
        row: dict[str, Any],
        position_name: str,
        report_date: datetime,
    ) -> None:
        from report_gen.html_board import write_candidate_match_html

        write_candidate_match_html(
            output_path,
            row=row,
            position_name=position_name,
            report_date=report_date,
        )

    # Wraps text to a pixel width; keeps Latin words intact and splits CJK by character.
    @staticmethod
    def _wrap_to_width(text: str, font: str, size: float, max_width: float) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return [""]
        if max_width <= 0:
            return [raw]

        def width_of(value: str) -> float:
            return pdfmetrics.stringWidth(value, font, size)

        def split_long_token(token: str) -> list[str]:
            parts: list[str] = []
            current = ""
            for char in token:
                trial = current + char
                if current and width_of(trial) > max_width:
                    parts.append(current)
                    current = char
                else:
                    current = trial
            if current:
                parts.append(current)
            return parts or [""]

        tokens: list[str] = []
        buf = ""
        for char in raw:
            if char == "\n":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append("\n")
            elif ord(char) > 0x2E80:
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(char)
            elif char == " ":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(" ")
            else:
                buf += char
        if buf:
            tokens.append(buf)

        lines: list[str] = []
        current = ""
        for token in tokens:
            if token == "\n":
                lines.append(current.rstrip())
                current = ""
                continue
            pieces = split_long_token(token) if width_of(token) > max_width else [token]
            for piece in pieces:
                trial = current + piece
                if current and width_of(trial) > max_width:
                    lines.append(current.rstrip())
                    current = piece.lstrip()
                else:
                    current = trial
        if current:
            lines.append(current.rstrip())
        return [line for line in lines if line != ""] or [""]

    # Character-count wrap kept for older callers; prefers word-safe width wrap.
    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        approx_width = max(40.0, float(max_chars) * 4.2)
        return ReporterService._wrap_to_width(text, _CJK, 8, approx_width)

    # Height needed to draw wrapped text.
    @staticmethod
    def _text_height(text: str, font: str, size: float, max_width: float, line_height: float) -> float:
        if not str(text or "").strip():
            return 0.0
        return len(ReporterService._wrap_to_width(text, font, size, max_width)) * line_height

    # Draws wrapped text lines starting at (x, y) and returns the next y position.
    @staticmethod
    def _draw_wrapped(
        c: canvas.Canvas,
        x: float,
        y: float,
        text: str,
        font: str,
        size: float,
        max_width: float,
        line_height: float,
    ) -> float:
        c.setFont(font, size)
        for line in ReporterService._wrap_to_width(text, font, size, max_width):
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
        radius = size / 2 - 42
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
                short = _RADAR_SHORT.get(label, label)
                label_lines = ReporterService._wrap_to_width(short, _CJK, 6.5, 70)
                label_lines.append("(N/A)")
            else:
                c.setFillColor(colors.Color(0.01, 0.518, 0.78))
                c.circle(pt[0], pt[1], 2.8, stroke=0, fill=1)
                c.setFillColor(colors.black)
                c.setFont(_REGULAR, 6.5)
                c.drawCentredString(pt[0], pt[1] + 5, f"{value:.0f}")
                short = _RADAR_SHORT.get(label, label)
                label_lines = ReporterService._wrap_to_width(short, _CJK, 6.5, 70)
            lx, ly = polar((radius + 16) / radius, i)
            c.setFont(_CJK, 6.5)
            line_h = 8
            start_y = ly + (len(label_lines) - 1) * line_h / 2
            for offset, line in enumerate(label_lines):
                ty = start_y - offset * line_h
                if abs(lx - center_x) < 8:
                    c.drawCentredString(lx, ty, line)
                elif lx < center_x:
                    c.drawRightString(lx, ty, line)
                else:
                    c.drawString(lx, ty, line)

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
                    "gaps": [],
                }
                gaps: list[str] = []
                for item in dim.get("gaps") or []:
                    text = item.get("text", "") if isinstance(item, dict) else str(item)
                    if text:
                        gaps.append(str(text))
                detail["gaps"] = gaps
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
        text = f"Disclaimer: This report supports screening only and does not constitute a hiring decision. Version: {version}"
        ReporterService._draw_wrapped(c, margin, 28, text, _CJK, 7, width - 2 * margin, 9)