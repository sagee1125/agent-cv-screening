---
name: cv-scoring-calibration
description: Explain, diagnose, or recalibrate CV screening scores in the agent-cv-screening repo. Use when HR asks why scores are low, asks what a high-scoring CV looks like, or asks to tune the matching engine, and when a scoring constant is changed and the official Desktop reports must be regenerated.
agent_created: true
---

# CV scoring calibration

Covers the whole loop: explain a score → decide whether it is a config problem →
change the engine safely → prove the effect → write it into the official reports.

Fixed paths (never guess):

```
REPO = C:/Users/User/Desktop/IHERD/agent-cv-screening
PY   = C:/Users/User/Desktop/IHERD/agent-cv-screening/venv/Scripts/python.exe
ENGINE = .codex/skills/scorer/src/scorer/matching/engine.py
CONFIG = .codex/skills/scorer/src/scorer/matching/config_builder.py
```

Always use `PY`, never a bare `python`.

## Privacy red lines (instant fail)

Never read or echo: `records.html`, `jd.txt`, `jd-context.txt`, anything under
`_pipeline/` **except** the aggregate score fields, `extracted-*.json`, `detail-*.json`,
`board-row-*.json`, `rows.json`, `manifest.json`, `.env`, and any `.pdf`.
You may pass their **paths** as arguments to a script.
Never show candidate names, emails, phones, HKIDs or salaries — identity is `appno` only.
Safe to quote: `refno`, `post_title`, `candidate_count`, per-dimension scores, `fit_band`,
`hr_status`, active/inactive dimension flags and normalized weights.

## Step 1 — recover the per-dimension scores

The official reports on the Desktop already expose them, so you do **not** need to open
any pipeline file. `Desktop/workbuddy-cv-screen/<refno>/<appno>.html` contains an SVG
radar; the centre is `(140,140)` and the outer ring radius `89.6` equals `100` points.
Distance from centre ÷ 89.6 = that dimension's score. Vertex order is fixed:
up = Core skills, right = Experience, down = Evidence, left = Job-specific.

```bash
cd "C:/Users/User/Desktop/workbuddy-cv-screen/<refno>" && for f in <appno>...; do
  score=$(grep -o 'score [0-9.]*' "$f.html" | head -1)
  poly=$(grep -o 'points="140.0,[0-9.]* [0-9.]*,140.0 140.0,[0-9.]* [0-9.]*,140.0" fill="rgba' "$f.html" | head -1)
  echo "$f | $score | $poly"
done
```

Sanity check: `sum(dimension × normalized_weight)` must equal the reported total to
within 0.05. If it does not, your weight assumption is wrong — re-derive it first.

## Step 2 — derive the active weights

Do not assume the six documented weights (30/25/15/15/5/10). They are **renormalized over
only the active dimensions**, and activation is JD-driven
(`config_builder._activation_map`):

| dimension | active when |
|---|---|
| `core_skill_match` | JD yielded `must_skills` |
| `relevant_experience` | must/specific/role/experience present |
| `role_seniority_fit` | **only** if the JD title contains one of intern/junior/mid/senior/lead/manager/director/executive |
| `evidence_impact` | anything evaluable |
| `education_certification` | **only** if the JD states `minimum_degree` / `field_of_study` / `certifications` / a licence |
| `job_specific_match` | JD yielded specific requirements |

A "Research Assistant" JD typically leaves `role_seniority_fit` **and**
`education_certification` inactive, so education carries **zero** weight. Confirm with a
script that prints `config.config["dimensions"][d]["normalized_weight"]` rather than
guessing, and tell HR plainly when a dimension is switched off.

## Step 3 — explain "why are all the scores low?"

The engine is deterministic (`candidate-matching-v1`); there is no LLM in the scoring step.
Missing evidence scores **0**, not "unknown and ignored".

- `core_skill_match` (usually the binding constraint): skill tokens come only from the
  skills list, `skills_used`, and certifications. Exact hit 1.0, taxonomy-approved related
  skill 0.7, otherwise 0. A skill described in prose is not counted at all.
