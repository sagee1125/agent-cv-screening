---
prd_id: PRD-Multi_Post-v1.0
feature_name: Multi-Post JAS Advertisements
version: 1.2.2
status: Draft
owner: HR Screening Product Owner
api_version: v1
related_docs:
  - docs/PRD-Overall-v1.0.md
  - docs/overall-logic-summary.md
  - docs/jas-import/PRD-JAS_Import_v1.0.md
  - docs/report-gen/PRD-Ranking_HTML_Radar_Traceback_v1.0.md
  - docs/workbuddy/PRD-Host_Tool_Return_Whitelist_v1.0.md
  - .codex/skills/jas-import/src/jas_import/records.py
  - .codex/skills/jas-import/src/jas_import/mock.py
  - .codex/skills/jas-import/scripts/run_jas_screening.py
  - .codex/skills/pipeline/scripts/run_pipeline.py
  - .codex/skills/report-gen/src/report_gen/html_board.py
  - .codex/skills/_shared/src/screening_core/report_fingerprint.py
affected_modules:
  - .codex/skills/jas-import
  - .codex/skills/jd-parser
  - .codex/skills/pipeline
  - .codex/skills/report-gen
  - .codex/skills/_shared (screening_core)
  - .codex/skills/host-envelope
  - AGENTS.md
  - ~/.workbuddy-ai/skills/hr-cv-screening/SKILL.md
---

# Product Requirements Document (PRD)

**Feature Name:** Multi-Post JAS Advertisements
**Version:** 1.2.2 (MVP)
**Status:** Draft
**Product Manager:** HR Screening Product Owner
**Target Users:** HR recruiters screening a JAS `refno` through the WorkBuddy chat

> Keep the header above in sync with the YAML frontmatter (machine-readable source of truth).

---

## Change Log

| Version | Date       | Author                     | Change Summary                                                                                                                  |
| ------- | ---------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 1.0.0   | 2026-09-17 | HR Screening Product Owner | Initial PRD: one `refno` may advertise several posts; per-post JD, scoring, report.                                             |
| 1.1.0   | 2026-09-17 | HR Screening Product Owner | Add FR-12 (`check_updates` reports per-post changes); carry `post` into the collector manifest; extend the module-impact table. |
| 1.2.0   | 2026-09-17 | HR Screening Product Owner | Record the prerequisite fix as resolved (§8); correct the test baseline to 517 (§9); add §13 Implementation Handover. |
| 1.2.1   | 2026-09-17 | HR Screening Product Owner | Withdraw FR-6.4: the records page has no post list, so a zero-applicant post cannot be shown. Add the measurement to §2.4 and scope the universe in FR-3. |
| 1.2.2   | 2026-09-17 | HR Screening Product Owner | FR-6: redact the named contact from the rendered JD panel and correct the "no trace" wording, which the advertisement text contradicts. Record `unclaimed` as the cross-check. |

---

## 1. Executive Summary

Until now the screening engine has assumed **one `refno` = one job advertisement = one parsed JD**. A JAS
advertisement can instead cover **several posts** (for example "Research Associate / Research Assistant"),
where each applicant applies for exactly one of them. Today the pipeline parses one JD for the whole
advertisement and ranks every applicant in a single list — which is wrong twice over: the applicants did not
compete for the same post, and the advertisement states different requirements per post.

This PRD defines multi-post screening: the advertisement's shared requirements become a **base JD**, each post
gets a small **delta** derived from the same advertisement, every applicant is scored only against the JD of the
post they applied for, and the ranking report presents **one collapsible section per post**.

### 1.1 Problem Statement

1. **One parsed JD cannot represent a multi-post advertisement.** The advertisement's `Description` mixes
   shared bullets with post-specific bullets ("Applicants for the **Research Associate** post should have …").
2. **A single ranking list is not comparable.** Scores computed against different post requirements have
   different denominators; presenting them in one ordered list implies a comparison that does not exist.
3. **The post an applicant applied for is discarded today.** The records page carries a `Post applied for`
   column for multi-post advertisements, and the parser currently drops its value.
4. **A blocking defect makes the whole path unusable.** The candidate column map silently falls back to
   hardcoded column positions, which shift by one on a multi-post page. Section 8 has the measured evidence.

### 1.2 Product Vision

HR screens a multi-post `refno` exactly as before — one refno, one Desktop folder, one report — but the report
shows one clearly labelled section per post, each with its own JD panel and its own ranking, and HR can
collapse the ones they are not working on.

### 1.3 Success Definition (MVP)

Screening a multi-post `refno`:

- downloads **every** applicant's CV (today it downloads none — see Section 8);
- groups applicants by the post they applied for, with no applicant silently dropped or misassigned;
- scores each applicant against the JD of their own post only;
- writes one `ranking-overview.html` containing one collapsed/expandable section per post, each showing the
  post's JD panel and its own ranking table;
- writes one `<appno>.html` / `<appno>.pdf` per applicant, each stating the post applied for;
- leaves the single-post path byte-identical in behaviour and scores.

