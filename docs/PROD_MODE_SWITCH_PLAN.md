# Production-mode switch — implementation plan

**Status:** drafted 2026-09-24, revised three times the same day — against HR's saved prod pages
(§0), against the owner's answers to §2 (now §2 "Decisions"), and against the owner's answers to
the three follow-ups those raised.
Nothing implemented. Code was only read, never changed.
**Next step:** §3, on an explicit go-ahead. Every §2 decision is closed; §2.12/§2.13 are
pre-existing items and the skill-copy analysis.

The goal is a single switch that moves the whole screening flow between the public demo
platform and the real internal JAS system, with a readiness check in front of both.

---

## 0. Verified against the real pages (HR's saved snapshot, 2026-09-24)

Source: `C:\Users\User\Desktop\jasweb\`, downloaded by HR.

- `Job Application Recordslist.html` (8,770 bytes) — the real **list** page.
- `Job Application Recordsrecords.html` (46,756 bytes) — the real **detail** page.

The saved record is a dummy (`refno 190001010`, `appno 123456`, posting date `1900-01-01`),
so its **shape** is trustworthy and its **content** is not.

### 0.1 The list page matches what the ghost cursor expects — no change needed

| what the script looks for | what the real page has | result |
| --- | --- | --- |
| `thead input[aria-label="Search column"]` | 10 inputs, `data-n="0"`…`"9"`, inside `<tr class="fancySearchRow">` inside `<thead>` | match |
| `thead input[placeholder*="Filter" i]` | `placeholder="Filter..."` | match |
| a row whose text contains the refno | one data row; its `View` anchor href is `…/internal/records.php?refno=<refno>` | match |
| an anchor whose text matches `/view/i` | `View` | match |

Table class is `listTable job-table`. Pagination is off —
`fancyTable({sortColumn:0, sortOrder:'descending', pagination:false, inputPlaceholder:'Filter...', globalSearch:false})`
— so the refno filter does not have to page through results.

→ **The visible human flow works on prod.** `fallback_direct_url` should be rare, not expected.

### 0.2 The records page has the same 39-column table, and the column map is already header-driven

`#f-list.listTable.job-detail-table`, 3 rows: 39 `<th>` headers, 39 `<th>` filter cells,
39 `<td>` data cells. `_candidate_column_indexes` (`jas_import/records.py:306`) resolves to
`{appno: 1, record_detail: 2, status: 3, cv: 13, supp: 14}` — **identical to its hard-coded
fallback**, and it arrives there by reading the header labels, not the positions.

→ The user's objection was correct and is now moot: the column map already works by header.
**No work item is needed for column mapping.**

### 0.3 The CV link is scraped, and `id` **is** the appno

Real markup:

```html
<a href="https://jobs.polyu.edu.hk/internal/file.php?t=cv&amp;id=123456&amp;refno=190001010">
```

Measured on that page: `appno` = 123456, `id` param = 123456, so `appno == id` → **True**;
the `refno` param also equals the job's refno.

The collector already reads the anchor's `href` and fetches exactly that URL
(`collect.py:176` → `fetch_bytes`), and nothing anywhere constructs a CV URL — so the user's
"do not hand-build it" objection is also satisfied by the existing code.
`cv_link_for_appno`'s fail-closed rule stays exactly as it is; on prod it will now *pass* rather
than drop the link, because the appno is present in the query.

### 0.4 Multi-post: **no signal at all on the saved prod page**

`multi_post_signals` → `{table_class: False, post_header: False, jd_field: False}`.
The page has **no `Post applied for` column** (the header row runs `No.`, `Application no.`,
`Online job application form summary (printable version)`, `Status`, `Title`, `Surname`, …
straight through with no post column), and the JD key/value block has no `Multi-post` field.

The user confirmed 2026-09-24 that this is genuinely how prod looks — not a dummy-record artefact.
**Decision recorded in §2.1: prod is single-post for now.**

### 0.5 What else the saved page settled

- `parse_job_html` runs against the saved page and returns a complete payload: refno (9 digits),
  job block, `jd_text`, one candidate carrying `appno` / `status` / `cv_url` / `record_detail_url`,
  `multi_post: False`. **The parser is not the problem; the multi-post signal simply is not there.**
- `_query_value(url, "id")` (`records.py:300`) already reads `appno` out of the CV URL, so the
  appno/`id` equality is consumed by the existing code path, not an assumption.

---

## 1. Confirmed facts (read from the code and from the live machine, 2026-09-24)

### 1.1 The two sites

| | Demo | Prod |
| --- | --- | --- |
| Host | `jes-web-demo.vercel.app` | `jobs.polyu.edu.hk` |
| List page | `/` (searchable table, Ref-no filter, `View` links) | `/internal/records.php` — **confirmed by the user 2026-09-24** |
| Job detail | `/records.html?refno=<refno>` | `/internal/records.php?refno=<refno>` |
| CV file | `/uploads/CV_<Given>_<Surname>.pdf` (person-named) | `/internal/file.php?t=cv&id=<appno>&refno=<refno>` |
| Login | none | SSO, in HR's own browser session; post-login domain is `/internal/` |
| Applicant table | Title / Surname / Given name / Name in Chinese / HKID or passport no. / Email / Phone | **same 39 columns**, verified in §0.2 |
| Post column | `Post applied for` on multi-post jobs | **absent** — §0.4, §2.1 |
| Report pack | `Desktop/workbuddy-cv-screen/<refno>/` | same; **kept indefinitely, HR deletes it** (user, 2026-09-24) |

