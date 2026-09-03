# Builds a local HTML screening board (ranking + SVG radar) for HR to open in a browser.
from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from screening_core.candidate_id import format_candidate_label  # noqa: F401  (kept for API compatibility)

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

_RADAR_TOOLTIP_IDS = (
    "core_skill_match",
    "relevant_experience",
    "role_seniority_fit",
    "evidence_impact",
    "education_certification",
    "job_specific_match",
)
_PAGE_CSS_BASE = """
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
    .note { background: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 14px 16px; margin: 20px 0 0; }
    .note h2 { margin: 0 0 6px; font-size: 1rem; }
    .note p { margin: 0 0 6px; font-size: .9rem; color: #475569; }
    .note p:last-child { margin-bottom: 0; }
    .radar-wrap { position: relative; }
    .axis-hit { cursor: help; }
    .axis-hit:focus { outline: 2px solid #2563eb; outline-offset: 2px; }
    .radar-tips { position: absolute; inset: 0; pointer-events: none; z-index: 4; }
    .radar-tip {
      position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
      width: min(340px, 92%); max-height: 94%; overflow: auto;
      background: #0f172a; color: #e2e8f0; border-radius: 12px;
      padding: 12px 14px; box-shadow: 0 12px 28px rgba(15, 23, 42, .4);
      opacity: 0; visibility: hidden; pointer-events: none;
      transition: opacity .12s ease;
    }
    .tip-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .tip-label { font-weight: 600; color: #fff; }
    .tip-score { font-weight: 700; font-size: 1.05rem; color: #fff; }
    .tip-muted { color: #94a3b8; font-size: .82rem; }
    .tip-status { margin-top: 2px; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }
    .tip-summary { margin: 6px 0 0; color: #cbd5e1; font-size: .9rem; line-height: 1.4; }
    .tip-gaps { margin: 6px 0 0; padding-left: 1.1rem; color: #fda4af; font-size: .85rem; line-height: 1.35; }
    .tip-sections { margin-top: 6px; font-size: .82rem; color: #94a3b8; }
    .tip-subscores { margin-top: 6px; font-size: .82rem; color: #a5b4fc; }
    .tip-preview { margin-top: 8px; padding-top: 6px; border-top: 1px solid rgba(148, 163, 184, .3); color: #a5b4fc; font-size: .85rem; line-height: 1.4; }
    .st-met { color: #34d399; }
    .st-partial { color: #fbbf24; }
    .st-not_met { color: #f87171; }
    .st-not_applicable, .st-unknown { color: #94a3b8; }
"""

_TOOLTIP_SHOW_RULES = "\n".join(
    f'.card:has(.axis-hit[data-axis="{dim}"]:hover) .radar-tip[data-tip="{dim}"],'
    f'.card:has(.axis-hit[data-axis="{dim}"]:focus-visible) .radar-tip[data-tip="{dim}"]'
    f" {{ opacity: 1; visibility: visible; }}"
    for dim in _RADAR_TOOLTIP_IDS
)

_PAGE_CSS = _PAGE_CSS_BASE + "\n" + _TOOLTIP_SHOW_RULES

# Advisory copy shown when the whole pool lands in the low band.
_LOW_BAND_NOTE_EN = (
    "Bands are absolute thresholds (high &ge; 80, medium &ge; 60, low &lt; 60) measured against "
    "this job's requirements; they are not a ranking of this pool. A low band usually means the CVs "
    "do not state the required evidence in machine-readable fields, not that the candidates are "
    "unqualified. Compare the per-application reports before shortlisting."
)

# Short radar axis labels so they never clip outside the SVG canvas.
_RADAR_SHORT_LABELS = {
    "Education and Certification": "Education",
    "Role and Seniority Fit": "Seniority",
    "Relevant Experience": "Experience",
    "Core Skill Match": "Core skills",
    "Job-Specific Match": "Job-specific",
    "Work Authorization": "Work auth",
}


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