### 1.4 Personas

1. **HR Recruiter (non-technical)** — says "screen refno X"; wants a per-post shortlist without reading the
   raw advertisement. Must never be asked to name a Python script or paste a CV into chat.
2. **HR Manager** — needs to know how many applicants each post received, and that the numbers are not
   comparable across posts.
3. **Engineering** — needs the post dimension to be an explicit, cacheable key rather than an implicit
   assumption, so re-runs and backtesting stay reproducible.

---

## 2. Verified JAS Page Behaviour

All of the following was measured against the live demo records pages on 2026-09-17 by fetching the raw HTML
(Appendix A has the exact commands). **No personal data is reproduced anywhere in this document.**

### 2.1 There is no `data-multi-post` attribute

An earlier assumption was that the page carries `data-multi-post="true|false"`. It does not. The string
`data-multi-post` occurs **zero** times in the list page and in the records pages of every refno tested, and the
page's own `assets/admin_common.js` contains zero occurrences of `multi`. The flag is rendered server-side, so
the WebBridge driver (post-JS DOM) and the headless HTTP driver (raw HTML) observe the same structure.

### 2.2 The three real signals

| Signal                        | Multi-post                                         | Single-post                  |
| ----------------------------- | -------------------------------------------------- | ---------------------------- |
| Candidate table `class`       | `listTable job-detail-table multi-post-table`      | `listTable job-detail-table` |
| `Post applied for` header     | present, inserted directly after `Application no.` | absent                       |
| JD key/value row `Multi-post` | `Yes`                                              | `No`                         |

The `Multi-post` key/value row is the most reliable of the three because it is **present for both shapes**
(a single-post page states `No` explicitly), and the parser already reads key/value rows. Detection should
accept any one of the three signals as "multi-post", and treat a page with none of them as single-post.

### 2.3 The extra column shifts everything after it by one

| Layout      | columns | appno | Post applied for | record detail | status | CV  | supplementary |
| ----------- | ------- | ----- | ---------------- | ------------- | ------ | --- | ------------- |
| single-post | 39      | 1     | —                | 2             | 3      | 13  | 14            |
| multi-post  | 40      | 1     | 2                | 3             | 4      | 14  | 15            |

### 2.4 Other measured facts

- **`data-n` is not a column index.** It is a sort key and is duplicated: `Post applied for` and the next
  header both carry `data-n="2"`. Never use it to locate a cell.
- **Each records page contains exactly one job block.** `id="job-<refno>"` appears once, so "the first
  `job-detail-table` on the page" is the correct table. (The page's own JS only toggles job blocks when the
  file is opened directly from disk, which is not the served path.)
- **Table lookup is substring-based** (`class_token in classes`), so the extra `multi-post-table` class does
  not break table discovery, and the JD key/value table is unaffected by the extra column.
- **The list page carries no multi-post signal** and its column set is unchanged.
- **The records page carries no post list.** Measured on 260917001: zero `<select>` and zero `<option>`
  elements. `Post title` is a cross-product string (`Senior Project Fellow / Postdoctoral Fellow
  (Full-time/Part-time)`) that cannot be split back into the four labels applicants see. The only source of
  the post universe is therefore the `Post applied for` column, which means a post nobody applied for is
  invisible — the reason FR-6.4 was withdrawn in v1.2.1.
- **Every advertisement ends with a named contact block.** Both live multi-post `Description` values close
  with a sentence naming a member of staff and giving a telephone number, and one of them also a fax number.
  The advertisement also names every post it describes, so the advertisement text *can* mention a post that
  received no applications — see the v1.2.2 correction under FR-6.
- **`appno` is not guaranteed to differ from `refno`.** One measured multi-post page contains an application
  whose number equals the refno it was screened under. Do not rely on the two differing.

### 2.5 Measured post universes

| refno     | applicants | posts | post → applicant count                                                                               |
| --------- | ---------- | ----- | ---------------------------------------------------------------------------------------------------- |
| 260907003 | 5          | 2     | Research Associate 2; Research Assistant 3                                                           |
| 260917001 | 12         | 4     | Senior Project Fellow (Full-time) 2; (Part-time) 3; Postdoctoral Fellow (Full-time) 3; (Part-time) 4 |
| 260901004 | 7          | —     | single-post control                                                                                  |

Two consequences:

1. **Full-time and part-time are separate posts.** `260917001` is four posts, not two.
2. **The post universe cannot be derived from the advertisement's `Post title`.** That field is a
   cross-product string (`Senior Project Fellow / Postdoctoral Fellow (Full-time/Part-time)`); it cannot be
   split back into the four labels applicants actually see. The post universe must come from the
   `Post applied for` column values, with `Post title` used only for display and as a cross-check.

### 2.6 Applicant identity

Every application has its **own unique application number**, including when the same person applies twice. All
five demo refnos have `rows == distinct appno`, and every `Post applied for` cell holds a single value (no
comma- or slash-separated multi-post cells). Two consequences:

- **`appno` remains the row key.** No composite `(appno, post)` key is required.
- The engine **must not** attempt to link two applications from the same person: that would require the name or
  email, which the pipeline deliberately discards. The report therefore never claims "this applicant also
  applied for another post".

---

## 3. Terminology

| Term              | Meaning                                                                                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Post**          | One selectable option on the advertisement, exactly as written in `Post applied for`.                                                                              |
| **Base name**     | A post label with its trailing parenthetical removed (`Senior Project Fellow`). Used only for bullet attribution and grill grouping — never as a display identity. |
| **Post universe** | The set of distinct `Post applied for` values actually present in the records page.                                                                                |
| **Base JD**       | The structured requirements shared by every post, parsed once from the advertisement.                                                                              |
| **Delta**         | The post-specific requirement fragments extracted from the same advertisement for one post.                                                                        |
| **Effective JD**  | `base JD ⊕ delta` — the requirements one applicant is scored against.                                                                                              |
| **Post group**    | The applicants of one post, scored and ranked together.                                                                                                            |

---

## 4. Scope

### 4.1 In scope

- Detecting a multi-post advertisement from the records page.
- Capturing the `Post applied for` value per applicant.
- Deriving one effective JD per post from the single advertisement.
- Scoring each applicant against their own post's JD only.
- One `ranking-overview.html` with one collapsible section per post.
- Extending the HR conditions grill to carry per-post items.
- Re-screening only the post group affected by a change.

### 4.2 Out of scope

- Cross-post ranking or any normalisation that would make scores comparable across posts.
- Ranking posts against each other, or recommending which post to fill.
- Multiple advertisements in one run, or one refno screened into several Desktop folders.
- Changes to the scoring formula, weights, or bands (see `docs/candidate-matching/`).
- Any use of applicant names, emails, phones or salaries.

---

## 5. Functional Requirements

### FR-1 — Detect a multi-post advertisement

Read the records page and set a multi-post flag from the three signals in Section 2.2 (accept any one; treat a
page with none as single-post). The flag and the raw evidence used must be recorded in the job payload so the
run can be audited.

### FR-2 — Capture the post applied for

Add the `Post applied for` value to each parsed applicant reference. It must survive into the manifest and the
pipeline rows. When the page is single-post, the value is absent and the existing behaviour is unchanged.

### FR-3 — Build the post universe

The post universe is the distinct `Post applied for` values, normalised by trimming surrounding whitespace and
comparing case-insensitively; the label shown to HR is the raw value. Cross-check against the advertisement's
`Post title` and record any disagreement — an applicant whose post matches nothing in the universe must **not**
be guessed at (see FR-7).

The universe is derived from applicants only, so it is exactly the set of posts that received at least one
application. A post nobody applied for is invisible on the records page and is therefore **out of scope**, not
rendered as an empty section — see FR-6 and the v1.2.1 change-log entry.

### FR-4 — Derive one effective JD per post

Split the single advertisement into a base JD plus one delta per post:

- Parse the advertisement **once** as today to produce the base JD (skills, languages, experience, education,
  seniority, visa).
- Attribute the `Description` bullet list: a bullet that names a post belongs to that post's delta; a bullet
  that names no post is shared and stays in the base.
- Bullet attribution matches on the **base name**, so full-time and part-time variants of one post inherit the
  same bullets.
- Every derived delta must carry provenance: the exact source sentence it came from.
- Effective JD for a post = base JD merged with that post's delta.

### FR-5 — Score per post

Each post group is scored against its own effective JD. An applicant is scored **once**, against their own
post's JD. Scores from different post groups must never be merged into a single ordered list.

### FR-6 — Ranking report with one collapsible section per post

One `ranking-overview.html` per refno, containing:

1. A page heading whose lede uses the advertisement's `Post title`, plus the refno and the report date.
2. A shared JD panel showing the **complete original advertisement text**, with its parsed tag groups listing
   the shared requirements only. The text is reproduced as the advertisement states it, except that the
   named contact's personal details are replaced by placeholders — see "Contact details are redacted" below.
3. One collapsible section per post, ordered as the post universe is ordered. Each section header states the
   post label, the number of applicants, and the top score; the body contains that post's JD panel (its delta
   plus the merged parsed requirements) and that post's own ranking table and applicant cards.
4. The first section may default to expanded; every other section defaults to collapsed.
5. Ranking tables inside a section are ranked within that section only.

Collapsible sections must use native HTML `<details>` / `<summary>` so the report needs no JavaScript and
prints correctly.

