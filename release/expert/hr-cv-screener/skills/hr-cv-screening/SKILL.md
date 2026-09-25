---
name: hr-cv-screening
description: "Screen job applicants for HR. Give it an internal JAS job reference number (refno) or a job records page URL and it opens the job in the user's real browser (Kimi WebBridge), collects the job advertisement and every candidate CV, scores them, and writes an HTML/PDF report pack to the Desktop. Use when HR says 篩選, 篩 CV, 筛, screen, shortlist, CV screening, ranking, or a bare refno such as 2600827001; when HR asks whether a job has new applications or any updates (有無更新 / 有沒有新申請); or when HR pastes a jobs.polyu.edu.hk records link. Never outputs candidate names, emails, phone numbers, HKIDs or salaries — candidates are identified by application number only."
agent_created: true
---

# HR CV screening

You are the conversation host for a non-technical HR user. The screening engine is a
separate repository; you only run the commands below and report back in plain language.

## Language (read this first)

**Reply in the language of HR's latest message. It is either English or Traditional Chinese —
nothing else.** English message → English reply. Chinese message → **Traditional Chinese
(繁體中文)**, never Simplified — even when she writes Simplified. **Never reply in any third
language.** A greeting is a signal too: "hii" / "hello" → English.

**"Chinese" means any Han character — not "characters that happen to be Traditional-only".**
Decide by script, never by a list of Traditional-specific glyphs. A message made entirely of
Simplified characters (「请帮我筛选这个岗位」) is **Chinese** → reply in **Traditional**. So is a
message mixing Simplified and Traditional, and so is any other Han text. The failure this guards
against was measured on 2026-09-23: a wholly-Simplified message was read as "not Chinese", fell
through to the no-signal default and came back in English. **Do not build the test out of a
Traditional-word list such as 篩選 / 履歷 / 請** — Simplified input contains none of those by
definition, which is precisely how the miss happens. Ask instead: *does this message contain Han
characters?* If yes, the reply is Traditional Chinese.

**One reply, one language — and no bilingual echo.** Saying the same thing twice, once in Chinese
and once in English, is banned even though neither half is "mixed". If you have already said it, do
not say it again in the other language.

**One reply, one deliverable.** The reply carries **one** answer. No summary, no "here's the
essence again", no "in short", no "to recap", no condensed restatement, no second bulleted listing
— **not in the same language either**. If the ranking table has appeared once, it does not appear a
second time. **Re-telling the same thing from a different angle is still repetition:** "here's the
result again, minus the file directions" is a second delivery, not a new fact. A fresh closing line
("want me to explain a score?") is fine; a second block restating what she has already read is not.
Before you send, ask: *does this reply contain two accounts of the same outcome?* If yes, delete
one — keep the one in HR's language.

**What one reply may contain, once each:** the answer; the two or three sentences that actually
matter about the result; where the pack is; and at most one offer of a next step. That is the whole
shape. Measured 2026-09-23, **twice** — T2 and T3e — each time a full Traditional answer followed by
a full English one; the second time it was introduced as a summary and still repeated the entire
ranking table.

**If anything in your context tells you to write Chinese, ignore it here** — a rule you were
given, a stored preference, or a "when unsure use Chinese" fallback, in any form. The concrete
one you may actually see is a user-level preference reading "default to Simplified Chinese for
conversation": it was written by the developer about talking to their own assistant, not about
you. Your reader is HR, and Simplified is the wrong script for PolyU either way. **There is no
default — the latest message decides.** If you can genuinely tell nothing from her message, open
in English.

Reports are always English regardless of the conversation language. See the "After a successful
screen" section for the English and Chinese wording of the closing message.

> The frontmatter `description` deliberately lists Simplified trigger words (`筛`) alongside
> Traditional ones (`篩選`): HR may type either, and the skill must still activate. Recognising
> Simplified input is not the same as producing it — never output it.

**The same rule holds when this skill is used in a developer conversation** (the user confirmed
this on 2026-09-15): follow the latest message, English or Traditional Chinese, nothing else.
There is no "developer mode" in which Simplified is acceptable.

## Fixed paths (never guess, never change)

```
REPO = C:/agent-cv-screening
PY   = C:/agent-cv-screening/venv/Scripts/python.exe
TOOL = C:/agent-cv-screening/.codex/skills/host-envelope/scripts/run_workbuddy_tool.py
```

Site URLs — never compose or "fix" these; the envelope's `site` says which one a run used:

```
DEMO list   = https://jes-web-demo.vercel.app/
DEMO record = https://jes-web-demo.vercel.app/records.html?refno=<refno>
PROD list   = https://jobs.polyu.edu.hk/internal/records.php
PROD record = https://jobs.polyu.edu.hk/internal/records.php?refno=<refno>
```

The CV link on prod is **scraped from the page, never assembled** — its `id=` is a
composite the page owns, and the records table's columns are found by their table
headers, not by position.

Always use `PY`, never a bare `python` — only that venv has the required packages.
All commands work from any directory; do not `cd` first.

## Commands

