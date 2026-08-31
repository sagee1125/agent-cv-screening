# WorkBuddy host instructions for HR screening.

WorkBuddy is the conversation host. This repository is the screening engine.
Reply in the language HR used. Do not invent tools.

HR saying 「用 jas-import 離綫篩選」plus a folder means: run the Python CLI below,
wait, then tell them the Desktop path. That is the entire task.

## Forbidden (instant fail)

Do not edit, create, or serve `screening.html`.
Do not add JAS Import / Paste HTML buttons.
Do not write `parseJASHTML`, DOMParser, or any JavaScript HTML parser.
Do not extract name, email, phone, HKID, or salary into a webpage.
Do not start `localhost` preview servers.
Do not write `screening_report.html` or keyword-match CVs.
If the export folder contains a leftover `screening.html`, delete it; it is not a product file.

## Required command

From `C:\Users\User\Desktop\IHERD\agent-cv-screening`, run and wait:

```
python .codex/skills/jas-import/scripts/run_jas_import.py "<folder-or-url-or-refno>"
```

Live URL or refno: add `--cookie-file` after JAS access is granted.
Never `--skip-reports`. Never `--output-dir` inside this repo or the export folder.

Success = files exist at `Desktop/workbuddy-cv-screen/<refno>/ranking-overview.html`.
If you did not run that Python command, you have not screened.

If HR gave no folder, URL, or refno, ask (do not start):

> 請發送崗位參考編號，或貼上內部招聘記錄頁的連結。
> Please send the job reference number, or paste the internal job records page link.

If the CLI returns `need_input` / `jas_session`, request OS access to the internal
page. Never ask HR to paste cookies.

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