# Extract allow-listed structured tooltip content from one radar axis record.
def _axis_parts(item: dict[str, Any]) -> dict[str, Any] | None:
    label = str(item.get("label") or "").strip()
    score = _score(item.get("score"))
    if score is None or not label:
        return None
    parts: dict[str, Any] = {"label": label, "score": score}
    status = str(item.get("status") or "").strip()
    if status:
        parts["status"] = status
    summary = str(item.get("summary") or "").strip()
    if summary:
        parts["summary"] = summary
    gaps = [str(gap) for gap in (item.get("gaps") or []) if str(gap).strip()]
    if gaps:
        parts["gaps"] = gaps[:3]
        overflow = int(item.get("gaps_overflow") or 0)
        if overflow > 0:
            parts["gaps_overflow"] = overflow
    sections = item.get("evidence_sections")
    if isinstance(sections, dict) and sections:
        parts["evidence_sections"] = {
            str(section): int(count) for section, count in sections.items() if str(section).strip()
        }
    metrics = item.get("evidence_metrics")
    if isinstance(metrics, dict) and metrics:
        parts["evidence_metrics"] = {str(key): value for key, value in metrics.items()}
    if not any(key in parts for key in ("status", "summary", "gaps", "evidence_sections")):
        return None
    return parts


# Collect radar axes (id, label, score, optional tooltip parts) from matching detail or legacy columns.
def _axes(row: dict[str, Any]) -> list[dict[str, Any]]:
    axes: list[dict[str, Any]] = []
    for item in row.get("radar_dimensions") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or _DIMENSION_LABELS.get(str(item.get("id") or item.get("dimension_id") or ""), "") or item.get("id") or "Dimension")
        score = _score(item.get("score"))
        if score is None:
            continue
        parts = _axis_parts(item)
        axes.append(
            {
                "id": str(item.get("id") or item.get("dimension_id") or ""),
                "label": label,
                "score": score,
                "parts": parts,
            }
        )
    if axes:
        return axes[:8]
    for key in _FALLBACK_DIMS:
        score = _score(row.get(key))
        if score is None:
            continue
        axes.append({"id": key, "label": _DIMENSION_LABELS.get(key, key), "score": score, "parts": None})
    return axes[:8]


# Draw a self-contained SVG radar polygon (no external scripts or CDNs).
# The viewBox is padded horizontally so side axis labels never clip at the edges.
def _radar_svg(axes: list[dict[str, Any]], size: int = 280, pad: int = 80) -> str:
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
    for index, axis in enumerate(axes):
        label = str(axis["label"])
        score = float(axis["score"])
        angle = -math.pi / 2 + index * 2 * math.pi / n
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        spokes.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="#d0d7e2"/>')
        lx = cx + (radius + 28) * math.cos(angle)
        ly = cy + (radius + 28) * math.sin(angle)
        anchor = "middle" if abs(math.cos(angle)) < 0.35 else ("start" if math.cos(angle) > 0 else "end")
        short = _RADAR_SHORT_LABELS.get(label, label)
        aid = str(axis.get("id") or "")
        parts = axis.get("parts")
        aria = f"{short} score {score:.0f}/100"
        if isinstance(parts, dict):
            extra = " · ".join(str(parts[key]) for key in ("status", "summary") if parts.get(key))
            if extra:
                aria = f"{aria}: {extra}"
        labels.append(
            f'<g class="axis-hit" tabindex="0" role="img" data-axis="{_esc(aid)}" aria-label="{_esc(aria)}">'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="13" fill="transparent"/>'
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" class="axis-label">{_esc(short)}</text>'
            f"</g>"
        )
        px = cx + radius * (score / 100.0) * math.cos(angle)
        py = cy + radius * (score / 100.0) * math.sin(angle)
        poly.append(f"{px:.1f},{py:.1f}")
    return (
        f'<svg viewBox="{-pad} 0 {size + 2 * pad} {size}" role="img" '
        f'style="width:100%;height:auto;display:block" aria-label="Match radar">'
        f"{''.join(rings)}{''.join(spokes)}"
        f'<polygon points="{" ".join(poly)}" fill="rgba(37,99,235,0.28)" stroke="#2563eb" stroke-width="2"/>'
        f"{''.join(labels)}</svg>"
    )