The prod detail URL is already implemented: `screening_core/candidate_id.records_url_for_refno`
(`candidate_id.py:53`) returns `https://jobs.polyu.edu.hk/internal/records.php?refno=<refno>` —
and is **never called by the collector**.

### 1.2 The switch today is demo-on / demo-off, not demo / prod

> **Superseded 2026-09-25** — this is the *pre-change* state, recorded so the defect below is
> legible. `demo_mode.py` and `JES_DEMO_MODE` no longer exist; see §3.A.

`JES_DEMO_MODE` and the repo-root `demo_mode.json` are read by
`screening_core/demo_mode.demo_mode_settings` (`demo_mode.py:38`) and applied by
`apply_demo_defaults` (`demo_mode.py:61`). Three measured behaviours:

1. **Only the literals `1/true/on/yes` and `0/false/off/no` are honoured.** Any other value
   (`JES_DEMO_MODE=prod`, `JES_DEMO_MODE=production`) is not recognised, so the function falls
   through and reads `demo_mode.json` instead — silently returning demo mode.
2. **`JES_DEMO_MODE=1` ignores `demo_mode.json`'s `base_url`** and uses the hard-coded
   `DEFAULT_DEMO_BASE_URL`.
3. `apply_demo_defaults` injects `--base-url` **only when the caller passed no `--records-url`**,
   so an explicit URL bypasses demo injection entirely.

**Turning demo off is not prod mode.** With demo off, a bare refno leaves `base_url = None`, and
the collector gates the visible human flow on `if base_url and refno`
(`webridge_collect/collect.py:137`). The condition fails, so the ghost-cursor list-page flow is
skipped and the run navigates straight to the records URL instead (`collect.py:148`).

`JES_DEMO_MODE` is **deleted** by this plan (§2.10).

### 1.3 `base_url` currently carries two unrelated meanings

`base_url` is used both as the **list-page origin** for the human flow (`navigate_like_human`,
`collect.py:98`: `list_url = f"{base_url.rstrip('/')}/"`) and as the **template base for building
the records URL** (`build_records_url`, `collect.py:73`, which produces `{base}/records.html?refno=`).
On the demo the two coincide. On prod they do not, and the second one is wrong.

`build_records_url` also duplicates logic that already exists and is already correct:
`records_url_for_refno` (`candidate_id.py:53`).

### 1.4 The readiness check does not exist

`run_workbuddy_tool._run_request_jas_access` (`run_workbuddy_tool.py:191`) only *formats* a state
the caller asserts via `--jas-session`; it verifies nothing. `_jas_session`
(`run_workbuddy_tool.py:86`) reads back the `need_input` that a **failed** run produced, so today
the browser/session state is only discovered by failing first.

Nothing anywhere observes "HR is signed in to the internal system". The WebBridge `/status`
endpoint reports that an extension is attached, not that a session is valid.

**The login check does not need the SSO hostname.** The user confirmed the post-login domain is
`https://jobs.polyu.edu.hk/internal/`, so "signed in" can be decided by landing inside `/internal/`
*and* finding the records table — a positive test, not a heuristic on an unknown IdP host.

### 1.5 Both modes share the same client-side prerequisites

The daemon (`127.0.0.1:10086`) and the Kimi extension must be up for **either** site, because
`--driver webbridge` is the default and the collector auto-starts the daemon
(`run_webridge_collect.py:172`). Only the login check is prod-only. This matches the user's
instruction of 2026-09-24: check Chrome + extension in both modes, add the login check for prod.

### 1.6 A site switch collides on refno-keyed paths — measured

> **Fixed 2026-09-25** (§3.C): `cvs/` is cleared before collecting, both caches are namespaced by
> site, and `claim_pack_site` archives a pack stamped with the other site instead of resuming it.

- `run_webridge_collect.py:169` → `folder = collect_root / (refno or "job")`, i.e.
  `data/jes_webridge/<refno>/`. `collect_job` **rewrites `records.html` unconditionally**
  (`collect.py:151`), so the HTML itself is refreshed — but `(folder / "cvs").mkdir(exist_ok=True)`
  (`collect.py:134`) **never clears the folder**, so CVs from a run on the other site for the same
  refno stay on disk and `_discover_cvs` will pick them up.
- `run_jas_screening.py:377` → `work_dir = pipeline_work_dir(job_dir)`, i.e. the Desktop pack's
  `_pipeline/`, and `run_jas_screening.py:380` sets `args.resume = True` **unconditionally**.
  A prod run of a refno already screened on demo therefore **resumes the demo run's parse/score
  cache** and produces a demo-derived report under a prod refno — silently.
