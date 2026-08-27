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

When the user says `用 jas-import 离线筛选` plus a folder or URL:

1. `cd` to this repository root.
2. Run `python .codex/skills/jas-import/scripts/run_jas_screening.py "<folder-or-url>"`.
3. Do not invent a keyword screener. Do not write `screening_report.html`. Do not pass `--skip-reports`.
4. Reports go to `Desktop/workbuddy-cv-screen/<refno>/` (not the WorkBuddy session folder). Files: `ranking-overview.html`, `<appno>.html`, `<appno>.pdf`.
5. Never put candidate names, emails, phones, or salaries in HTML/PDF. Identity is `refno/appno` only.