**Contact details are redacted.** The advertisement's closing paragraph names a member of staff and gives a
telephone, fax or email address (measured on both live multi-post advertisements). That block is
advertisement logistics, not a requirement, and the project rule is that no personal name, phone number or
email address appears in a report. The panel therefore renders it with the contact's name and numbers
replaced by `[name removed]`, `[phone removed]` and `[email removed]`. Redaction happens **at render time
only**: the raw advertisement stays unmodified in `_pipeline` for audit, and because it never touches the
parsed JD it cannot affect scores or the cache. `_scrub_contact` in
`report-gen/src/report_gen/html_board.py` applies the rule to every JD-derived string the report emits,
including requirement tooltips. It is deliberately narrow — a titled name after "contact", or an untitled
name immediately followed by the contact details — so an ordinary requirement sentence cannot lose a
capitalised word.

**No empty-post section.** An earlier revision of this requirement demanded that a post with zero applicants
still be shown with an empty state. v1.2.1 removes it, because it is not implementable: the records page
carries no post list at all (measured on the live pages — zero `<select>` and zero `<option>` elements), and
`Post title` is a cross-product string that cannot be split back into the full-time / part-time labels
applicants actually see (§2.5). A post nobody applied for therefore leaves **no trace in the records page**,
which is the only input that can confirm a post was ever selectable. The post universe is exactly the
distinct `Post applied for` values (FR-3), so every rendered section has at least one applicant, and the
report never claims to know about a post it cannot see.

> **Correction (v1.2.2).** v1.2.1 justified this by saying a post nobody applied for "leaves no trace on the
> page". That is too strong. The **advertisement text** can name a post that received no applications — the
> live advertisements name every post they describe. The decision stands, because the advertisement cannot
> confirm such a post was selectable and the records page cannot confirm it either, but the trace does exist
> and is now recorded: `PostSplit.unclaimed` reports a post the advertisement names that the post universe
> does not contain.

### FR-7 — Applicant whose post cannot be determined

Because the post universe is derived from the column values themselves (FR-3), a **non-empty** post value
always matches the universe by construction. The reachable failure is a **blank or missing** `Post applied for`
value on a multi-post page: that applicant cannot be placed in any post group.

The run must **finish** the other applicants and place such a row in a clearly labelled "needs HR confirmation"
block, carrying the application number and the raw (possibly empty) value. The run must never silently drop the
row and never guess which post it belongs to. If a new run status is introduced for this, it must be registered
in the host envelope's `ALLOWED_STATUS` / `ALLOWED_ERROR_CODES` / `ALLOWED_MISSING` lists, or the host will
collapse it into a generic error.

Separately, when a post value is not mentioned anywhere in the advertisement's `Post title`, that is recorded as
a cross-check disagreement (FR-3) and surfaced to HR. That is a warning, not a block.

### FR-8 — Per-candidate report

`<appno>.html` / `<appno>.pdf` keep their current file names. Each must state the post applied for, and its JD
panel must show that applicant's effective JD (base ⊕ delta), not the shared base alone.

### FR-9 — HR conditions grill

The grill stops the pipeline **once** and carries one item per post, each tagged with its post. The conversation
asks the items one after another and then confirms them in a single re-run.

- Grill items are grouped by **base name**, so full-time and part-time variants of one post share one answer
  (260917001 therefore produces two grill items, not four).
- A partially confirmed run must not re-ask posts that were already confirmed; the stored overrides file
  records per-post confirmation state.
- The existing rule stands: stored conditions are the grill's default answer, never a substitute for asking.

### FR-10 — Incremental re-run

When a re-run finds that only one post group changed (a new applicant, a changed CV, a changed post), only that
group is re-parsed, re-scored and re-reported. The board HTML is rewritten in full because it contains every
group, but the untouched groups' per-applicant artifacts are reused from cache.

### FR-11 — Documentation and HR-facing text

- `AGENTS.md` and the `hr-cv-screening` skill's reply template gain a multi-post variant of the text summary:
  counts and top application numbers **per post**, and the Desktop folder path.
- The reply must state that scores are comparable within a post, not across posts.

### FR-12 — Update checking

`check_updates` must report changes in the post dimension, not only new applicants: a new applicant in post X, an
applicant whose post changed, and a post that appeared or disappeared. Reporting only "the applicant count
changed" would hide a re-assignment, which is exactly the change HR most needs to see. The flow's existing
behaviour is unchanged: it opens only the records page, does not grill, and closes its tab once answered.

---

## 6. Artifacts, Identity and State

The HR-facing unit does not change: one refno → one folder `Desktop/workbuddy-cv-screen/<refno>/`, containing
`ranking-overview.html`, `<appno>.html` and `<appno>.pdf`. The post dimension is carried **inside** the folder.