- `data/jas_state/<refno>.json` is rewritten per run, so it corrupts the `check_updates` delta
  rather than the scores.

This is a real defect, not a theoretical one: it is the one path where a prod run can produce a
plausible-looking report that is wrong. Fix in §3.C.

---

## 2. Decisions (owner, 2026-09-24)

| # | Question | Decision |
| --- | --- | --- |
| 2.1 | How does prod express a multi-post job? | **It does not.** Prod has no post column and no `Multi-post` JD field. Keep the detection code as-is; **prod is treated as single-post for now.** Do not claim per-post support on prod. |
| 2.2 | The saved page's JD body was only 87 chars | **Real ads are long. Read as much as there is — the cap comes off** (§2.11, §3.K). |
| 2.3 | Session idle timeout | **Unknown, deferred.** Do not build renewal. Keep the pre-flight cheap so it can be re-run by hand. |
| 2.4 | IT rate limits / audit logs | **Unknown, accepted risk.** Note it for the first test. |
| 2.5 | Does HR's machine need VPN / campus network? | **Yes, but it does not concern the agent.** If HR can sign in, the session is inherited. Question closed. |
| 2.6 | Who runs the first prod test? | **The owner, on HR's computer.** |
| 2.7 | Retention of the raw PII surfaces | **Reversed 2026-09-24: no automatic cleanup.** The cost was not worth it — §3.J. |
| 2.8 | Does the demo profile stay in the package? | **Yes.** So the switch must be explicit and visible, and the envelope must carry the active site (§3.E). |
| 2.9 | Same refno screened on both sites | **Real defect** — see §1.6. Fix in §3.C. |
| 2.10 | The switch's env var | **Delete `JES_DEMO_MODE`.** Use `JES_SITE_MODE` only: **`1`/`prod` → prod; unset/empty/`0`/`demo` → demo; anything else refuses to start.** The typo trap is closed — §2.10. |

### 2.10 resolved — the typo trap is closed

The owner accepted the refinement on 2026-09-24. It mattered because a bare "anything else → demo"
lets a typo (`production`, `PROD`, `true`) silently degrade a **real** run to the demo site: the
run succeeds, the report looks normal, and the numbers come from the wrong site. Same class of
failure as §1.2's silent fallthrough, which is why §1.2 is called out.

| value | result |
| --- | --- |
| `1` or `prod` | prod |
| unset, empty, `0`, `demo` | demo |
| anything else (`production`, `PROD`, `true`, `2`) | **refuse to start**, non-zero exit |

`=1` → prod is exactly as the owner specified; only the dangerous case changed from silent to loud.

### 2.11 The JD is capped at 3,000 chars on one code path — **the cap comes off**

There are two prompt paths and they disagree:

- **Vision path** — `cv_parser/service.py:310-311` passes the JD **uncapped**:
  `{"type": "text", "text": f"JD Context:\n{jd_text}"}`. This is the primary path.
- **Text-fallback path** — `cv_parser/helpers.py:1040` compresses the JD to
  **3,000 chars** (`compress_cv_text(raw_text=jd_text, max_chars=3000)`) and the CV to 12,000.
  `build_compressed_prompt` has exactly **one** call site (`helpers.py:1032`), so this is a
  one-line change.

Two demo jobs measured 3,968 and 4,664 chars, so the fallback **already truncates real JDs today**.
**Owner decision 2026-09-24: remove the cap.** Work item §3.K.

### 2.12 Pre-existing items

- **`data/reports/comparison-260806009.xlsx` — resolved 2026-09-25: it is test data, keep it
  tracked.** No action. (`git ls-files data/reports/` also shows `report-260806009-AE.pdf` and
  `.png`; the reports measured PII-free.)
- **The HR skill's three copies — analysed 2026-09-25, baseline chosen.** See §2.13.

### 2.13 The HR skill's three copies — what they are, and which is the baseline

They are **not** three copies of one role; each is loaded by a different thing. Measured 2026-09-25:

| # | path | lines | md5 | loaded when | paths inside |
| --- | --- | --- | --- | --- | --- |
| 1 | `~/.workbuddy-ai/skills/hr-cv-screening/SKILL.md` | 641 | `10f1cc99` | this machine triggers the skill **directly** (not through Vera) | real machine paths |
| 2 | `~/.workbuddy-ai/plugins/marketplaces/my-experts/plugins/hr-cv-screener/skills/hr-cv-screening/SKILL.md` | 666 | `33fdf8a8` | HR (or the user) talks to the **Vera expert** | install placeholders |
| 3 | `release/expert/hr-cv-screener/skills/hr-cv-screening/SKILL.md` | 666 | `33fdf8a8` | the **installer / CI** | install placeholders |

`build_release.py` ships the committed snapshot by default and `--sync-expert` refreshes it from the
live expert dir (`build_release.py:42`, `:53-63`, `:163`). There is **no fourth copy** in the repo:
`.codex/skills/` holds the twelve engine skills (`webridge-collect`, `jas-import`, …) and no
`hr-cv-screening`.