- `evidence_impact` = 50×coverage + 25×ownership + 25×metric. Metric requires
  `_METRIC_PATTERN`; ownership requires `_OWNERSHIP_SIGNALS`. Academic CVs score low here.
- `relevant_experience` needs parseable `YYYY-MM` dates; it is often saturated and carries
  no discrimination — say so if everyone scores 100.

Also compute the **mathematical ceiling** per candidate:
`core × core_weight + (sum of the other three weights)`. If that is below the high-band
threshold, that candidate *cannot* reach high no matter what else they have. This is the
single most useful number to give HR.

## Step 4 — dry-run the change before touching official reports

Write a comparison script outside the repo (e.g. `%TEMP%/compare_scoring_<refno>.py`)
that scores every candidate twice — once with the old constants, once with the new —
and prints only `appno`, totals, bands and per-dimension scores.

Two setup traps:

1. Importing `scorer` needs **both** of these, in this order:
   ```python
   sys.path.insert(0, str(REPO / ".codex/skills/_shared/src"))
   from screening_core.bootstrap import ensure_skill_imports
   ensure_skill_imports(REPO)
   ```
   Adding only `scorer/src` fails with `ModuleNotFoundError: screening_core`, then
   `cv_parser`.
2. The real pipeline wires a taxonomy related-skill resolver
   (`scorer/scripts/run_score.py`, `_load_taxonomy_related`). Replicate it or
   `core_skill_match` will be wrong. The loader method is `loader.related(a, b)` —
   **not** `are_related`.

**Validation gate: the "before" column must reproduce the official scores to 0.01.**
If it does not, stop — the model is wrong.

Prefer monotone changes (they can only raise a score) so no candidate is ranked down by
an unintended regression.

## Step 5 — run the test suite

```bash
cd "$REPO" && "venv/Scripts/python.exe" -m pytest backend/tests -q > %TEMP%/pytest.log 2>&1; tail -25 %TEMP%/pytest.log
```

Baseline: **405 passed / 1 skipped** (2026-09-02). Never pass `--basetemp` inside the
repo — `hr_output.is_internal_output_dir()` treats in-repo paths as internal and silently
redirects HR output to the Desktop, which makes JAS screening tests fail spuriously.
A trailing `SystemExit: 1` from the sandbox bulk-delete guard during tmpdir cleanup is
expected noise; trust the `N passed` line, not the exit code.

## Step 6 — regenerate the official reports

**Changing a constant alone is a silent no-op.** `run_jas_screening.py` sets
`args.resume = True` whenever a manifest already exists, and `run_pipeline.py` then skips
any candidate whose `detail-<slug>.json` is usable JSON.

Invalidate by **moving** (never deleting) the scoring artifacts:

```bash
cd "C:/Users/User/Desktop/workbuddy-cv-screen/<refno>/_pipeline"
mkdir -p "_backup-<timestamp>"
mv detail-*.json rows.json report-fingerprints.json board-row-*.json "_backup-<timestamp>"/
```

Keep `extracted-*.json` — that is the CV parse cache; keeping it avoids all LLM calls
(a 7-candidate re-run then takes ~1m13s instead of ~2m30s). PDF/HTML need no manual
invalidation: `_generate_reports` compares per-row fingerprints, so changed scores
regenerate automatically.

Then:

```bash
"$PY" "$REPO/.codex/skills/host-envelope/scripts/run_workbuddy_tool.py" screen_refno "<refno>" --driver webbridge
```

Run it with `run_in_background`; WebBridge occasionally stalls past 120s. Afterwards
confirm the new scores match the dry-run prediction, and present
`Desktop/workbuddy-cv-screen/<refno>/ranking-overview.html`.

## Thresholds are a separate decision

`fit_bands` is `{"high_min": 80.0, "medium_min": 60.0}` (`config_builder.py`). Changing it
relabels; it does not measure better. Always give HR a sensitivity table (counts per band
at a few candidate thresholds) and let them choose — do not silently move the goalposts.

## Reverting

Back up the file you edit (outside the repo, to avoid polluting the work tree) and copy it
back to undo. The moved pipeline artifacts stay recoverable inside `_pipeline/_backup-*`.
