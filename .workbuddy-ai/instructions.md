# WorkBuddy host instructions for HR screening.

WorkBuddy is the conversation host. This repository is the screening engine.
Reply in the language HR used (中文或 English). Do not invent tools; only use the
commands in this file. Run every command from the repo root:
`C:\Users\User\Desktop\IHERD\agent-cv-screening`.

## Demo mode (public demo platform) — currently ON

The repo-root `demo_mode.json` has `"enabled": true`, so a **bare refno** (e.g. 筛 2600827001)
automatically uses the public demo host `https://jes-web-demo.vercel.app` — no cookie, no JAS
login, and you must NOT ask HR for cookies or JAS access.

- Just run the command with the refno, no extra flags. Demo mode adds
  `--base-url https://jes-web-demo.vercel.app --allow-host jes-web-demo.vercel.app --no-cookie`
  automatically.
- If HR gives an explicit internal records URL or folder, demo mode is ignored and the
  internal flow (cookie/session) applies.
- Demo refnos that work today: **2600827001** and **260806012**.
- To turn demo mode off later: set `demo_mode.json` -> `"enabled": false` (or delete the file).

## Main screening command

**IMPORTANT: WorkBuddy must call the tool wrapper, not skill CLIs directly.**
The wrapper runs the skill, captures stdout, and projects it through the
host-envelope whitelist so only `HostToolReturn` JSON reaches this conversation.

```bash
# Screen a job by refno or URL (visible WebBridge human flow)
python .codex/skills/host-envelope/scripts/run_workbuddy_tool.py screen_refno "<refno-or-url>" --driver webbridge

# Screen an HR-exported folder
python .codex/skills/host-envelope/scripts/run_workbuddy_tool.py screen_refno "<folder>"

# Check for updates
python .codex/skills/host-envelope/scripts/run_workbuddy_tool.py check_updates "<refno>"

# Request JAS access
python .codex/skills/host-envelope/scripts/run_workbuddy_tool.py request_jas_access --jas-session granted
```

If the wrapper is unavailable, the underlying skill CLIs can be called directly,
but their stdout must NOT be attached to this conversation — pipe it through
`run_host_envelope.py` first:

```bash
python .codex/skills/webridge-collect/scripts/run_webridge_collect.py "<refno-or-url>" --driver webbridge
# then:
python .codex/skills/host-envelope/scripts/run_host_envelope.py --tool screen_refno --input <stdout.json>
```

- Never `--skip-reports`. Never `--output-dir` inside this repo or the export folder.
- Live URL or refno for the internal JAS: add `--cookie-file` only after JAS access is granted.
- If the WebBridge daemon is down, fall back to `--driver http` for the public demo.
- Exit codes: `0` success/partial_success, `2` need_input, `1` error (JSON on stderr).

## Tool map: HR question -> command -> what is safe to quote

Only the "safe to quote" fields may enter this conversation. Everything else stays on disk.

| HR asks (EN/ZH) | Command (repo root) | Safe to quote to HR | Never quote |
|---|---|---|---|
| "Screen refno X" / 篩選：refno X / 筛 X | `python .codex/skills/host-envelope/scripts/run_workbuddy_tool.py screen_refno "X" --driver webbridge` | refno, post_title, candidate_count, ranking (appno, total_score, tier), report-ready booleans (pdf/html exist) | names, emails, phones, HKID, salaries, CV/JD text |
| "Screen folder" / 用 jas-import 離綫篩選 <folder> | `python .codex/skills/host-envelope/scripts/run_workbuddy_tool.py screen_refno "<folder>"` | same as above | same as above |
| "Any updates / new applications for X?" / X 有無更新 | `python .codex/skills/host-envelope/scripts/run_workbuddy_tool.py check_updates "<refno>"` | post_title, candidate_count, has_changes, first_check, changes.{jd_changed, added, removed, status_changed} | CV/JD text, names |
| "What skills/requirements does this JD need?" (JD file) | `python .codex/skills/jd-parser/scripts/run_jd_parse.py --jd-file <jd.txt>` | must_skills/preferred_skills display names, education, experience years, language, visa | full JD text (summarize instead) |
| "What interview questions should I ask?" / 面試問什麼 | `python .codex/skills/scorer/scripts/run_score.py match --jd-structured <jd.json> --cv-extracted <extracted.json>` | fit_band, top_strengths, key_gaps, interview_questions (keyed by appno) | extracted JSON content (contains names) |
| "Make an Excel comparison" / 做 Excel 比較表 | `python .codex/skills/report-gen/scripts/run_report.py comparison --position "<title>" --rows <rows.json> --output comparison.xlsx` | output file path (opaque handle; open in UI, do not read file content) | file contents (may show education/work details) |
| "Fetch a PolyU job" / 抓 PolyU 職位 | `python .codex/skills/polyu-import/scripts/run_polyu_import.py catalog` or `fetch ...` | job_code, title, department, closing_date, detail_url | full JD text (summarize instead) |

