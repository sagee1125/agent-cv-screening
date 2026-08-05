from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


class ReporterService:
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
    ) -> None:
        file_path = Path(output_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        c = canvas.Canvas(str(file_path), pagesize=A4)
        width, height = A4
        y = height - 40

        # Header
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, f"候选人: {candidate_name}")
        y -= 18
        c.setFont("Helvetica", 11)
        c.drawString(40, y, f"申请职位: {position_name}")
        c.drawString(320, y, f"报告日期: {report_date.strftime('%Y-%m-%d')}")
        y -= 22

        # Summary box
        c.setStrokeColor(colors.black)
        c.rect(40, y - 50, width - 80, 45)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y - 20, f"综合评分: {total_score:.2f}")
        c.drawString(230, y - 20, f"层级: {tier}")
        c.drawString(360, y - 20, f"排名: {rank}")
        y -= 65

        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Section 1: 学历背景")
        y -= 15
        c.setFont("Helvetica", 10)
        if education:
            for item in education[:4]:
                line = f"- {item.get('school', '')} | {item.get('degree', '')} | {item.get('major', '')} | {item.get('year', '')}"
                c.drawString(50, y, line[:95])
                y -= 13
        else:
            c.drawString(50, y, "- 无")
            y -= 13

        y -= 4
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Section 2: 工作经历")
        y -= 15
        c.setFont("Helvetica", 10)
        if experience:
            for item in experience[:4]:
                duration = f"{item.get('start_date', '')} ~ {item.get('end_date', 'Present')}"
                line = f"- {item.get('company', '')} | {item.get('title', '')} | {duration}"
                c.drawString(50, y, line[:95])
                y -= 13
        else:
            c.drawString(50, y, "- 无")
            y -= 13

        y -= 4
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Section 3: 技能匹配")
        y -= 14
        self._draw_bar(c, 50, y, 240, 10, hit_rate, "命中率")
        y -= 18
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Hit: {str(skill_hit)[:90]}")
        y -= 13
        c.drawString(50, y, f"Miss: {str(skill_miss)[:90]}")
        y -= 16

        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Section 4: 各维度评分")
        y -= 14
        labels = [
            ("技能匹配", "skill_match"),
            ("经验匹配", "experience_match"),
            ("学历匹配", "education_match"),
            ("论文质量", "research_quality"),
            ("经验质量", "experience_quality"),
        ]
        for label, key in labels:
            self._draw_bar(c, 50, y, 240, 9, float(dimension_scores.get(key, 0.0)), label)
            y -= 13
        y -= 6

        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Section 5: 面试建议")
        y -= 14
        c.setFont("Helvetica", 10)
        for suggestion in interview_suggestions[:4]:
            line = f"- [{suggestion.get('severity', 'low')}] {suggestion.get('rule_id', '')}: {suggestion.get('text', '')}"
            c.drawString(50, y, line[:100])
            y -= 12

        # Footer
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(40, 25, f"免责声明: 本报告仅供筛选辅助，不构成最终录用建议。版本: {version}")
        c.save()

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

        sheet.append([f"职位: {position_name}", f"报告日期: {report_date.strftime('%Y-%m-%d')}"])
        sheet.append([])
        sheet.append(
            [
                "排名",
                "姓名",
                "综合分数",
                "技能匹配",
                "经验匹配",
                "学历匹配",
                "论文品质",
                "Tier",
                "面试建议摘要",
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

    @staticmethod
    def _draw_bar(
        c: canvas.Canvas,
        x: float,
        y: float,
        width: float,
        height: float,
        score: float,
        label: str,
    ) -> None:
        normalized = max(0.0, min(100.0, score))
        c.setFont("Helvetica", 9)
        c.drawString(x, y + 12, f"{label}: {normalized:.1f}")
        c.setStrokeColor(colors.black)
        c.rect(x, y, width, height)
        c.setFillColor(colors.darkblue)
        c.rect(x, y, width * (normalized / 100), height, fill=1, stroke=0)
        c.setFillColor(colors.black)