| Artifact                                                      | Change                                                                                                                     |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `_pipeline/jd-parse.json`                                     | Becomes the base JD (unchanged shape).                                                                                     |
| `_pipeline/post-jds.json` (new)                               | One effective JD per post, plus each delta's provenance.                                                                   |
| `_pipeline/jd-overrides.yaml`                                 | Gains a post dimension; records per-post confirmation state.                                                               |
| `_pipeline/rows.json`                                         | Every row gains `post`.                                                                                                    |
| `_pipeline/detail-*.json`, `score-*.json`, `extracted-*.json` | Per applicant, unchanged (an applicant belongs to exactly one post).                                                       |
| `_pipeline/report-fingerprints.json`                          | Per-applicant fingerprints gain the post dimension.                                                                        |
| `_pipeline/manifest.json`, `jas-manifest.json`                | The single `post_title` becomes a post list with per-post applicant counts.                                                |
| Collector manifest (`<collect-root>/<refno>/manifest.json`)   | `candidates[]` gains `post`; the single `post_title` becomes a post list. The collector still writes one folder per refno. |
| `data/jas_state/<refno>.json`                                 | `last_screen` and the score snapshot gain the post per applicant.                                                          |

Cache keys: the run payload already carries `refno` and `position`; `position` becomes the post label for
per-group work and a `post` key is added, so two posts never share cached scores. The board fingerprint must
cover **every** post's JD digest, not a single digest.

---

## 7. Module Impact

| Module                                             | Change                                                                                                                           |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `jas_import/records.py`                            | Read the `Post applied for` column; expose the multi-post flag; the column map must read link-wrapped header labels (Section 8). |
| `jas_import/skill.py`                              | Carry `post` on every candidate reference, and the multi-post flag plus signals on the job. The flat candidate list is **kept**: a nested per-post structure buys nothing once FR-6.4 is withdrawn, and it would make the single-post and multi-post payloads diverge. |
| `jas_import/mock.py`                               | Fixture headers must mirror the real page (labels inside `<a>`), plus a multi-post fixture shape.                                |
| `jas_import/scripts/run_jas_screening.py`          | Group applicants by post; carry the post into the pipeline call and the run state.                                               |
| `jd-parser`                                        | Split the advertisement into base + per-post deltas with provenance.                                                             |
| `screening_core/jd_overrides.py`                   | Merge overrides per post.                                                                                                        |
| `screening_core/report_fingerprint.py`             | Per-post run payload and a board fingerprint over all post JD digests.                                                           |
| `pipeline/scripts/run_pipeline.py`                 | One post-aware run: per-post config, `post` on every row, grouped report generation.                                             |
| `report-gen/src/report_gen/html_board.py`          | `write_screening_board` accepts post groups and renders one `<details>` per post.                                                |
| `jas_import/scripts/check_updates.py`              | Report per-post changes (new applicant, moved post, new post) instead of one aggregate count.                                    |
| `webridge-collect/src/webridge_collect/collect.py` | Carry `post` into the collect manifest; one folder per refno is unchanged.                                                       |
| `host-envelope`                                    | Any new status or missing-input key must be whitelisted.                                                                         |

---

## 8. Prerequisite Defect (blocking)

> **Status: RESOLVED** in commit `0923542` (2026-09-17). **Do not re-fix it.** The measured evidence below is
> kept as the record of why the fix was required and as the regression target. What shipped:
> `_header_label(cell)` now reads `text or link_text` (`records.py:237`) and is used by
> `_candidate_column_indexes` (`records.py:302`); `mock.py` emits link-wrapped headers behind a
> `multi_post=` fixture flag; three regression tests were added to `backend/tests/unit/test_jas_import.py`.
> **The `post` key is deliberately NOT in the column map yet** — it lands with FR-2 (§13, step 1), because the
> map and the `JASCandidate.post` field must change together.

**The candidate column map never works on real pages, so multi-post cannot be implemented on top of it.**

`jas_import/records.py:_candidate_column_indexes` is designed to map columns by header label and fall back to
hardcoded legacy positions. On a real page the header labels are wrapped in a sortable link —
`<th class="f-header"><a href="#" data-n="N">Label</a></th>` — and `_normalize_cell` deliberately keeps link
text only in `link_text`, never in `text`. `_candidate_column_indexes` reads `_text(cell)`, so the label is
**always empty**, the map is **never updated**, and the hardcoded positions
`{appno: 1, record_detail: 2, status: 3, cv: 13, supp: 14}` are used for every page.

Single-post pages happen to match those positions, which is why this went unnoticed. Measured on the live
pages (columns read per applicant, before the fix):

| refno     | layout      | appno | status | cv_url | record_detail_url | supp_url |
| --------- | ----------- | ----- | ------ | ------ | ----------------- | -------- |
| 260901004 | single-post | 7/7   | 7/7    | 7/7    | 7/7               | 0/7      |
| 260907003 | multi-post  | 5/5   | 0/5    | 0/5    | 0/5               | 5/5 †    |
| 260917001 | multi-post  | 12/12 | 0/12   | 0/12   | 0/12              | 12/12 †  |

† On a multi-post page, legacy index 14 is the CV column, so the CV link is mislabelled as supplementary
material; legacy index 13 is the **contact telephone** column, which is read into the CV field.

Effect: a multi-post refno downloads **zero CVs** today, and the run degrades into "no candidates".

The fix — applied in `0923542` — was one line, reading the label from `text or link_text`, plus two
follow-ups, both now satisfied:

