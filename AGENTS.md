# AGENTS.md

Project rules for all agents working in this repository.

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
   python .codex/skills/webridge-collect/scripts/run_webridge_collect.py "<refno-or-url>" --driver webbridge
   ```

   - The WebBridge human flow is the default everywhere; `run_webridge_collect.py --driver webbridge`
     auto-starts the Kimi WebBridge daemon when it is down (probes `http://127.0.0.1:10086/status`).
   - Only if the daemon still cannot be started (or HR explicitly asks for the offline/HTTP path),
     fall back to the headless HTTP driver:
     `python .codex/skills/webridge-collect/scripts/run_webridge_collect.py "<refno>" --driver http`
   - Only if HR explicitly asks for the offline/HTTP path, or hands over an **already exported
     folder** (`records.html` + `cvs/`), run jas-import directly:
     `python .codex/skills/jas-import/scripts/run_jas_import.py "<folder>"`
   - `demo_mode.json` at the repo root supplies `--base-url` / `--allow-host` /
     `--no-cookie` automatically, so do not pass them by hand.
   - Repeat runs reuse unchanged PDFs; a changed JD or CV is rebuilt.
   - The update checker `check_updates.py` uses the same WebBridge default; it only opens the
     records page (no CV download, no report). Add `--driver http` for the offline/cookie path.
3. If there is no refno, link, or folder, do not invent a screener. The CLI returns `need_input` (`refno`). Ask HR in the language they used (or both) for the job reference number or the records page link.
4. Do not write or edit `screening.html` / `screening_report.html`. Do not add JS parsers or localhost demos. Do not pass `--skip-reports`.
5. Reports go to `Desktop/workbuddy-cv-screen/<refno>/` (not the WorkBuddy session folder). Files: `ranking-overview.html`, `<appno>.html`, `<appno>.pdf`.
6. Never put candidate names, emails, phones, or salaries in HTML/PDF. Identity is `refno/appno` only.
7. Tell HR where the Desktop folder is, in the same language they used. Do not load those files into the chat model.
   Do not ask HR to name Python scripts.

