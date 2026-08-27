# Builds a local HTML screening board (ranking + SVG radar) for HR to open in a browser.
from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from screening_core.candidate_id import format_candidate_label

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

_FALLBACK_DIMS = (
    "skill_match",
    "experience_match",
    "education_match",
    "research_quality",
    "experience_quality",
)

_PAGE_CSS = """
    :root { font-family: "Segoe UI", system-ui, sans-serif; color: #0f172a; background: #f1f5f9; }
    body { max-width: 1100px; margin: 0 auto; padding: 28px 20px 64px; }
    h1 { margin: 0 0 6px; font-size: 1.6rem; }
    .lede { color: #475569; margin: 0 0 24px; }
    table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #e2e8f0; }
    th { background: #0f172a; color: #fff; font-weight: 600; }
    .grid { display: grid; gap: 18px; margin-top: 28px; }
    @media (min-width: 860px) { .grid { grid-template-columns: 1fr 1fr; } }
    .card { background: #fff; border-radius: 16px; padding: 16px 16px 20px; box-shadow: 0 1px 3px rgba(15,23,42,.08); }
    .card header { display: flex; gap: 12px; align-items: center; }
    .rank { font-size: 1.4rem; font-weight: 700; color: #2563eb; margin: 0; min-width: 2.2rem; }
    .card h2 { margin: 0; font-size: 1.05rem; }
    .meta, .muted { color: #64748b; font-size: .9rem; }
    .axis-label { font-size: 9px; fill: #334155; }
    .questions { padding-left: 1.1rem; }
    .prio { color: #2563eb; font-size: .8rem; text-transform: uppercase; }
    a { color: #1d4ed8; }
"""


# Escape text for HTML text nodes and attributes.
def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


# Coerce a score to 0-100 for radar geometry.
def _score(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return max(0.0, min(100.0, number))


# Collect numeric radar axes from matching detail or legacy dimension columns.
def _axes(row: dict[str, Any]) -> list[tuple[str, float]]:
    axes: list[tuple[str, float]] = []
    for item in row.get("radar_dimensions") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or _DIMENSION_LABELS.get(str(item.get("id") or item.get("dimension_id") or ""), "") or item.get("id") or "Dimension")
        score = _score(item.get("score"))
        if score is None:
            continue
        axes.append((label, score))
    if axes:
        return axes[:8]
    for key in _FALLBACK_DIMS:
        score = _score(row.get(key))
        if score is None:
            continue
        axes.append((_DIMENSION_LABELS.get(key, key), score))
    return axes[:8]


# Draw a self-contained SVG radar polygon (no external scripts or CDNs).
def _radar_svg(axes: list[tuple[str, float]], size: int = 280) -> str:
    if len(axes) < 3:
        return '<p class="muted">Not enough dimension scores for a radar chart.</p>'
    cx = cy = size / 2
    radius = size * 0.32
    n = len(axes)
    rings = []
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = []
        for i in range(n):
            angle = -math.pi / 2 + i * 2 * math.pi / n
            x = cx + radius * frac * math.cos(angle)
            y = cy + radius * frac * math.sin(angle)
            pts.append(f"{x:.1f},{y:.1f}")
        rings.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="#d0d7e2" stroke-width="1"/>')
    spokes = []
    labels = []
    poly = []
    for i, (label, score) in enumerate(axes):
        angle = -math.pi / 2 + i * 2 * math.pi / n
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        spokes.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="#d0d7e2"/>')
        lx = cx + (radius + 28) * math.cos(angle)
        ly = cy + (radius + 28) * math.sin(angle)
        anchor = "middle" if abs(math.cos(angle)) < 0.35 else ("start" if math.cos(angle) > 0 else "end")
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" class="axis-label">{_esc(label)}</text>'
        )
        px = cx + radius * (score / 100.0) * math.cos(angle)
        py = cy + radius * (score / 100.0) * math.sin(angle)
        poly.append(f"{px:.1f},{py:.1f}")
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
        f'aria-label="Match radar">'
        f"{''.join(rings)}{''.join(spokes)}"
        f'<polygon points="{" ".join(poly)}" fill="rgba(37,99,235,0.28)" stroke="#2563eb" stroke-width="2"/>'
        f"{''.join(labels)}</svg>"
    )