1. `jas_import/mock.py` had to wrap its header labels in `<a>` the way the real page does. The existing
   regression test passed only because the fixture emitted bare `<th>Label</th>`; the fixture therefore
   exercised a code path production never takes.
2. The resolved map for a multi-post page had to be asserted in a test:
   `{appno: 1, record_detail: 3, status: 4, cv: 14, supp: 15}`, with the single-post map unchanged at
   `{appno: 1, record_detail: 2, status: 3, cv: 13, supp: 14}`.

Neither multi-post refno has ever been screened (no Desktop folder, no state file, no offline fixture), so
there is no contaminated history to reconcile.

---

## 9. Test Plan

| Level                | Coverage                                                                                                                                                                                                                                                             |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit — `records.py`  | Header labels wrapped in `<a>` resolve the same map as bare labels; multi-post map shifts by one; a multi-post page yields appno, status, cv_url and record_detail_url for **every** row; the `Post applied for` value is never mistaken for the record-detail cell. |
| Unit — fixture guard | The mock records page keeps link-wrapped headers, so the suite cannot silently return to testing a path production never takes.                                                                                                                                      |
| Unit — JD split      | Base plus delta reconstruction; bullets naming a post land in that post's delta; unnamed bullets stay shared; full-time and part-time variants inherit the same bullets; provenance points at the source sentence.                                                   |
| Unit — grouping      | Post universe from the column values, in first-appearance order; a blank post value on a multi-post page produces the needs-confirmation block and never a guess; the universe holds exactly the posts that received applications (a post with zero applicants is out of scope — see FR-6). |
| Unit — report        | One `<details>` per post; the shared panel carries the advertisement text with the named contact redacted and the raw text left unmodified in `_pipeline`; section order follows the post universe; no cross-post table.                                            |
| Integration          | A multi-post fixture runs the full wrapper chain and produces one report with the expected per-post counts.                                                                                                                                                          |
| Regression           | The single-post path is unchanged: same scores, same file names, same report shape.                                                                                                                                                                                  |
| Cache                | Adding one applicant to post B does not invalidate post A's parsed, scored or per-applicant artifacts.                                                                                                                                                               |

Baseline at the start of the multi-post work (HEAD `1e8e499`, before the prerequisite fix): **514 passed,
1 skipped**. Current baseline at PRD v1.2.0 (HEAD `90b09e5`, prerequisite fix applied): **517 passed,
1 skipped** — measured on 2026-09-17; the three added tests are the two column-map assertions and the fixture
guard. An earlier revision of this PRD quoted 502, which was stale. Redirect pytest's output to a file before
grepping it: the temporary-directory cleanup prints a trailing `SystemExit: 1` that hides the summary line.

```bash
venv/Scripts/python.exe -m pytest backend/tests -q > "$LOCALAPPDATA/Temp/pytest.txt" 2>&1
grep -E "passed|failed|error" "$LOCALAPPDATA/Temp/pytest.txt" | tail -3
```

---

## 10. Risks and Mitigations

| Risk                                                               | Mitigation                                                                                             |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Bullet attribution misreads a post-specific requirement as shared. | Show every derived delta with its source sentence in the HR conditions grill and require confirmation. |
| Scores shift because the JD now differs per post.                  | Expected and intended. Never promise HR that a re-screen reproduces earlier numbers.                   |
| The board is rewritten whenever any group changes.                 | Accepted: board generation is cheap; the expensive per-applicant work stays cached.                    |
| An applicant's post string does not match the universe.            | Needs-confirmation block (FR-7); never guessed.                                                        |
| A new run status is swallowed by the host.                         | Register it in the host envelope whitelists (FR-7).                                                    |
| Legacy cached artifacts lack the post dimension.                   | They read as "post missing" and recompute once; existing caches are moved, never deleted.              |

---

## 11. Non-Functional Requirements

- **Privacy:** no names, emails, phones or salaries in any HTML, PDF, manifest or log. Identity remains
  `refno` / `appno`. Report contents are never loaded into the model context. The advertisement's own contact
  block reaches the report inside the JD text, so it is redacted at render time (FR-6). This was a
  pre-existing leak, not one this feature introduced: phone numbers were already replaced, the named contact
  was not.
- **Determinism:** the same inputs yield the same scores; post derivation must be reproducible and auditable.
- **No new dependencies:** native `<details>` for the report; no JavaScript added.
- **Backwards compatibility:** the single-post path and the existing file names must not change.

---

## 12. Open Questions and Deferred Items

1. **Shared JD panel content.** This PRD specifies the advertisement text with the named contact redacted and
   shared-only parsed tags. If HR finds the post-specific bullets confusing inside the "shared" panel, revisit.
2. **Non-blocking, pre-existing:** the offline-folder path maps CV files back to application numbers by
   **file name** (`_appno_by_cv_filename`). Measured demo CV file names are distinct per applicant and contain
   no application number. If the same person's two applications ever upload an identically named file, only one
   file exists in the folder and the other application lands in `candidates_without_cv` — a graceful
   degradation, not silent corruption. The WebBridge path is immune because it always saves `cvs/<appno>.pdf`.
