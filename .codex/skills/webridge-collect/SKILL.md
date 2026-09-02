---
name: webridge-collect
description: "Collect one JAS job (records.html + all candidate CVs) using Kimi WebBridge like a human, or directly over HTTP for the public demo, then run the existing jas-import screening pipeline to Desktop reports. Use when: HR gives a job refno or records URL that needs a real browser session (WebBridge), or for the public demo at jes-web-demo.vercel.app."
---

# WebBridge Collect Skill

**This is the default entry point for "screen refno \<digits\>" / "筛 \<digits\>" (see AGENTS.md).**
It drives the user's real browser so HR watches the full human flow; `jas-import` is only
used directly when HR supplies an already-exported folder.

Simulate a human in a real browser (Kimi WebBridge) to open the job records page,
save the full HTML, download every candidate CV named by application number, and
then hand the folder to the existing `jas-import` pipeline for scoring and reports.
No candidate identity ever enters the chat: only the refno / records URL is accepted,
and page/CV content stays on disk.

## Prerequisites

- Kimi WebBridge extension installed in Chrome/Edge and the daemon running:
  `& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" start`
- For the public demo (no login), `--driver http` needs no browser at all.
- Python deps: `venv/Scripts/python.exe -m pip install -r backend/requirements.txt`.

## Run

```bash
# Real browser path (WebBridge), internal records URL
venv/Scripts/python.exe .codex/skills/webridge-collect/scripts/run_webridge_collect.py "https://jobs.polyu.edu.hk/internal/records.php?refno=260818001" --driver webbridge

# Public demo host, direct HTTP (no browser needed)
venv/Scripts/python.exe .codex/skills/webridge-collect/scripts/run_webridge_collect.py 2600827001 \
  --driver http --base-url https://jes-web-demo.vercel.app \
  --allow-host jes-web-demo.vercel.app
```

| flag | meaning |
|---|---|
| `target` / `--refno` / `--records-url` | Job reference number or records page URL (one required) |
| `--driver webbridge\|http` | `webbridge` (default) drives the user's browser; `http` fetches public demo pages directly |
| `--session <name>` | WebBridge tab-group session name |
| `--base-url <URL>` | Base URL for CV links and refno URL building (public demo) |
| `--allow-host <HOST>` | Extra allowlisted URL host (repeatable) |
| `--cookie-file <jar>` | Local Netscape cookies.txt for authenticated HTTP fetches |
| `--collect-dir <dir>` | Where records.html + cvs/ are written (default repo data/jes_webridge) |
| `--report-dir <dir>` | Pipeline output parent (default Desktop/workbuddy-cv-screen) |
| `--no-pipeline` | Collect only; do not run screening |
| `--engine legacy\|matching` | Scoring engine (default matching) |
| `--no-open` | Do not open ranking-overview.html |
| `--skip-reports` | Skip HTML/PDF/Excel (testing only) |
| `--cleanup` | Delete collected folder after a successful run |
| `--keep-browser` | Keep the WebBridge tabs open (default: close them once the report is on screen) |

## Behavior

- Writes `<collect-dir>/<refno>/records.html` + `cvs/<appno>.pdf` + `_webridge-manifest.json`.
- WebBridge driver simulates a human: it opens the job list page, types the refno into the Ref no. filter,
  locates the job row, and opens its View link (falls back to the records URL directly when the row is not found).
- The human flow auto-focuses the new browser tab (CDP `Page.bringToFront`) and drives a visible ghost
  cursor that glides to the filter, types the refno, and presses the View link, so HR watches the interaction.
- Then runs `run_jas_import.py <folder>` -> `Desktop/workbuddy-cv-screen/<refno>/`.
- Exit codes: `0` success/partial_success, `1` error, `2` need_input (`refno` or `jas_session`).
- WebBridge daemon down -> the script auto-starts it (and waits for it to come up);
  only if it still cannot start -> `need_input` asking to start it. It never silently
  degrades to `--driver http` for a refno/URL.
- **Browser cleanup**: once the pipeline succeeds and `ranking-overview.html` is open,
  the WebBridge session is closed (`close_session`), so every page the run opened disappears
  and HR is left with the report. A **not-found** result also closes the tabs (the empty
  search is an answered question, not something HR needs to keep looking at). Other
  failures (download failure, pipeline error) keep the pages open so HR can see what went
  wrong. Add `--keep-browser` to leave them open in any case. The close is best-effort: a
  browser that is already gone never fails the run.
- CV filenames are derived from application numbers only; person-named files are never used.
- TLS: the HTTP driver respects `JAS_SSL_VERIFY` (`system` / `0` / `false` / CA bundle
  path) like the jas-import fetcher; WebBridge mode uses the browser's own trust store.

## PII boundary

- Only the refno / records URL is accepted as input (no inline text, no pasted HTML).
- Page HTML and CV bytes are written to disk by the script; they are never echoed to the chat.
- The stdout envelope contains only `refno`, `post_title`, counts, and paths.
- WebBridge `evaluate` runs inside the user's browser with its real login session; the
  downloaded bytes stay on this machine.