**#2 and #3 are byte-identical** (`33fdf8a8`), so the only real divergence is #1 vs #2 — four hunks,
39 changed lines under `diff -u`:

1. **`## Fixed paths`** — #1 has the real repo path; #2 has `C:/agent-cv-screening`.
2. **The Chrome extension path and the WebBridge helper CLI** — #1 has real paths; #2 has
   `%LOCALAPPDATA%/…` and `%USERPROFILE%/…`.
3. **#2 carries +25 lines that #1 lacks**: `## Running the gate's JD parse without scoring` — the
   `parse-job` forwarding trap, and how to read the five JD slots without scoring.
4. One cosmetic line ("`C:/Users/User/Desktop/...`" vs "the user's Desktop").

**The placeholders are deliberate, not stale.** `setup_engine.py:230-232` rewrites three spellings
of `C:/agent-cv-screening` to the real `engine_dst` at install time (default `C:\agent-cv-screening`
on Windows, `~/agent-cv-screening` on macOS — `setup.bat:9-11`, `setup.command:10`). So #2/#3 carry
tokens the installer resolves, and #1 is the developer's local file where they are already resolved.

**Baseline decision: #2 is the content baseline.** It is the superset — everything #1 has, plus the
25-line section. So the direction is **#2 → #1**, never the reverse, and #3 follows #2 through
`--sync-expert`. #1 must be **derived, not copied**: the sync applies the reverse substitution
(`C:/agent-cv-screening` → the real repo path, `%LOCALAPPDATA%` / `%USERPROFILE%` → real paths).
Deterministic and scriptable, so nobody has to hand-edit three files again.

**Gap found while doing this:** nothing substitutes `%LOCALAPPDATA%` or `%USERPROFILE%`.
`setup_engine.py` handles only the three `C:/agent-cv-screening` spellings, so those two lines in
#2/#3 are **Windows-only** — correct if the reader expands a Windows env var, and simply wrong on
macOS, where the Chrome profile is `$HOME/Library/Application Support/Google/Chrome/…` and the
WebBridge helper is under `$HOME/.kimi-webbridge/…`. The installer supports macOS, so this is a real
packaging gap: small, but it can mislead an agent on a Mac. Added to §3.F.

### Accepted unknowns (documented, not blocking)

Session idle timeout (2.3) and IT rate limits (2.4). Neither blocks §3; both are recorded so a
prod failure can be diagnosed quickly.

---

## 3. Work items

### A. Site-profile layer (replaces the demo-only switch) — **DONE 2026-09-25**

- [x] `screening_core/demo_mode.py` — replaced by `screening_core/site_mode.py`. The resolver is
  `site_profile(mode=None, *, repo_root=None)`, returning
  `{mode, base_url, list_url, records_url_template, allow_hosts, expects_login,
  human_flow_available, tab_group_title}`; `resolve_site_mode()` returns just the mode.
  Precedence: explicit argument > `JES_SITE_MODE` env > `JES_SITE_MODE` in `.env` > the profile
  file's `default` > built-in.
  **The `.env` step was added during implementation.** The CLIs resolve the mode before any
  settings object copies `.env` into the environment, so without it the switch documented in
  `.env.example` would have been silently ignored and the run would have used the demo site.
- [x] **`JES_DEMO_MODE` and `apply_demo_defaults` are deleted**, with no compatibility shim.
- [x] Unknown `JES_SITE_MODE` values are refused per §2.10: all three CLIs exit non-zero with
  `error_code: bad_site_mode`. Smoke-tested on `run_webridge_collect.py`, `run_jas_screening.py`
  and `check_updates.py`.
- [x] The repo-root `demo_mode.json` is replaced by `site_profiles.json` holding both profiles;
  `mode` is the one key a file may not override.
- [x] `JES_SITE_MODE` added to `.env.example` and to the release `START-HERE.txt`.
- [x] **Not on this list, done because it is the same rename:** with `demo_mode.json` gone, every
  live reference to it had to be corrected — `AGENTS.md`, `jas-import/SKILL.md`,
  `.workbuddy-ai/instructions.md` (whose `## Demo mode … currently ON` section became
  `## Site mode`), `release/build_release.py` (`ENGINE_COPY`, the required-files list and the
  module docstring) and `release/payload/scripts/setup_engine.py`'s docstring.
- [x] **`apply_site_defaults` sets `--no-cookie` only on a site that expects no login.** The first
  cut set it on both, which made the `need_input(jas_session)` branch in `run_jas_screening.py`
  unreachable — a silent break of the host contract documented in `instructions.md`. It is now
  gated on the profile's `expects_login`: demo is cookie-free, prod still asks for JAS access on
  the HTTP path. The WebBridge flow screens a folder and never reaches that branch.

### B. URL building — one source of truth — **DONE 2026-09-25**

- [x] `build_records_url` (`collect.py`) delegates to `candidate_id.records_url_for_refno` when
  there is no explicit template; the template comes from the active profile.
