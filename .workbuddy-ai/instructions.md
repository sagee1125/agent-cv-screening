# WorkBuddy must run this repo's JAS CLI, not a homemade screener.

When HR says 用 jas-import 离线筛选 plus a folder or URL:

```
cd C:\Users\User\Desktop\IHERD\agent-cv-screening
python .codex/skills/jas-import/scripts/run_jas_screening.py "<folder-or-url>"
```

Never write `jas_screening.py`, `extract_cvs.py`, or `screening_report.html`.
Never keyword-match CVs. Never include names, emails, phones, or salaries.
Never save reports under `WorkBuddy AI\<timestamp>\`.
Never pass `--skip-reports`.
Never pass `--output-dir data/jas_out` or any path inside this git repo.
Do not run `host-envelope` as the HR deliverable.
The CLI writes `Desktop/workbuddy-cv-screen/<refno>/` and opens `ranking-overview.html`.