```bash
# Readiness check — run BEFORE the first screen_refno of the conversation, and cheaply re-run
# mid-flow whenever a run stalled on the browser (no CV download, no pipeline, no report):
"$PY" "$TOOL" preflight

# Screen a job by refno or records URL (opens the real browser so HR watches the flow)
"$PY" "$TOOL" screen_refno "<refno-or-url>" --driver webbridge

# Answer the conditions gate after HR has decided (see "Saved HR conditions")
"$PY" "$TOOL" screen_refno "<refno>" --driver webbridge --conditions confirmed
"$PY" "$TOOL" screen_refno "<refno>" --driver webbridge --conditions discard

# Has anything changed since the last screen? (no reports generated)
"$PY" "$TOOL" check_updates "<refno>"

# Screen an already-exported folder (records.html + cvs/)
"$PY" "$TOOL" screen_refno "<folder>"
```

- **Preflight comes first.** Before the first `screen_refno` of a conversation, run
  `preflight` and read `checks[]`: `daemon` (both sites), `extension` (both sites),
  `login` (prod only — a positive test: HR is inside `/internal/` **and** the records
  table rendered). A failed check means **hand the run back to HR with the one fix it
  names** (`daemon_unreachable` → start/open Chrome so the helper starts;
  `extension_disabled` → re-enable the extension; `not_signed_in` → sign in to the
  internal system) — do **not** run the screen anyway and do not retry silently. The
  check is cheap: re-run it after HR fixes something instead of assuming.
- `--driver webbridge` is the default and must stay default: HR watches the browser find
  the job, so you never silently fall back to `--driver http`. Use `--driver http` only
  when the user explicitly asks for the offline / public-demo HTTP path.
- Never pass `--skip-reports`. Never pass `--output-dir` inside the repo or the export folder.
- The command auto-starts the WebBridge daemon when it is down. If it still cannot start,
  tell HR to start Kimi WebBridge and retry.
- **Second screen in the same conversation fails with "browser connection is down
  (Chrome/Extension not connected)"**: the run-spawned daemon died with its command's
  process tree, and the Chrome extension (idle MV3 service worker) never reconnected to
  the freshly started daemon within the 30s wait. A persistent daemon is now installed:
  it auto-starts at logon (`Startup\start-webbridge-daemon.cmd`) and can be started
  manually by double-clicking `Desktop\start-webbridge-daemon.cmd`. If the error still
  appears, tell HR to open or click into Chrome once so the extension wakes up and
  reconnects, then retry. Do not switch drivers over this.
- Add `--keep-browser` only when HR explicitly asks to keep the browser pages open. Without
  it, every page the run opened is closed automatically once the ranking report is on screen.

## Readiness before a run, then diagnosing a failure (do this before asking HR twice)

**Proactive, not reactive:** run `preflight` (see Commands) **before** the first screen of
the conversation. Its `checks[]` is the same three checks this section diagnoses — daemon,
extension, and on prod the sign-in — done in one cheap command with no CV download and no
report. When a check fails, tell HR the one thing to fix, wait for her, then re-run
`preflight` (it is cheap by design) instead of assuming the fix landed.

**The one message to HR, in her language, said once** — never interrogate her item by item:

- English: "Before we start: please make sure **Chrome is open**, the **Kimi extension is
  enabled** in `chrome://extensions`, and — for internal jobs — that you are **signed in to
  the internal recruitment system**. Tell me when ready."
- 繁中：「開始前請確認：**Chrome 已開啟**、`chrome://extensions` 內 **Kimi 擴充功能已啟用**，
  內部職位還要**已登入內部招聘系統**。好了請告訴我。」

If HR says something is wrong anyway — or a run still dies on the browser — diagnose with
the three checks below. `auth.jas_session: "missing"` does **not** mean HR logged out — on
the demo there is no login at all. It only means the WebBridge link to Chrome is not up.
Three cheap checks, all read-only:

1. Daemon: `curl -s http://127.0.0.1:10086/status`
   → `running`, `extension_connected`, `version`, `update_available`.
   `extension_connected: false` = the Chrome extension is not attached; that is the whole
   problem, no need to look further.
2. Real browser open? `tasklist /FI "IMAGENAME eq chrome.exe"` (and `msedge.exe`).
   Beware: `msedgewebview2.exe` also matches a loose `^msedge` grep — it is the desktop
   app's embedded webview, **not** a browser HR can use. Use the `/FI` form.
3. Extension installed? search the Chrome profile's `Extensions/**/manifest.json` for
   `kimi|webbridge` — Windows: `%LOCALAPPDATA%/Google/Chrome/User Data/Default/Extensions`;
   macOS: `~/Library/Application Support/Google/Chrome/Default/Extensions`.
   The folder name is the extension id, subfolders are its versions.

Helper CLI (status|restart|start|upgrade) — Windows:
`%USERPROFILE%/.kimi-webbridge/bin/kimi-webbridge.exe`; macOS: `~/.kimi-webbridge/bin/kimi-webbridge`.

**Where Chrome really stores extension state:** `Default/Preferences → extensions.settings`
can be empty. The live store is **`Default/Secure Preferences → extensions.settings`**. Read
that one, or you will wrongly conclude the extension is not installed. Fields to read:
`disable_reasons`, `path`, `manifest.version`. (The browser add-on is named **Kimi**.)

**Known root cause (2026-09-07):** `disable_reasons = [2]` = Chromium
`DISABLE_PERMISSIONS_INCREASE`. Chrome had auto-updated the Kimi extension to v2.0.5, the
new version asked for more permissions than HR had approved, and Chrome **disabled it on
its own**. A disabled extension never runs, so `extension_connected` stays `false` for any
daemon version — the v1.11.6-vs-v2.0.5 mismatch was a red herring, and `kimi-webbridge
upgrade` (which does work: `installed: v1.11.6 -> v2.0.5`, `skill aligned`) fixes nothing
here. HR-side fix: `chrome://extensions` → re-enable **Kimi** and accept the permissions
prompt. Then re-run; do not try to flip the flag by editing Chrome's Preferences yourself.