# Renders one hidden styled tooltip card for a radar axis (revealed on hover via CSS).
def _axis_tip_panel(axis: dict[str, Any]) -> str:
    aid = str(axis.get("id") or "")
    parts = axis.get("parts")
    if not isinstance(parts, dict) or not aid:
        return ""
    score = float(parts["score"])
    blocks = []
    head = f'<span class="tip-label">{_esc(parts["label"])}</span><span class="tip-score">{score:.0f}</span><span class="tip-muted">/100</span>'
    blocks.append(f'<div class="tip-head">{head}</div>')
    status = str(parts.get("status") or "").strip()
    if status:
        blocks.append(f'<div class="tip-status st-{_esc(status)}">{_esc(status)}</div>')
    summary = str(parts.get("summary") or "").strip()
    if summary:
        blocks.append(f'<p class="tip-summary">{_esc(summary)}</p>')
    metrics = parts.get("evidence_metrics")
    if isinstance(metrics, dict) and metrics:
        labels = {
            "presence_pct": "presence",
            "linkage_pct": "linkage",
            "ownership_pct": "ownership",
            "impact_pct": "impact",
        }
        rendered = " \u00b7 ".join(
            f"{labels.get(key, key)} {value:g}%"
            for key, value in metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        )
        if rendered:
            blocks.append(f'<div class="tip-subscores">Sub-scores: {_esc(rendered)}</div>')
    gaps = parts.get("gaps") or []
    if gaps:
        items = "".join(f"<li>{_esc(gap)}</li>" for gap in gaps)
        overflow = int(parts.get("gaps_overflow") or 0)
        if overflow > 0:
            items += f"<li>+{overflow} more</li>"
        blocks.append(f'<div class="tip-muted">Key gaps</div><ul class="tip-gaps">{items}</ul>')
    sections = parts.get("evidence_sections")
    if isinstance(sections, dict) and sections:
        provenance = " \u00b7 ".join(f"{_esc(str(section))} {count}" for section, count in sections.items())
        blocks.append(f'<div class="tip-sections">Evidence by CV section: {provenance}</div>')
    return f'<div class="radar-tip" data-tip="{_esc(aid)}" role="tooltip">{"".join(blocks)}</div>'



# Wraps all hidden tooltip cards for one candidate radar in one overlay container.
def _axis_tips(axes: list[dict[str, Any]]) -> str:
    panels = [_axis_tip_panel(axis) for axis in axes]
    panels = [panel for panel in panels if panel]
    if not panels:
        return ""
    return f'<div class="radar-tips">{"".join(panels)}</div>'


# Candidate header states which part is the refno and which is the appno (never a name).
def _label(row: dict[str, Any]) -> str:
    refno = str(row.get("refno") or "").strip()
    appno = str(row.get("appno") or "").strip()
    if refno and appno:
        return f"refno {refno} · appno {appno}"
    if appno:
        return f"appno {appno}"
    if refno:
        return f"refno {refno}"
    return str(row.get("display_label") or "unknown")


# Build an advisory block when every scored candidate sits in the low band.
def _low_band_advisory(ranked: list[dict[str, Any]]) -> str:
    bands = [str(row.get("tier") or row.get("fit_band") or "").strip().lower() for row in ranked]
    if not any(band == "low" for band in bands):
        return ""
    if any(band not in ("low", "") for band in bands):
        return ""
    spread_html = ""
    scores = [score for score in (_score(row.get("total_score")) for row in ranked) if score is not None]
    if len(scores) >= 2:
        spread = max(scores) - min(scores)
        if spread < 10:
            spread_html = (
                "<p><strong>The whole pool spans only "
                f"{spread:.1f} points</strong> — candidates this close should be treated as "
                "tied; rank order alone is not a signal.</p>"
            )
    return (
        '<aside class="note"><h2>Why every candidate shows the low band</h2>'
        f"<p>{_LOW_BAND_NOTE_EN}</p>"
        f"{spread_html}"
        "</aside>"
    )


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
      <div class="radar-wrap">
        {_radar_svg(axes)}
        {_axis_tips(axes)}
      </div>
      {q_html}
    </article>
    """


# Render the online resume link cell; em dash when no URL is known.
def _resume_cell(row: dict[str, Any]) -> str:
    resume_url = str(row.get("resume_url") or "").strip()
    if not resume_url:
        return "<span class='muted'>—</span>"
    return f"<a href='{_esc(resume_url)}' target='_blank' rel='noopener'>Resume</a>"


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
            f"<td>{_resume_cell(row)}</td>"
            "</tr>"
        )
    cards = "".join(_card(row) for row in ranked) or "<p class='muted'>No scored candidates.</p>"
    advisory = _low_band_advisory(ranked)
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
    <thead><tr><th>Rank</th><th>Application</th><th>Score</th><th>Tier</th><th>Resume</th></tr></thead>
    <tbody>{''.join(table_rows)}</tbody>
  </table>
  {advisory}
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