- [x] The hard-coded `https://jobs.polyu.edu.hk/internal/records.php` string is gone from
  `collect.py` — the URL now lives only in `site_mode.BUILTIN_PROFILES`.
- [x] `navigate_like_human` takes `list_url` from the profile instead of `base_url + "/"`.
- [x] `group_title` comes from `profile["tab_group_title"]` (`JES demo screening` / `JAS
  screening`) at both call sites.

### C. Collector behaviour — **DONE 2026-09-25**

- [x] The human flow is gated on `profile["human_flow_available"]`, not on `base_url`.
- [x] The prod fallback to the direct records URL is unchanged, and is still reported as
  `human_flow: "fallback_direct_url"`.
- [x] **`cvs/` is cleared before collecting** (`shutil.rmtree`, then recreated).
- [x] **Caches are namespaced by site**: `data/jes_webridge/<site>/<refno>/` and
  `data/jas_state/<site>/<refno>.json`. Implemented as a **subdirectory**, not the
  `<site>-<refno>.json` filename sketched above — a subdirectory cannot be mistaken for a state
  file by anything globbing `data/jas_state/*.json`.
- [x] **The site is stamped into the report pack and a mismatch is refused.**
  `site_mode.claim_pack_site` writes `_pipeline/site.json`; on a mismatch it archives everything
  except `_backup-*`, the marker itself and HR's own `jd-overrides.yaml`, then returns `False` so
  the caller does **not** set `--resume` and re-scores instead. The HR-facing folder path is
  unchanged.
- [x] `run_webridge_collect.py` has `--site demo|prod` and passes the profile into `collect_job`.
- [x] `run_webridge_collect.py` refuses `--cookie-file` in prod
  (`error_code: cookie_file_not_allowed`).
- [x] The no-silent-degrade rule is unchanged: a missing daemon still returns `need_input`.
- [x] The other two callers were brought into step: `check_updates.py` and `run_jas_screening.py`
  both take `--site` and call `apply_site_defaults`, and `run_pipeline.py` propagates the mode to
  its children through the environment — passing `--site` to the collector alone would have left
  the child chain resolving demo.

### D. Readiness check (new command) — **DONE 2026-09-25**

- [x] New command, e.g. `run_webridge_collect.py --preflight` (or a sibling script), returning a
  PII-free envelope with a per-check list:

  | check | how | mode |
  | --- | --- | --- |
  | `daemon` | `POST /status` → `running` | both |
  | `extension` | `/status` → `extension_connected`, plus the version | both |
  | `login` | navigate to `/internal/records.php`, then require *landed inside `/internal/`* **and** *the records table is present* | prod only |

- [x] Classify the login result by the positive test above, not by an unknown IdP hostname.
- [x] Close the tabs the check opened, the same way a not-found run does
  (`run_webridge_collect.py:198`), so a failed check does not leave a stray page.
- [x] Return distinct, actionable reasons rather than one generic failure, so the persona can say
  the right sentence: `daemon_unreachable`, `extension_disabled`, `not_signed_in`.
- [x] Must be cheap and side-effect-free: no CV download, no pipeline, no report. It must also be
  cheap enough to **re-run by hand mid-flow**, which is the mitigation for §2.3's unknown timeout.

**Implemented as** `.codex/skills/webridge-collect/scripts/run_preflight.py` (a sibling script, which
the item allowed), driven by three new client primitives in `webridge_collect/client.py`:
`webbridge_status`, `extension_version`, `start_webbridge_daemon`. Wired into the host wrapper as the
`preflight` subcommand (`run_workbuddy_tool.py`). 20 tests in `backend/tests/unit/test_preflight.py`.

Four implementation decisions worth recording:

1. **The identifier key is `check`, not `name`.** The first draft keyed each record by `name`, and the
   whole envelope was rejected as `envelope_rejected` — `DENY_KEYS` contains `"name"` because it is
   the candidate-name field. The guard was kept and the key renamed; weakening the PII scan to admit
   a convenience key would have been the wrong trade. A test now asserts no envelope carries `name`.
2. **`daemon` starts the daemon before it reports failure.** A check that said "not running" for
   something the run starts by itself would block HR on a non-problem. It starts it, waits, then
   reports what is actually true.
3. **`--driver http` reports an empty check list**, not a pass. No browser is involved, so there is
   nothing to have checked; claiming OK would be a lie the persona would repeat to HR.
4. **`login` runs only where the profile says `expects_login`** (prod). On the demo the check is not
   emitted at all, and `auth` stays `null` rather than asserting a session state never observed.

Verified against the live daemon on this machine: extension v2.0.17, `daemon` and `extension` both
OK, bad site mode refused with `bad_site_mode`.

### E. Host envelope — the whitelists that silently swallow new values — **DONE 2026-09-25**

This is the trap already recorded once (a question collapsed into `error` because a status was
missing from the whitelist). Every new value must be added in `host_envelope/schema.py`:

- [x] `ALLOWED_TOOLS` (`schema.py:7`) — add the new tool name.
- [x] `ALLOWED_ERROR_CODES` (`schema.py:9`) — add the browser/login reasons.
- [x] `ALLOWED_MISSING` (`schema.py:26`) — add browser/extension tokens. **Reuse `jas_session`**
  for the login failure so it rides the existing `auth.jas_session` projection (`project.py`, and
  `_jas_session` at `run_workbuddy_tool.py:86`).
- [x] `ALLOWED_SESSION` (`schema.py:31`) — `expired` already exists; use it for a signed-out session.
- [x] `TOP_KEYS` (`schema.py:32`) — add `checks` **and `site`** (§2.8: the envelope must say which
  site the run used, or a wrong-site run is undetectable after the fact).
- [x] `run_workbuddy_tool.py:202` — add the subcommand and wire it into `main()`.
- [x] `docs/workbuddy/PRD-Host_Tool_Return_Whitelist_v1.0.md` and
  `docs/workbuddy/host-tool-return.schema.json` — keep in step with the code.
- [x] Persona and skill must call the check **before** `screen_refno`, and on failure hand the run
  back to HR instead of running it anyway. → landed with batch F: the persona gained
  **"Stage — Before the first run (readiness)"** ahead of the refno gate, and the skill's Commands
  section pins `preflight` ahead of the first `screen_refno` of the conversation, with the
  hand-back rule spelled out per reason.

**Implemented as** four new frozensets in `schema.py` (`ALLOWED_SITES`, `ALLOWED_CHECKS`,
`ALLOWED_CHECK_REASONS`, `CHECK_KEYS`), `site`/`checks` added to `TOP_KEYS`, validation for both in
`validate_envelope`, `_project_site` / `_project_preflight` in `project.py`, and the `preflight`
subparser in `run_workbuddy_tool.py`. Tests in `backend/tests/unit/test_host_envelope.py`.

Two things worth recording beyond the list:

1. **`site` is stamped on every envelope**, not only on `preflight` — including the rejected one.
   The whole point of §2.8 is that a wrong-site run must be detectable *after* it happened, and the
   envelope that most needs to say where it ran is the one that failed.
2. **The published JSON schema was further behind than this list assumed.** It had no multi-post
   keys at all — no `posts`, no `ranking[].post`, no `conditions_pending` — so the documentation
   half of this item was a rewrite, not an append. `test_published_schema_matches_the_code_whitelists`
   now asserts the shipped schema's enums equal the code's frozensets, which is what stops the drift
   from recurring. (`jsonschema` is not installable on this machine — no PyPI access from either
   interpreter — so the guard compares the document against the code directly instead of validating
   a fixture against it.)

### F. Persona and skill — three copies must stay in step — **DONE 2026-09-25**

Three copies, three roles, and they have diverged — the full analysis is in §2.13.
**Baseline = the live expert copy; #1 is derived from it; #3 follows it via `--sync-expert`.**

- [x] `~/.workbuddy-ai/plugins/marketplaces/my-experts/plugins/hr-cv-screener/skills/hr-cv-screening/SKILL.md`
  — the **live expert copy, content baseline** (was 666 lines with install placeholders; now 727)
- [x] `~/.workbuddy-ai/skills/hr-cv-screening/SKILL.md` — this machine's direct skill, **derived**
  from the live copy with the reverse path substitution (now 727 lines, identical except paths)
- [x] `release/expert/hr-cv-screener/skills/hr-cv-screening/SKILL.md` — the committed snapshot,
  refreshed from the live copy by `build_release.py --sync-expert` (done in the 1.2.0 build)

Edits needed in each:

- [x] Replace `## Demo mode (public demo platform)` (`SKILL.md:506`) with a **two-mode** section:
  what demo is, what prod is, how the switch is set, and that a prod run needs a signed-in browser.
  → `## Two modes — demo and prod (the JES_SITE_MODE switch)`, including the campus-network/VPN
  need and the `login` check's positive test.
- [x] Turn `## Diagnosing need_input / jas_session missing` (`SKILL.md:112`) from reactive into
  the documented form of the **proactive** check, and add the three HR-facing sentences (open
  Chrome / enable the extension at `chrome://extensions` / sign in to the internal system). Keep
  them as one message in HR's language, said once. → Renamed `## Readiness before a run, then
  diagnosing a failure`; the one message is written out in English and 繁中.
- [x] Add the prod URLs (`/internal/records.php`, the list page, the CV link shape) to
  `## Fixed paths` so the agent never guesses them. → Includes "scraped from the page, never
  assembled" for the CV link and header-driven columns.
- [x] Record the §2.1 limitation: **prod jobs are screened as single-post.** If an HR question
  implies per-post support on prod, the honest answer is that the internal system does not expose
  the post on the records page. → In the two-mode section, with the demo contrast.
- [x] Keep the existing rule that HR is never asked for cookies, passwords or tokens — it already
  exists and must not be weakened for prod. → Restated in the two-mode section and the readiness
  stage.
- [x] `agents/hr-cv-screener.md` — add a **"Stage — Before the first run (readiness)"** ahead of
  the refno gate. Today the persona only has a "When something goes wrong" stage. Both modes get
  the browser/extension check; only prod gets the login check.