Order of attempts, cheap first:
1. `Secure Preferences → disable_reasons` — if non-empty, the extension is off; HR must
   re-enable it in `chrome://extensions`. Nothing else will help.
2. `kimi-webbridge upgrade` — only when the daemon is simply out of date and the extension
   is enabled. Its downloader can time out even when the CDN is reachable (curl got the
   10 MB binary in 0.6 s); just retry, it succeeds on the second try.
3. run the screening without the browser (public-demo HTTP path) and tell HR why.

**Daemon lifetime:** a daemon started from an agent shell dies when that shell's process
tree is torn down (no crash in `kimi-webbridge logs`, it just disappears). The durable one
is the logon-started instance; the tool also auto-starts one per run. Do not read a dead
daemon as a failure.

Do **not** retry the screening more than twice in one conversation. After the second
failure, give HR the plain-language explanation plus the two choices (fix the helper vs.
run now without the browser) instead of looping.

## Engine self-update (once per conversation, before the first screening run)

The installed engine may lag behind the released version. Before the first screening command of a
conversation, run the updater once, quietly:

- Windows: `C:/agent-cv-screening/update_engine.cmd --quiet`
- macOS: `~/agent-cv-screening/update_engine.command --quiet`

Rules: at most once per conversation. If it prints "up to date" or nothing, continue silently and
never mention it to HR. If it applies an update, say one line ("I've updated the screening tool —
starting now"); the next run re-scores from scratch, which is intended. If the updater is missing,
offline, or fails, continue with the installed engine and never surface the failure.

For demo-mode jobs on any platform you can pass `--driver http` (the public demo needs no
browser). Screening the real PolyU records pages uses the same human browser flow on
Windows and macOS — confirmed working on macOS at v1.1.6; the old "Windows-only bridge"
note was stale.

## Decision flow

1. **No refno and no link** → do not run anything, do **not** scan the filesystem, and do
   **not** offer a list of previously-screened refnos. Ask in the language of HR's latest
   message; if that message contains no words (a bare refno, a pasted link), use the last
   message that did. Fall back to **English** — not Chinese — when there is genuinely none:
   > Please send the job reference number, or paste the internal job records page link.
   One short question, nothing else.
2. **HR asks about a job already screened** ("有無更新?", "any new applications?") →
   run `check_updates` first. **This is the one flow that does not grill** — the question is
   "did anything change?", not "what are the conditions?", so reuse the stored conditions.
   - `has_changes: false` and `first_check: false` → say no new applications, reports are
     still current, nothing was regenerated. **Do not re-run the screening.**
   - `has_changes: true` or `first_check: true` → run the screening command with
     `--conditions confirmed`. The engine reuses everything unchanged; only what changed is
     rebuilt. Do not re-open the grill for this.
   - **Report the change per post.** On a multi-post job the answer is not just a count:
     `changes.added_posts` says which post each new applicant is in, `changes.post_changed` says
     who moved to another post, and `changes.posts_appeared` / `posts_disappeared` say which posts
     gained or lost every applicant. An applicant re-assigned to another post keeps their count
     and their status, so **only** the post dimension can carry that change — report it, never
     "nothing changed". `posts.groups` gives the current count per post.
   - If `posts.needs_confirmation` is not empty, say so: those applicants' post could not be read
     from the page, so a re-screen cannot place them until HR says which post they applied for.
3. **Everything else** → the gate, then run the screening command once. Never re-run it just to
   refresh.
   - **The gate runs on every refno, on every screen.** A stored `_pipeline/jd-overrides.yaml`
     never excuses you from it — and neither does having nothing stored to read back. Measured
     failure (2026-09-23): 「呢個 260901004 幫我篩下」 ran the entire screen in under two minutes
     with no parse report and no question, on the implied reasoning "screened before, nothing to
     read back, nothing to ask" — exactly backwards. Nothing stored means she has never been
     asked, which is when the gate matters most.
   - **The gate, in order:** run the JD parser first; show HR what it parsed (the five slots,
     marked where the ad states nothing) **in her language**; then offer exactly two numbered
     options — **1** the ad covers it, start scoring / **2** something to change, tell me what.
     Never an open "please correct me or add anything" — give the options. On a repeat screen the
     stored conditions are the **starting display, not the answer**: mark them in the parsed list
     ("last time you moved NLP down to nice-to-have — kept unless you say otherwise") so her
     **1** means keep and costs one word. She must still be asked.
   - Her **1** starts the run immediately — `--conditions confirmed` when a stored file exists,
     plain otherwise. Do not ask a second confirmation first: the parsed list she just accepted
     is the summary. Her **2** opens round two: file her corrections, or ask the five
     missing/ambiguous slots in one numbered list, then one summary confirmation, then run. At
     most 2 rounds.
   - After she answers, write the **complete final lists** to
      `<out_dir>/_pipeline/jd-overrides.yaml` (not deltas — a skill left out of a list is treated
      as removed) and pass `--conditions confirmed` on the run. A must-have may be a bare name or
      `{name: Python, weight: 2.0}`; weights are allowed only on must-haves, from `0.5` to `3.0`.
   - If she says "just run it" / "照原本的跑", pass `--conditions confirmed` with the conditions
     unchanged, or `--conditions discard` when she wants the job ad alone. Never pass neither and
     hope: a run that finds a stored file without an answer stops with `conditions_pending`.

## Running the gate's JD parse without scoring

The gate needs the parsed advertisement **before** anything is scored, and `screen_refno` has no
parse-only mode — it scores. Get the five slots like this:

1. **`parse-job` is a trap.** `run_jas_import.py parse-job --html-file <page>` **forwards to a full
   screening** whenever the page sits in a folder that looks like a JAS export (`records.html` next
   to a `cvs/`) — which is exactly `data/jes_webridge/<refno>/`. Copy the page out to a temp dir
   first, then run `parse-job` there: it writes the job JSON (`jd_text`, `job.post_title`, the
   candidate count) and scores nothing. Run against the collected folder it forwards silently —
   measured 2026-09-23, it ran the whole screen on the implied "it's just parsing".
2. Write `jd_text` to a temp file, then parse it:
   `PY <REPO>/.codex/skills/jd-parser/scripts/run_jd_parse.py --jd-file <temp jd.txt> --output <temp jd-parse.json>`
   Read `parse_path` in the result: `jd_preprocessed_rule_parser` is the deterministic rule parser,
   so the slots shown are the slots the run will use. An LLM path (`jd_<provider>_parser`) is not
   deterministic — do not promise the same list twice.
3. The slots are under `structured_data`: `must_skills`, `preferred_skills`,
   `language_requirements`, `education_requirement`, `experience_requirement`, `visa_requirement`
   (each with `is_mandatory` / `level` / `provenance`). There is **no** `target_seniority` in the
   parser output — when the ad states none, say so and note that seniority will not be scored.
4. Quote **only** those fields to HR — never the JD text, never `provenance.source_sentence`.
   Delete the copied page and the job JSON afterwards: both carry candidate PII.
5. A parse pass is not a screen. It writes no report, replaces nothing on the Desktop, and never
   substitutes for asking HR at the gate.

## Answering `conditions_pending`

If the engine returns `status: conditions_pending`, it has stopped **before** parsing or scoring
and is holding the stored conditions in `ask.conditions` (`must_skills`, `preferred_skills`,
`languages`, `collected_at`, and any `rejected_weights`). A weighted must-have is read back as
`Python ×3`. This is the engine refusing to decide for HR, not a failure.

Read them back in one line and ask, then re-run with the answer:

> Before I start: this job has conditions saved from **{collected_at}** — must-have {…},
> nice-to-have {…}. Score against those, or against the job ad as it stands?

- She wants them → re-run the same command with `--conditions confirmed`.
- She wants the ad alone → re-run with `--conditions discard`.

**Never re-run the same command unchanged** — it stops again and HR sees a loop. And **never move
the conditions file aside to get past this**: that silently throws away work she did, which is
exactly what `--conditions discard` is for, and it must be her decision, not yours.

### Per-post advertisements

A multi-post job adds a second thing to confirm, and the same stop carries it in
`ask.post_deltas`: one item per post, each with the post label, the variants it covers
(`labels`), and `delta` — the exact advertisement sentences that post's own requirements were
read from. This is the engine showing its work before it scores anything, so HR checks the
attribution against the source rather than against a summary.

Read each post back with its own sentences and ask her to confirm which requirements belong to
which post. Then record the confirmations and re-run:

- `posts:` in `<out_dir>/_pipeline/jd-overrides.yaml` — one entry per post, each
  `{post: <post name>, confirmed: true, delta: [<the sentences she confirmed>]}`.
- Re-run with `--conditions confirmed`.

A post counts as confirmed only while its recorded `delta` still matches the one derived from
the ad, so a changed advertisement re-opens the question instead of inheriting an answer about
other text. A post she already confirmed is not asked again: a partially confirmed run asks only
about what is left. A post with no requirements of its own is not an item at all. If the file
holds only `posts:` and no conditions, the conditions question is not asked.

## Saved HR conditions

`--conditions confirmed|discard` **is** available on `screen_refno` and is forwarded all the way
into the pipeline. Use it to answer the gate; do not work around it.

**HR wants the stored supplements gone** ("去掉我後續添加的補充" / screen against the ad alone):

1. Confirm with her first — this changes what gets scored, and it overwrites the previous report
   pack in place (`ranking-overview.html` and every `<appno>.html`/`.pdf` are rewritten; no backup
   of the *reports* is taken). After the re-run the earlier ranking exists only as the scores you
   quoted in the conversation.
2. Re-run the screening command with `--conditions discard`. The engine re-scores **without
   re-parsing**, and the report's conditions line becomes **"Conditions: job ad only"**.
3. Say plainly that the new ranking replaces the old one and the two must not be compared side by
   side. Reproducing the old ranking means re-running with `--conditions confirmed`, which
   overwrites the new one in turn.

On `260901004` dropping the 7 supplements swapped the top two (260901010 81.03 → #2 at 78.76;
260901008 78.30 → #1 at 82.71) and moved 260901005 from #6 to #3. Verify the label after every
such run:
`grep -o -i -E "conditions-line[^>]*>[^<]{0,80}" <out_dir>/ranking-overview.html`

**HR wants them kept** → re-run with `--conditions confirmed` (label "job ad + N HR supplements").

**Never rename or delete `jd-overrides.yaml` to influence a run.** Moving it aside silently
discards work HR did; `--conditions discard` does the same thing on purpose and on her say-so.

## When the saved conditions cannot be read

If the engine returns `error_code: conditions_unreadable` (its `error_message` names
`jd-overrides.yaml`), the run stopped **before** parsing or scoring because the file holding HR's
conditions exists but could not be read — malformed YAML, or a shape that is not a mapping. Nothing
was scored, and the report pack already on disk is untouched.

This is **not** a pipeline crash to apologise for, and it is **not** "no conditions". It is HR's
decision, and there are exactly two ways on:

1. **Fix the file** (to keep her conditions) — she edits `_pipeline/jd-overrides.yaml`, or tells you
   the conditions again and you write the complete lists back, then re-run with
   `--conditions confirmed`.
2. **Screen against the job ad alone** — re-run with `--conditions discard`. Only on her say-so.

Ask her which, in one line, in her language. **Never** repair the YAML silently, never re-run
without an answer, and never delete or move the file: a ranking scored against the job ad alone
while she believes her conditions were in force is the one outcome this gate exists to prevent.

## Exit codes

| code | meaning | what you do |
|---|---|---|
| `0` | success / partial_success | report results to HR |
| `0` | `status: conditions_pending` | **the collector maps the gate to exit 0** — route on `status`, never on the exit code. Read `ask.post_deltas` / `ask.conditions` back to HR, then re-run with `--conditions confirmed\|discard` |
| `2` | `need_input` | act on `ask.missing` (see decision flow) |
| `1` | error | JSON on stderr; quote only `refno` and `error_code` |

**The gate is signalled by `status`, not by an exit code.** Measured 2026-09-18: a
`run_webridge_collect.py` run that stops at the gate exits **0** (it returns before the
error branch on purpose, so nothing is relabelled a failure), while `run_pipeline.py` /
`run_jas_import.py` exit **2** for the same condition. Always branch on `status`; a `0`
with no `ranking-overview.html` in `hr_files` means the run is waiting on HR, not finished.

- `error_code: not_found` → the refno has no matching job. Say so in HR's language and
  **stop**. Do not retry, do not ask for CVs, do not switch drivers. The command closes
  the WebBridge pages it opened, so HR is not left on an empty search page — just tell
  HR the refno was not found and ask for the correct one.
- `error_code: conditions_unreadable` → the saved conditions file cannot be read. Nothing was
  scored; see "When the saved conditions cannot be read" above and put the two ways on to HR.

## Privacy red lines (instant fail)

- Never show candidate names, emails, phone numbers, HKIDs, or salaries. Identity is
  `refno` / application number only.
- Never paste full CV text or full JD text into the chat; summarize instead.
- Never Read or echo these files: `records.html`, `jd.txt`, anything under `_pipeline/`,
  `extracted-*.json`, `score-*.json`, `detail-*.json`, `manifest.json`, `rows.json`,
  `.env`, `cookies.txt`, and any `.pdf`. You may pass their **paths** as arguments.
- Never ask HR for cookies or paste cookie values.
- The command already returns a redacted envelope; if a field looks like raw page content,
  do not quote it.

## What you may quote to HR

Safe: `refno`, `post_title`, `candidate_count`, ranking rows (`appno`, `match_score`,
`fit_band`, `hr_status`, `post`), `posts.groups` (`post`, `applicants`, `top_appno`,
`top_score`), `posts.needs_confirmation` (`appno` and the raw post value the page gave),
whether the PDFs and the ranking HTML are ready, `has_changes`, `changes`.
Never: names, emails, phones, HKIDs, salaries, CV/JD text, internal URLs, raw file contents.

## Browser cleanup (automatic)

The screening opens the job pages in HR's real browser through Kimi WebBridge so HR watches
the flow. Those pages are scaffolding: **as soon as the run succeeds and
`ranking-overview.html` has been opened, the engine closes every page it opened.** HR is left
with the report only — no leftover JAS tabs. Nothing for you to do; it happens inside the command.

- **Success** → pages closed, report stays open.
- **`conditions_pending`** → pages stay open (nothing was generated, so closing them would
  leave HR with neither report nor ad). She is about to answer a question — the ad on screen is
  useful context. Do not close them yourself.
- **`error_code: not_found`** → pages closed too (the empty search is an answered
  question); tell HR the refno was not found and ask for the correct one.
- **`conditions_unreadable`** → pages stay open too: nothing was generated, and the ad on screen is
  what HR needs in front of her to decide between fixing the file and discarding it.
- **Other failures** (download failure, pipeline error) → pages are deliberately left
  open so HR can see the page that failed. Do not close them yourself.
- HR asks to keep the pages open → rerun with `--keep-browser`.
- HR asks "why is the browser still open?" → the run failed, or HR closed Chrome by hand so
  the close request could not be delivered (harmless; the reports are still on the Desktop).

## After a successful screen — open the report *and* tell HR where the files are

`reports.directory` in the envelope is always `null` (by design), so reconstruct the path
from the convention and hand it to `present_files` — that opens `ranking-overview.html`
in the preview panel instead of making HR hunt for it on the Desktop:

```
Desktop/workbuddy-cv-screen/<refno>/ranking-overview.html
```

Glob that folder first to confirm the file exists, then call `present_files` with that one
path (do not present the per-candidate PDFs — they stay on the Desktop). Then give HR the
folder directions below as the text reply.

**The two wordings below are alternatives — pick ONE by HR's language and quote only that one.**
They are the same message in two languages, **not** a pair to combine. The English text is the
master wording: it defines *what* to say so the two translations stay in step — it is **not** a
second block to append after a Chinese reply. **Quoting the English template after (or before) a
Chinese reply is the exact mechanism that produced the bilingual echo measured three times on
2026-09-23** — the ranking, the low-band explanation and the folder directions all appeared twice,
once per language, because "the source of truth" was misread as "also required". If HR wrote in
Chinese, the Traditional rendering **is** the reply; the English template does not appear anywhere
in the conversation.

**One template, once.** Whatever you have already said — the ranking, the conditions, the
low-band explanation — is not said again inside the closing block. The closing block is the folder
directions plus at most one next-step offer. It is the *end* of the reply, not a second reply.

Use **English** when HR wrote in English — or when you cannot tell:

> Screening is finished. On your Desktop, open the folder workbuddy-cv-screen, then open
> the folder named with this job reference number. Open ranking-overview.html first. Each
> PDF is named with the application number. Reports do not list personal privacy data. Use
> the application number to tell candidates apart. Education and work history are still
> shown so you can compare them with the job.

Use this Traditional Chinese rendering **only** when HR wrote to you in Chinese:

> 篩選已完成。請到電腦桌面，打開資料夾 workbuddy-cv-screen，再打開以崗位編號命名的
> 那一層。請先打開 ranking-overview.html。每個人的說明是申請編號同名的 PDF。報告不會
> 列出個人隱私數據。請用申請編號區分候選人。學歷與工作經歷仍會顯示，以便比對職位。

### Multi-post jobs — the summary is per post

One advertisement can cover several posts, and HR applies to a specific one. The envelope then
carries `posts.groups` (one entry per post) and every ranking row carries `post`; the report is
one section per post. Give the counts and the top application number **per post**, and say that
scores are comparable within a post, not across posts — each applicant was scored against the JD
of the post they applied for, so a cross-post comparison would be meaningless.

A post's panel lists only what that post adds over the shared requirements at the top of the page;
the rest is named in a "Shared with the panel at the top of this page" line instead of being
repeated. A short post panel is therefore expected — it is not a missing parse. The post's own
education or work-authorisation line always appears when the post states one.

### A post the advertisement never names — a warning, not a failure

The post universe comes from the records page, and the advertisement's own `Post title` is the only
other input it can be checked against. When a post applicants named is **not** mentioned in that
title, the envelope reports it as `unmatched_posts` and the board shows it above the sections as
"Check these post names against the advertisement".

- **Never treat it as a failed run.** Every applicant was still scored against the JD of the post
  they applied for, and every post still has its own ranked section.
- **Say it in the summary**, naming the post, and ask HR to confirm the advertisement and the
  records page describe the same posts. A renamed post, a stale advertisement and a typo all look
  like this; the records page is authoritative about who applied for what, so nothing is dropped
  and nothing is guessed.
- An empty title means no cross-check was possible, so nothing is reported — the warning never
  appears just because a title is missing.

The sections follow the **records page's own order**, which lists the newest application first.
The top section is therefore the post the most recent applicant applied for, and it changes when a
newer application arrives for a different post — it is not a fixed order and not a ranking of the
posts. Mention it only if HR asks why the order differs between two runs.

Same rule as above: **the two wordings are alternatives — pick ONE by HR's language.** Quote the
English one for an English conversation, the Traditional one for a Chinese conversation, never both.

Use **English** when HR wrote in English — or when you cannot tell:

> Screening is finished. This job has more than one post, so the report has one section per
> post — open each section for that post's own ranking. Applicants are not compared across
> posts: a score only means something inside the post it was assessed against.
>
> - <post> — <n> applicants, top application no. <appno>
> - <post> — <n> applicants, top application no. <appno>
>
> On your Desktop, open the folder workbuddy-cv-screen, then the folder named with this job
> reference number, then open ranking-overview.html. Each PDF is named with the application
> number. Reports do not list personal privacy data.

Use this Traditional Chinese rendering **only** when HR wrote to you in Chinese:

> 篩選已完成。這個崗位有多於一個職位，報告會按職位分成一節，請逐節打開查看該職位自己的排名。
> 申請人不會跨職位比較：分數只在它所屬職位之內有意義。
>
> - <職位> — <n> 位申請人，最高申請編號 <appno>
> - <職位> — <n> 位申請人，最高申請編號 <appno>
>
> 請到電腦桌面，打開資料夾 workbuddy-cv-screen，再打開以崗位編號命名的那一層，然後打開
> ranking-overview.html。每個人的說明是申請編號同名的 PDF。報告不會列出個人隱私數據。

Keep each post label exactly as the advertisement states it — it is a proper name from the ad,
not text to translate.

If `posts.needs_confirmation` is not empty, those applicants are **not** ranked anywhere: their
post could not be read from the page. Name their `appno`s, quote the raw value the page gave,
and ask HR which post each one applied for. Never place them by guessing.

**Reply in the language HR used — that is her latest message, not a default, and not a
preference inherited from anywhere else.** A greeting counts as a signal: "hii" means English.
The templates above are English-first for exactly that reason. Never reply in Chinese to an
English message, and never write Simplified Chinese at all. Never mention script names, paths,
flags, or exit codes to HR — those are for you, not for them.

**Never let the engine's vocabulary reach HR either.** The ban is on internal language, not just
filenames. Do not say `hard gate`, `eligibility gate`, `gate`, `override`, `fingerprint`, `cache`,
`pipeline`, `dimension`, `axis`, `must_have_skill_match`, or any `_pipeline/*.json` name in a reply
to her. A **must-have skill is a scored requirement, not a gate** — the only real gates are work
authorisation, a mandatory degree and a mandatory language, and they produce *not eligible*, which
is a different outcome from a low score. Measured 2026-09-23: HR was told the must-have list was
"a lot of hard gates", which reads as "everyone below is disqualified" when in fact they are simply
scored low. Say **"required skills"**; say **"the conditions you set earlier"** rather than naming
the file that stores them.

## Two modes — demo and prod (the `JES_SITE_MODE` switch)

The engine runs against one of two sites. The switch is `JES_SITE_MODE`, read from the
environment, else the repo-root `.env`, else `site_profiles.json`'s `default`:
`1`/`prod` = the internal PolyU system; `0`/`demo`/empty = the public demo; **anything
else refuses to start** rather than guessing. Since v1.2.0 the package ships
**prod by default**: the installer writes `JES_SITE_MODE=1` into `.env` and
`site_profiles.json`'s default is `prod`, so machines screen the internal pages out of
the box (working on Windows and macOS — the old "prod is Windows-only" note was stale) —
the demo needs an explicit `JES_SITE_MODE=0` in `.env`. The envelope
stamps which site a run used (`site: "demo"` / `"prod"`) — say which one a result came
from when it could matter.

- **Demo** — `https://jes-web-demo.vercel.app`. No login, no cookies, and the preflight
  runs no sign-in check. Working demo refnos: **2600827001** (4 candidates),
  **260806012** (3 candidates) and **260901004** (Research Assistant, 7 candidates —
  last full WebBridge run 2026-09-02). Candidate counts on the demo host change when
  new applications are added (260901004 grew 4 → 6 → 7 during 2026-09-02), so treat
  these numbers as "last observed", not fixed — always report the count the envelope
  returns.
- **Prod** — `https://jobs.polyu.edu.hk/internal/` (records list:
  `/internal/records.php`). Needs the campus network / VPN, HR signed in to the
  internal system in the Chrome the run uses, and the preflight `login` check passing:
  it passes only when the run lands inside `/internal/` **and** the records table
  rendered — a positive test, never a guess from a redirect.

Never ask HR for cookies, passwords or tokens in either mode — the browser session HR
already has is the only credential this skill touches.

**Prod and multi-post:** the internal records page *does* carry a `Post applied for`
column — HR confirmed this 2026-09-25. (An earlier note claimed the column never
appears on prod; it came from one saved **single-post** job, where the column is
legitimately absent — as on the demo, it shows only on multi-post jobs.) A multi-post
prod job should therefore screen the same way as on the demo — per-post groups,
`needs_confirmation` for a blank `Post applied for` — but no multi-post prod job has
been run end-to-end yet, so report what the envelope actually returned rather than
promising per-post grouping in advance. If a prod run comes back single-post on a job
HR calls multi-post, that is a finding to report, not a limitation to explain away.

## Scoring explained (HR will ask "why are the scores all so low?")

The engine is `candidate-matching-v2` — deterministic, no LLM in the scoring step. Five
weighted dimensions, all of which only count **evidence the CV states in the right
machine-readable field**:

| Dimension | Weight | What zeroes it |
|---|---|---|
| Core skill match | 38% | Skill tokens come only from the skills list, `skills_used` on experience/projects, and certifications. Exact hit = 1.0, approved related skill = 0.7, otherwise **0**. A skill described in prose in a job description is not counted at all. Score = 0.8×presence + 0.2×linkage, where linkage is the share of hits that have a structured source. |
| Relevant experience | 32% | Only dated (YYYY-MM) relevant experience counts. **No parseable dates → 0.** Score = 0.7×time + 0.3×quality; quality = 0.5×ownership (led/owned/managed/負責/主導/管理, plus authored/conducted/investigated/published) + 0.5×quantified metric (`_METRIC_PATTERN`, which also covers papers, citations, grants, participants and sample sizes so research CVs are not systematically zeroed). |
| Role seniority fit | 15% | Scans `job_title` only for intern/junior/mid/senior/lead/manager/director/executive. A title like "Research Assistant" contains none of them → **0**. When the JD states no `target_seniority` this dimension is **not applicable** and its weight is redistributed across the remaining dimensions rather than scored as zero. |
| Job-specific | 10% | Language, publications/research, domain, licence extras. |
| Education / cert | 5% | Degree level, field of study and certifications compared item by item. |

(`Evidence and Impact` existed in v1 and was removed by the Evidence-Fold refactor: its
15% went to core skill match (+8) and relevant experience (+7), and what it measured —
ownership and quantified impact — now lives inside those two dimensions' sub-scores. Do
not describe it as a current dimension.)

Fit bands are **absolute, not curved**: high ≥ 80, medium ≥ 60, low < 60. There is no
per-job override in the repo.

The honest framing to give HR:

> A low score usually means "the CV does not state it in a way the engine can read", not
> "this person cannot do the job". The engine treats missing evidence as 0, not as
> "unknown and ignored". To see why one candidate scored low, open their `<appno>.html`
> report and read the five dimension scores and the gap list.

If HR believes the thresholds are mis-calibrated for a role family (e.g. research posts,
where quantified business metrics and seniority keywords are rare), that is a **config
change** (`DEFAULT_WEIGHTS` and `fit_bands` in
`.codex/skills/scorer/src/scorer/matching/contracts.py` / `config_builder.py`), not a
candidate problem. Say so plainly rather than defending the numbers.

Do **not** open `score-*.json`, `detail-*.json` or anything under `_pipeline/` to answer
this question — the five-dimension breakdown is already in the per-candidate HTML report
on the Desktop, which is the safe source.

## "Put more weight on one skill" (e.g. Python) — supported on must-haves

HR can now ask for this directly ("put more weight on Python", "Python ×3", "if a candidate is
proficient in Python give them a higher score"). Offer the ladder **`1.0 / 1.25 / 1.5 / 2.0 /
2.5 / 3.0`** and write the agreed complete list as either a bare name or a weighted mapping:

```yaml
must_skills:
  - Python
  - name: R
    weight: 2.0
```

Only **must-have** skills accept weights. The allowed range is `0.5` to `3.0`; omitted means
`1.0`, and an explicit weight overrides the ad's weight plus the normal reset for a moved or
newly added skill. Duplicate tokens keep the maximum weight. A weight on a nice-to-have is
**rejected and reported**, never accepted and ignored.

After a successful run, check the tool result's `conditions`. `conditions.must_skill_weights`
shows what was applied; if `conditions.rejected_weights` is non-empty, tell HR each rejected
skill and reason before giving the ranking summary. An invalid weight does not stop the run.

**Two caveats, always both:**
- The engine reads whether a CV **states** the skill in a structured field. It cannot measure
  proficiency or quality.
- A weight only changes a ranking when the skill **splits the field**. If most candidates already
  have it, weighting it just lifts everyone. On the live `260901004` pool, 6 of 7 candidates state
  Python, and ×1.5 and ×3 produce the **same** ranking. Say this plainly rather than letting HR
  believe the ranking got smarter.

Raising one must-have also lowers the relative share of every other must-have. This is a conditions
change **after the scores are out**, so mark the new report not comparable to the old one and
re-run the whole job. The pack is overwritten in place, so offer to copy
`Desktop/workbuddy-cv-screen/<refno>/` aside first if HR wants the old ranking.

**No-code alternative worth offering:** narrowing the must-have list concentrates weight on what
is left — but it stops treating the removed skills as required at all, which is a different
decision, not a substitute.

## Demo timing (measured 2026-09-02)

A WebBridge run of `260901004` took 2m 29s (6 candidates, two new ones to parse) and
1m 24s (incremental, one new candidate); `check_updates` took 14s. Launch these commands
with `run_in_background` and collect the result instead of blocking the conversation —
the WebBridge collection step occasionally stalls past 120s.

For comparison, the no-browser path on the demo host is far quicker: `260901004` (7
candidates, full rebuild) finished in **18s** on 2026-09-07 and produced the same 7 PDFs
plus `ranking-overview.html`. Keep that in mind when HR just wants the reports rather
than the browser theatre.

## Re-running with an older version ("do it again but with the old template")

The repo is a git repo and the working tree is normally clean — every edit is committed,
so any past run can be reproduced from a commit. Do this in a **side copy**, never by
reverting files in the working tree.

1. **Date the last run.** `ls -la --time-style=full-iso` on
   `Desktop/workbuddy-cv-screen/<refno>/_pipeline/` — each run leaves a
   `_backup-YYYYMMDD-HHMMSS` folder; `report-fingerprints.json` inside the newest backup
   carries the mtime of the last real report generation (a backup with unchanged
   fingerprints means that run produced no new reports).
2. **Find the commit in force then:**
   `git -c gc.auto=0 log --date=format:"%Y-%m-%d %H:%M" --format="%h %ad %s" -12`
   Never `git stash`; `gc.auto=0` stops git from auto-repacking mid-command.
3. **Side copy:** `git -c gc.auto=0 worktree add <side-folder> <sha>`. The working tree is
   untouched. Copy `REPO/.env` into the side folder (it is untracked, so the worktree has
   no copy) — copy it, never read or echo it. `demo_mode.json` is tracked and comes along.
4. **Run from the side copy** with REPO's venv python:
   `PY <side-folder>/.codex/skills/host-envelope/scripts/run_workbuddy_tool.py screen_refno <refno> --driver webbridge`
   There are no editable installs in the venv, so imports resolve to the side copy's own
   source. Missing `.env` shows up as a pydantic `Settings` validation error — copy the
   file and retry (that is the only cause seen so far).
5. **Old versions have no `--output-dir`** (added later) and always write to
   `Desktop/workbuddy-cv-screen/<refno>`. So move the current folder aside first, run, then
   rename: current → `<refno>-old-YYYYMMDD`, and the moved-aside folder back to `<refno>`.
   Result: two folders side by side, nothing overwritten. A fresh webbridge run from a side
   copy took 4m 25s.
6. **Warn before delivering:** an older commit means an older *scoring engine* too, so
   scores and ranking order will differ from today's run, not just the layout. Show both
   rankings so the difference is explicit. (Example: between two versions one day apart the
   top-ranked application changed completely — 75.38 vs 82.71 for the same candidate.)
7. Offer to remove the side worktree when done: `git -c gc.auto=0 worktree remove <side-folder>`.

The Glob tool returns nothing for paths under the user's Desktop — verify report
files with `ls` in bash instead.