# Candidate header uses refno/appno only; personal names are ignored.
def _label(row: dict[str, Any]) -> str:
    if row.get("display_label"):
        return str(row["display_label"])
    return format_candidate_label(row.get("refno"), row.get("appno"))


# Render one candidate card: scores, radar, optional interview prompts.
def _card(row: dict[str, Any]) -> str:
    axes = _axes(row)
    questions = []
    for item in row.get("interview_questions") or []:
        if isinstance(item, dict) and item.get("question"):
            questions.append(item)
        elif isinstance(item, str) and item.strip():
            questions.append({"question": item, "priority": ""})
    q_html = ""
    if questions:
        items = "".join(
            f"<li><span class='prio'>{_esc(q.get('priority') or '')}</span> {_esc(q.get('question'))}</li>"
            for q in questions[:8]
        )
        q_html = f"<h3>Interview prompts</h3><ol class='questions'>{items}</ol>"
    score = row.get("total_score")
    score_txt = f"{float(score):.1f}" if _score(score) is not None else "—"
    return f"""
    <article class="card" id="app-{_esc(row.get('appno') or row.get('rank'))}">
      <header>
        <p class="rank">#{_esc(row.get('rank') or '—')}</p>
        <div>
          <h2>{_esc(_label(row))}</h2>
          <p class="meta">Tier {_esc(row.get('tier') or row.get('fit_band') or '—')} · score {_esc(score_txt)}</p>
        </div>
      </header>
      {_radar_svg(axes)}
      {q_html}
    </article>
    """


# Write a standalone HTML file HR can open; it never includes personal names.
def write_screening_board(
    output_path: str,
    *,
    position_name: str,
    rows: list[dict[str, Any]],
    report_date: datetime | None = None,
    refno: str | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = (report_date or datetime.utcnow()).strftime("%Y-%m-%d")
    ranked = sorted(rows, key=lambda row: int(row.get("rank") or 0) or 10**6)
    table_rows = []
    for row in ranked:
        appno = str(row.get("appno") or row.get("rank") or "unknown")
        table_rows.append(
            "<tr>"
            f"<td>{_esc(row.get('rank'))}</td>"
            f"<td><a href='{_esc(appno)}.html'>{_esc(_label(row))}</a></td>"
            f"<td>{_esc(row.get('total_score'))}</td>"
            f"<td>{_esc(row.get('tier') or row.get('fit_band') or '')}</td>"
            "</tr>"
        )
    cards = "".join(_card(row) for row in ranked) or "<p class='muted'>No scored candidates.</p>"
    heading = _esc(position_name)
    sub = _esc(refno) if refno else ""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Ranking overview · {heading}</title>
  <style>{_PAGE_CSS}</style>
</head>
<body>
  <h1>Ranking overview</h1>
  <p class="lede">{heading}{' · refno ' + sub if sub else ''} · {stamped} · labels are refno/appno only</p>
  <table>
    <thead><tr><th>Rank</th><th>Application</th><th>Score</th><th>Tier</th></tr></thead>
    <tbody>{''.join(table_rows)}</tbody>
  </table>
  <div class="grid">{cards}</div>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")
    return path


# Write one candidate match page named by application no. (radar + interview prompts).
def write_candidate_match_html(
    output_path: str,
    *,
    row: dict[str, Any],
    position_name: str,
    report_date: datetime | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = (report_date or datetime.utcnow()).strftime("%Y-%m-%d")
    label = _label(row)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Match · {_esc(label)}</title>
  <style>{_PAGE_CSS}</style>
</head>
<body>
  <p class="lede"><a href="ranking-overview.html">Back to ranking overview</a> · {_esc(position_name)} · {stamped}</p>
  {_card(row)}
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")
    return path


__all__ = ["write_candidate_match_html", "write_screening_board"]