- [x] Expert package: after any edit run `validate_expert.py` then
  `register_expert.py <dir> --session-id a4f160b6-bd71-4d9a-aee1-ecfacb81d1e6`. Back the package up
  first — it is **not under version control**. → Backup at
  `~/.workbuddy-ai/backups/hr-cv-screener-20260925-104339`; validate + register re-run after the
  final edit, both pass.
- [x] Update `TESTING.md` with the new readiness cases (Batch 5 is still unrun). → **Batch 0**
  added (T0a–T0f); the note that Batch 5 is unrun stands.
- [x] **Fix the two Windows-only path lines** (§2.13): `%LOCALAPPDATA%` and `%USERPROFILE%` are not
  substituted by `setup_engine.py`, which only rewrites the three `C:/agent-cv-screening` spellings.
  Either add them to the installer's substitution table or rewrite those lines as OS-neutral
  instructions — the installer supports macOS, where both are currently wrong. → Chosen the second
  option: both lines now carry the Windows **and** macOS spellings inline, so they are correct
  everywhere and the installer's table is untouched.
- [x] **Add the derivation step** (§2.13) so the three copies stop drifting by hand: derive #1 from
  the live expert copy with the reverse substitution as part of the release/skill-update flow. →
  `build_release.py --sync-dev-skill`: resolves the placeholders to the developer machine's real
  paths and refuses to write if any survive. The old four-hunk drift (including the parse-job
  section #1 lacked) is gone — #1 is now #2 except paths.

### G. Packaging and release — **DONE 2026-09-25** (tag left to the owner)

- [x] `release/build_release.py:44` — `ENGINE_COPY` includes `demo_mode.json`; point it at
  `site_profiles.json`. The demo profile **stays in the package** (§2.8), so ship the file, not
  just the env var. → done with batch A: `ENGINE_COPY` carries `site_profiles.json` (and the
  staged-files list and the docstring were corrected with it).
- [x] Bump the version, run `release/tests/simulate_install.py` and `--update` locally before
  tagging; the release asset name stays version-free on purpose. → **v1.1.8** built 2026-09-25
  (148 files, 396 KB; zip sha256 `a8c69d9a…`); zip contents verified (`site_profiles.json` in,
  `demo_mode.json` absent, `JES_SITE_MODE` documented, expert skill packaged).
  - `simulate_install.py` — **ALL PASS** (3m12s; the installer exited cleanly, the shutdown race
    did not trigger).
  - `simulate_install.py --update` — **ALL PASS** (18m23s; the installer step hit the shutdown
    race, was caught by the pass-marker tolerance below, and the updater then applied the latest
    live release with the API key surviving and the version stamp advancing).
  - **One test-script change, beyond the item list and flagged to the owner:** `run()` in
    `simulate_install.py` is now Popen-based with a `pass_marker` — on a step timeout, if the
    captured output contains the step's completion marker (`Install complete.` for the installer,
    `updated to version` for the updater), the lingering process tree is killed and the step
    passes with a `[WARN]`. Product code untouched; the root cause of the dev-machine shutdown
    race is still unknown (see the batch record and the daily log).
  - **The tag itself is left to the owner** (commit + tag `v1.1.8` + push; CI attaches the zip).

### H. Tests — **DONE 2026-09-25** (most landed with A–E)

- [x] `backend/tests/unit/test_demo_mode.py` — rewrite for the site-profile resolver: precedence,
  unknown-value rejection (§2.10), both profiles. → Became `test_site_mode.py` in batch A
  (`test_demo_mode.py` deleted with `demo_mode.py`): 28 tests covering the full resolution order,
  unknown-value refusal, both profile shapes, `.env` reading, and the shipped-profiles guard.
- [x] New tests: `build_records_url` returns the prod URL with no template; the profile drives the
  list URL; `--cookie-file` is refused in prod mode. → `test_records_url_per_mode`,
  `test_site_profile_prod_shape` / `test_site_profile_demo_shape`. **Note on the third one:** the
  implemented semantics (batch A) is that an explicit `--cookie-file` is *honoured* in prod — what
  prod refuses is to be auto-declared cookie-free (`test_apply_site_defaults_respects_cookie_file`).
  The refusal reading in this list predates that design; a jar is how a prod run *can* carry a
  session, so refusing it would have contradicted `need_input(jas_session)`.
- [x] New test: `cvs/` is cleared before collection (§1.6). →
  `test_collect_clears_stale_cvs_before_collecting` (this batch — the behaviour existed since batch
  C but had no test).
- [x] New test: a report pack stamped with the other site is **not resumed** — it is archived and
  re-scored. This is the regression guard for the §1.6 defect. →
  `test_pack_from_other_site_is_archived_not_resumed` (this batch, at the CLI level; batch A's
  `test_claim_pack_site_other_site_archives` covers the helper).
- [x] New test: the pre-flight envelope survives projection for each failure reason — the
  regression this guards against is a question collapsing into `error`. → Batch E's
  `test_host_envelope.py` projection tests.