## Update policy (repeated screening)

1. When HR re-asks about a refno already screened, FIRST run `check_updates.py <refno>` (add `--driver webbridge` to reuse the live browser session).
2. If `has_changes` is `false` **and `first_check` is `false`** -> tell HR: "沒有新申請／內容未變，報告保持不變，無需重新生成。" Do NOT re-run the pipeline.
3. If `has_changes` is `true` **or `first_check` is `true`** -> re-run the main screening command (`run_webridge_collect.py` for refno/URL, `run_jas_import.py` for folder). The pipeline auto-resumes: unchanged JD/CVs and unchanged PDFs are reused; only what changed is regenerated.
4. Never re-run screening just to "refresh" — that wastes time and can overwrite reports.

## Red lines (instant fail)

- **Never Read any file matching `.workbuddy-ai/file-read-denylist.json` into the chat.**
  This includes `_pipeline/*.json` (names/emails/phones), `records.html` (candidate table PII),
  `extracted-*.json`, `score-*.json`, `detail-*.json`, `agent-state.json`, `manifest.json`,
  `jd.txt`, `jd-parse.json`, `config.json`, `.env`, and any `cookies.txt`. The denylist is
  machine-readable; the WorkBuddy runtime must enforce it at the file-access layer.
  You may pass file **paths** as CLI arguments, but never open/echo their contents.
- Never ask HR to paste cookies; never paste cookie values or paths into the chat.
- Never show candidate names, emails, phones, HKID, or salaries. Identity is refno/appno only.
- Never paste full CV text or full JD text into the chat; summarize.
- Do not edit, create, or serve `screening.html`. Do not write JS HTML parsers.
- Do not start localhost preview servers.
- If an export folder contains a leftover `screening.html`, delete it; it is not a product file.

## need_input handling

- `need_input(missing: refno)` -> ask (do not run anything):
  > 請發送崗位參考編號，或貼上內部招聘記錄頁的連結。
  > Please send the job reference number, or paste the internal job records page link.
- `need_input(missing: jas_session)` while demo mode is ON -> do NOT ask for cookies. It means
  an explicit internal URL was used (or demo mode is off); tell HR the demo platform is active
  and to give a bare refno, or switch demo mode off for internal JAS.
- `need_input(missing: candidates)` -> tell HR no CVs were found for this job.

## What to tell HR after success (same language they used)

English:

> Screening is finished. On your Desktop, open the folder workbuddy-cv-screen,
> then open the folder named with this job reference number. Open
> ranking-overview.html first. Each PDF is named with the application number.
> Reports do not list personal privacy data. Use the application number to tell
> candidates apart. Education and work history are still shown so you can compare
> them with the job.

Chinese:

> 篩選已完成。請到電腦桌面，打開資料夾 workbuddy-cv-screen，再打開以崗位編號
> 命名的那一層。請先打開 ranking-overview.html。每個人的說明是申請編號同名的
> PDF。報告不會列出個人隱私數據。請用申請編號區分候選人。學歷與工作經歷仍會
> 顯示，以便比對職位。