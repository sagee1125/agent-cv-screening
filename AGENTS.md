# AGENTS.md

Project rules for all agents working in this repository.

## HR screening entry point

### Screening conversation contract (must follow exactly)

This is the exact behaviour HR expects when they say "screen the CVs" / 「請幫我篩選一下簡歷」
/ 「篩選簡歷」/ "screen the resumes":

1. **No refno → ask immediately, in HR's language.** When the request does not include a
   refno, a records-page URL, or an already-exported folder, do **not** scan the filesystem,
   do **not** offer a list of previously-screened refnos, and do **not** invent one. Ask
   HR straight away for the job reference number (or the records page link). Reply in the
   language HR used — English if they wrote in English, 繁體中文 if they wrote in 繁體中文
   (ask in both if you cannot tell). One short question, nothing else.

2. **Refno given → run the WebBridge human flow.** Use `--driver webbridge` (the default).
   The collector opens the demo site in HR's real browser, types the refno into the list
   page Ref-no filter, clicks the row's View link, downloads the CVs, and runs the
   pipeline — HR watches the whole human flow.

3. **Not found → close the browser tabs and report.** If the refno has no matching row,
   the collector closes the WebBridge pages it opened and returns `not_found`. Tell HR in
   their language that the refno was not found and ask for the correct one. Do **not**
   leave the empty-search page on screen.

4. **Found → open the ranking report, close the browser tabs, give a text summary.** On
   success the collector opens `ranking-overview.html` and closes the WebBridge tabs, so HR
   is left with the report. Then give HR a short text summary (counts, top candidate
   `appno`s, where the Desktop folder is) in their language. Do **not** load the report
   HTML/PDF into the chat model — point HR to the Desktop folder instead.

### Skill contract source

The same screening contract is installed as a user-level WorkBuddy skill named
**`hr-cv-screening`** (`~/.workbuddy-ai/skills/hr-cv-screening/SKILL.md`), so HR can trigger
it from any folder, not only inside this repo. That skill is the canonical source for the
command list, the tool map, the privacy red lines, and the reply templates. This file stays
authoritative for anything repo-specific (paths, code rules) — see the
"WorkBuddy / HR screening" section below.

### Interpreter and venv

Always invoke the CLIs with `venv/Scripts/python.exe`, never a bare `python`: only that venv
has `httpx`, `openpyxl`, `reportlab`, `pymupdf`, and the OCR stack. As a safety net,
`screening_core.bootstrap.ensure_venv_interpreter` re-execs the CLI with the venv
interpreter when those packages are missing from the interpreter that was called.

## Code Comment Rule

Every code file and every function must include a short English comment explaining its purpose.

1. **File header comment** Each source file (backend `.py`, frontend `.ts` / `.tsx` components, scripts, configs, etc.) must start with a brief one-line English comment describing the purpose of the file.

2. **Function comment** Every function, method, and React component function must have a short English comment (1-2 lines) directly above its definition explaining what it does.

3. **Language & length** Comments must be written in English and kept concise: state the _purpose_, not the implementation details.

### Examples

Python (backend):

```python
# Parse an uploaded CV file into structured candidate data.
async def upload_candidate_cv(...):
```

TypeScript / React component (frontend):

```tsx
// Renders a job posting card with status toggle and detail actions.
export function JobCard({ job, ... }) {
```

### Scope

- Applies to all code files: backend modules, API routes, services, models, frontend components, hooks, utilities, and scripts.
- Short, auto-explanatory helpers may use a single inline comment instead of a multi-line block, but must still carry a comment.

## WorkBuddy / HR screening

When HR asks to screen a job in Chinese or English (a JAS records URL, a numeric
refno, or an exported folder), including 「用 jas-import 離綫篩選」plus a path:

1. `cd` to this repository root.
2. **For a refno or a records URL, run the WebBridge human-flow collector (default).**
   It opens the demo site `https://jes-web-demo.vercel.app/` in the user's real browser,
   types the refno into the list-page filter, clicks the row's View link, downloads the
   CVs, and then runs the screening pipeline — so HR watches the whole human flow.

   ```bash
   venv/Scripts/python.exe .codex/skills/webridge-collect/scripts/run_webridge_collect.py "<refno-or-url>" --driver webbridge
   ```

   - The WebBridge human flow is the default everywhere; `run_webridge_collect.py --driver webbridge`
     auto-starts the Kimi WebBridge daemon when it is down (probes `http://127.0.0.1:10086/status`).
   - Only if the daemon still cannot be started (or HR explicitly asks for the offline/HTTP path),
     fall back to the headless HTTP driver:
     `venv/Scripts/python.exe .codex/skills/webridge-collect/scripts/run_webridge_collect.py "<refno>" --driver http`
   - Only if HR explicitly asks for the offline/HTTP path, or hands over an **already exported
     folder** (`records.html` + `cvs/`), run jas-import directly:
     `venv/Scripts/python.exe .codex/skills/jas-import/scripts/run_jas_import.py "<folder>"`
   - `demo_mode.json` at the repo root supplies `--base-url` / `--allow-host` /
     `--no-cookie` automatically, so do not pass them by hand.
   - Repeat runs reuse unchanged PDFs; a changed JD or CV is rebuilt.
   - **Browser cleanup is automatic**: when a run succeeds and `ranking-overview.html` has
     been opened, the collector calls WebBridge `close_session`, so every page it opened is
     closed and HR is left with the report. A **not-found** result also closes the tabs
     (the empty search is an answered question — tell HR the refno was not found and ask for
     the correct one; do not leave them on the blank results page). Other failures (download
     failure, pipeline error) keep the pages open on purpose so HR can see what went wrong.
     Pass `--keep-browser` to opt out of closing in any case. The same applies to
     `check_updates.py`, which closes the tab it opened once the check is answered. The
     close is best-effort and never fails a screening.
   - The update checker `check_updates.py` uses the same WebBridge default; it only opens the
     records page (no CV download, no report). Add `--driver http` for the offline/cookie path.
3. If there is no refno, link, or folder, do not invent a screener. The CLI returns `need_input` (`refno`). Ask HR in the language they used (or both) for the job reference number or the records page link.
4. Do not write or edit `screening.html` / `screening_report.html`. Do not add JS parsers or localhost demos. Do not pass `--skip-reports`.
5. Reports go to `Desktop/workbuddy-cv-screen/<refno>/` (not the WorkBuddy session folder). Files: `ranking-overview.html`, `<appno>.html`, `<appno>.pdf`.
6. Never put candidate names, emails, phones, or salaries in HTML/PDF. Identity is `refno/appno` only.
7. Tell HR where the Desktop folder is, in the same language they used. Do not load those files into the chat model.
   Do not ask HR to name Python scripts.