- [x] Keep the baseline green (`backend/tests -q`) and respect the `repo_job_state_untouched`
  fixture: any end-to-end test passes its own `tmp_path` `--state-dir`.

### I. Data hygiene — **decided 2026-09-24, no action**

- [x] `data/reports/comparison-260806009.xlsx` is **tracked in git** and contains a candidate name
  (it predates the `data/` ignore rule). Decide separately whether to rewrite history or simply
  stop tracking it. → **Owner's decision (2026-09-24): it is test data and stays as-is** — no
  history rewrite, no untracking. Recorded here so the open item does not silently outlive the plan.

### J. Post-run PII cleanup — **dropped** (decision 2.7, reversed)

The owner reversed 2.7 on 2026-09-24: the cleanup was not worth its cost, so **nothing is deleted
automatically after a run.** The pack and the caches keep everything they hold today.

What that means, stated plainly so it is a choice rather than an oversight:

- After a prod run, these still hold candidate PII on the machine:
  `<pack>/_pipeline/staged_cvs/` (the original CVs, copied in by `_stage_cvs_by_appno`,
  `run_jas_screening.py:213`), `<pack>/_pipeline/extracted-*.json` (parsed CV text),
  `data/cache/*-pii-redaction*.json` (plaintext name/email/phone), and
  `data/jes_webridge/<site>/<refno>/records.html` (the whole applicant table, including
  HKID/passport/email/phone).
- The upside of not cleaning: a re-run of the same refno reuses the collection and the parse cache,
  so a re-score stays cheap and a suspicious run can be re-examined without re-fetching anything.
- The owner's standing rule is unchanged: **HR deletes the Desktop pack when she wants to.**

Two items in §3.C are **correctness fixes, not cleanup**, and must not be dropped along with it:

- clearing `cvs/` before collecting (stale CVs from another site's run being scored), and
- site-namespacing `data/jes_webridge/<site>/<refno>/` and `data/jas_state/<site>-<refno>.json`.

Optional and unscheduled: a manual `--clean-pii` command doing exactly the list above, run only
when someone asks. It costs little and keeps the option available without an automatic step.

### K. Remove the 3,000-char JD cap (§2.11) — **DONE 2026-09-25**

- [x] Remove `max_chars=3000` on the JD in `build_compressed_prompt`
  (`cv-parser/src/cv_parser/helpers.py:1040`), so the text-fallback path honours "read as much as
  there is". Single call site (`helpers.py:1032`); one-line change.
- [x] One implementation check, not a question: if the fallback model rejects an over-long prompt,
  the failure must surface as a clear error naming the JD length — not as a silently truncated JD
  and not as a generic API error. Report the model's real limit if one exists rather than quietly
  re-introducing a cap.
- [x] Add a test pinning a JD longer than the old cap through the fallback path.

**Implemented as** `compress_cv_text` gaining `max_chars: int | None` (`None` = keep every line —
the dedup and whitespace normalisation still run, only the truncation is skipped), the JD call site
passing `None`, and a length-rejection note in `service.py`'s text-fallback `except`: when the
exception looks like a length refusal (`context_length_exceeded`, "prompt too long", …), the
recorded `error_message` gains `prompt_rejected_for_length=true cv_chars=<n> jd_chars=<n>`, and the
model's own limit rides through verbatim inside the original exception text. Three tests in
`test_parser.py`: a 400-line JD (well past the old cap) reaches the prompt in full, the compressor
still truncates when explicitly asked, and the length-rejection path names what was sent.

---

## 4. Test plan for the first prod run

Run by the owner on HR's computer (§2.6).

1. Pre-flight only, no screening: daemon, extension, login — all three green.
2. One single-post refno, small applicant count. Confirm: the envelope's `human_flow` and `site`
   values, and that the board renders CV links (§0.3).
3. Verify the PII surfaces that matter to HR: the board and the per-applicant PDFs must contain no
   name, email or phone. (The `_pipeline/` caches and `data/` **will** hold PII — §3.J, by decision.)
4. Re-run the **same refno** and confirm the collector re-collects, clears `cvs/`, and does not
   resume stale artefacts (§1.6).
5. Only then run a full-size job.

Per-post sections are **not** part of this test plan: §2.1 records that prod is single-post for now.

## 5. Rollback — **guarantees verified 2026-09-25**

- [x] Keep the demo profile working and selectable at all times (§2.8), so a failed prod test
  falls back to a known-good path in one switch. → verified: `site_profiles.json` carries both
  profiles and **`"default": "demo"`** ships in the release package, so unset/`0`/`demo` is the
  fallback with no code change.
- [x] Nothing in this plan changes the scoring engine, so scores are unaffected by the switch —
  but a full re-parse is not score-neutral, so do not mix demo and prod artifacts for the same
  refno (§1.6, §3.C). → verified against the working tree: no scorer / matching / taxonomy file is
  touched by any of A–G.
- [x] No automatic cleanup runs (§3.J), so a suspicious prod pack can be re-examined and re-scored
  in place. Treat that pack as PII-bearing: the original CVs and the parsed text are still inside
  it.