3. **Deferred:** if an advertisement ever lists one application number against two posts, `appno` stops being a
   unique row key and the report file names collide. Not implemented because it has not been observed. A
   recorded hazard for that day: `safe_pack_id("Senior Project Fellow (Full-time)")` yields
   `Senior_Project_Fellow__Full-time_`, which already contains a double underscore, so a `__` separator would
   need the slug's underscore runs collapsed first.
4. **Deferred:** making the column map fail loudly (rather than falling back to hardcoded positions) when a
   header row is present but the expected labels are missing.

---

## 13. Implementation Handover

This section is written for an engineer or agent picking the work up with no prior context. Sections 1–12
state **what** to build; this one states **how to work in this repository safely**. It repeats no page facts —
those are in Section 2.

### 13.1 Implementation order

Take the steps in this order. Each is independently testable, and the later steps assume the earlier ones.

| # | Step | Lands in |
| - | ---- | -------- |
| 1 | Add `post` to the column map **and** `JASCandidate.post` **in the same change**, so a mapped key always has a field to land in. The verified multi-post map is `{appno: 1, record_detail: 3, status: 4, cv: 14, supp: 15, post: 2}`. | `jas_import/records.py` |
| 2 | Expose the multi-post flag from the three signals (FR-1); carry the post into the parsed candidate reference (FR-2). | `jas_import/records.py`, `jas_import/skill.py` |
| 3 | Build the ordered post universe from the candidate references, plus the grouping helper that the pipeline and the report both use. An applicant with a **missing** post value on a multi-post page goes to the needs-confirmation block (FR-7); never a guess. | `screening_core` (shared helper) |
| 4 | Base ⊕ delta derivation with provenance (FR-4). | `jd-parser` |
| 5 | Per-post scoring groups (FR-5); add the post dimension to the cache keys (Section 6). | `pipeline/scripts/run_pipeline.py`, `screening_core` |
| 6 | One `<details>` per post in the board (FR-6). | `report-gen/src/report_gen/html_board.py` |
| 7 | Per-post grill, grouped by base name, stopping once (FR-9). | `screening_core/jd_overrides.py`, `run_jas_screening.py` |
| 8 | Per-post update checking (FR-12) and the multi-post reply text (FR-11). | `jas-import/scripts/check_updates.py`, `AGENTS.md`, the `hr-cv-screening` skill |

Step 3 no longer restructures the payload. With FR-6.4 withdrawn (v1.2.1) the flat candidate list already
carries everything the pipeline needs, so `job_payload_from_html` only gained `post` on each candidate and the
multi-post flag on the job — which keeps the single-post payload shape identical apart from the added keys.
The single-post regression risk therefore moved to step 5.

### 13.2 The real entry point is a wrapper chain, not `run_pipeline.py`

The HR-facing entry point is several scripts deep. **Verify behaviour through the chain, never by calling
`run_pipeline.py` directly** — a direct call bypasses the host envelope and will report success for a run the
product cannot actually deliver.

```
host-envelope/scripts/run_workbuddy_tool.py    screen_refno
  ├─ folder target  →  jas-import/scripts/run_jas_import.py <folder>
  └─ refno / URL    →  webridge-collect/scripts/run_webridge_collect.py <refno> --driver webbridge
                         └─ jas-import/scripts/run_jas_import.py           (forwards argv verbatim)
                              └─ jas-import/scripts/run_jas_screening.py   (auto-enables --resume, line 340)
                                   └─ pipeline/scripts/run_pipeline.py
```

Two consequences, each of which has already shipped a defect here once:

- **New statuses and keys must be whitelisted.** Any new run status or missing-input key — for example the
  needs-confirmation state in FR-7 — must be added to the host envelope's `ALLOWED_STATUS`,
  `ALLOWED_ERROR_CODES` and `ALLOWED_MISSING` lists. Without that, `project_host_return` collapses the
  question into a generic `error` and HR never sees it.
- **Never read a result out of the output directory without gating on the current run's status.** A run that
  stops early (`need_input`, `conditions_pending`, `error`) writes **no** manifest, so the *previous* run's
  manifest is still on disk. Projecting it reports stale reports as this run's result and hides the question
  the run stopped to ask. `run_workbuddy_tool.py` gates on `status in ("success", "partial_success")` — keep
  that gate on any new code path that reads the output directory.

### 13.3 `--resume` will make your code changes look like no-ops

`run_jas_screening.py:340` turns `--resume` on automatically on any second run of the same job folder. The
resume decision is keyed on **inputs** (JD bytes, CV bytes, the conditions file) and never on **code**. So
after editing scoring logic in `engine.py`, `taxonomy.py` or similar, re-running the same refno reuses the
cached `score-*.json` and the change appears to do nothing.

When a change must be observable, **move — never delete** — the cached artifacts aside first:

| Move these | Effect |
| ---------- | ------ |
| `detail-*.json`, `rows.json`, `board-row-*.json`, `report-fingerprints.json` | forces a re-score |
| also `jd-parse.json`, `jd-context.txt` | forces a JD re-parse |
| also `extracted-*.json` | forces a full re-parse (slowest) |

Move them to `_pipeline/_backup-<timestamp>/`. A full re-parse is **not** score-neutral, so never promise HR
that a re-screen reproduces earlier numbers. Bumping `SCHEMA_VERSION` or `config_hash` does **not** invalidate
the cache.

### 13.4 Fixtures already available

- `jas_import/mock.py` generates both page shapes. `mock_records_html(refno, multi_post=True)` returns the
  HTML; `generate_mock_jas_dir(target_dir, multi_post=True)` writes a complete offline job folder
  (`records.html` + `cvs/`). Both default to `multi_post=False`, so existing callers are unchanged. Use the
  multi-post fixture for the integration row of the Section 9 test plan rather than building a new one.
- An offline folder can drive the whole chain without a browser:
  `run_jas_import.py <folder> --output-dir <tmp>`.
- The demo records pages are the agreed stand-in for the real `records.php`. Appendix A re-runs the page
  checks; re-verify against the real pages when they become available.

### 13.5 Invariants that must not break

1. **The single-post path stays byte-identical** — same scores, same file names, same report shape. It is the
   control proving the post dimension did not leak.
2. **One refno → one Desktop folder**, `Desktop/workbuddy-cv-screen/<refno>/`. Never one folder per post.
3. **No cross-post ranking**, and no wording implying scores are comparable across posts.
4. **No names, emails, phones or salaries** in any artifact, log or manifest. Identity is `refno` / `appno`.
5. **Never load report contents into the model context.**
6. **Never re-run the HR conditions command unchanged** — it stops at the same question again and HR sees a
   loop. Never rename, move or delete `_pipeline/jd-overrides.yaml` to get past the gate: that silently
   discards HR's conditions. Stored conditions are the grill's default answer, never a substitute for asking,
   and `check_updates` is the only flow that does not grill.
7. **Move cached artifacts, never delete them.**
8. **Do not run `git stash`, `git gc` or `git repack` in this repository** — an interrupted repack has
   destroyed objects here before. Do not push unless asked.

### 13.6 Operational context that does not live in this repository

Some working rules live in the assistant's local memory under `.workbuddy-ai/memory/`, which is **git-ignored**
and therefore does not travel with the repository. Everything relevant to this feature is restated in §13.5 so
this document stands alone; anything else must be handed over in conversation, not assumed.

---

## 14. Sign-off

| Role          | Name                       | Status |
| ------------- | -------------------------- | ------ |
| Product Owner | HR Screening Product Owner | Draft  |
| Engineering   | pending                    | Draft  |

---

## Appendix A — How to re-verify the page facts

Structural checks only; none of these print applicant data. Note that on Windows the temp directory is
`$LOCALAPPDATA/Temp` — `/tmp` does not exist there and a write to it fails.

```bash
# Fetch the raw records pages (demo)
TMP="${LOCALAPPDATA:-/tmp}"; [ "$TMP" = "/tmp" ] || TMP="$TMP/Temp"
REC="$TMP/rec.html"
curl -sL "https://jes-web-demo.vercel.app/records.html?refno=260917001" -o "$REC"

# The flag is NOT an attribute
grep -c 'data-multi-post' "$REC"          # -> 0
grep -o 'multi-post[a-z-]*' "$REC"        # -> multi-post-table, multi-post-value

# Table class and the JD key/value row
grep -o '<table[^>]*job-detail-table[^>]*>' "$REC"
grep -o 'Multi-post</td>[^<]*<td[^>]*>[A-Za-z]*' "$REC"
```

```python
# Resolve the column map from the page itself (same file the shell block above fetched)
import os, sys
sys.path.insert(0, ".codex/skills/jas-import/src")
from jas_import import records as R

local = os.environ.get("LOCALAPPDATA")
rec = os.path.join(local, "Temp", "rec.html") if local else "/tmp/rec.html"
html = open(rec, encoding="utf-8", errors="replace").read()
table = R._find_table(R.parse_tables(html), "job-detail-table")
print(R._candidate_column_indexes(table))   # multi-post -> record_detail 3, status 4, cv 14, supp 15
```

Re-run the checks when the real (non-demo) JAS pages are available: this PRD's page facts come from the demo
site, which is the agreed stand-in for `records.php`.

## Appendix B — Field map for the `Post applied for` column

| Layout      | Cell index | Header label        | Value shape                               |
| ----------- | ---------- | ------------------- | ----------------------------------------- |
| multi-post  | 2          | `Post applied for`  | one post label, e.g. `Research Associate` |
| single-post | —          | absent from the DOM | —                                         |

The cell holds plain text (no link), a single value, and its value is exactly one of the options the
application form offered.
