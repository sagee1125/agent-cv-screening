# hr-cv-screener

A WorkBuddy expert package that turns the `agent-cv-screening` engine into something an HR
colleague can summon by clicking a card.

## Layout

```
hr-cv-screener/
├── .codebuddy-plugin/plugin.json         Identity + market card copy (bilingual)
├── agents/hr-cv-screener.md              The agent: tone, privacy red lines, the JD grill stage
├── skills/hr-cv-screening/SKILL.md       Commands, paths, exit codes — the machine half
├── avatars/expert.png                    512x512 head-and-shoulders mark on #951D1D
├── README.md                             this file
└── TESTING.md                            Behavioural test script — run it after every agent change
```

Display name: **Vera** (en and zh), profession "Resume Screening Specialist / 履歷篩選專員".

`TESTING.md` is the manual test table. `validate_expert.py` checks structure only; it cannot tell
whether Vera answers well, so the wording checks in `TESTING.md` are the only real safety net.

The agent handles the person, the skill handles the machine. Everything HR-facing — language,
tone, what to say when something breaks — belongs in `agents/`. Everything operational — commands,
paths, exit codes — lives in the user-level `hr-cv-screening` skill, which this agent preloads by
name (`skills: [hr-cv-screening]` in the agent frontmatter).

Language split: the **conversation mirrors HR's language**, every **report is always English**.

**The skill is bundled as of v0.2.0.** `skills/hr-cv-screening/SKILL.md` is a copy of the
user-level skill, rewritten for the target machine: its three fixed paths point at
`C:/agent-cv-screening`, and the Chrome profile and WebBridge helper paths are expressed as
`%LOCALAPPDATA%` / `%USERPROFILE%` so they resolve under any Windows account.

On this development machine the user-level copy at `~/.workbuddy-ai/skills/hr-cv-screening/`
is still the live one, and it still points at `Desktop/IHERD/agent-cv-screening`. Keep the two
in sync when the skill changes — they are separate files and neither updates the other.

The bundled copy only matters on a machine with no user-level copy, which is exactly the
distribution case: there the package is self-contained and the engine must sit at
`C:/agent-cv-screening`.

## Distribution

Built by `package_expert.py` into `hr-cv-screener.zip` (6 files, ~46 KB). It is installed by
`install-expert.bat`, which ships inside the engine folder beside the zip; that script unpacks
this package into the WorkBuddy settings folder and merges the entry into `marketplace.json`.

Still open:

- **No MCP dependency declared.** The agreed direction is a **local stdio MCP server** on HR's
  machine; until that exists, the bundled skill drives the engine through its CLIs.
- **No update path.** Plan: a `latest.json` manifest plus a startup check, so HR never re-pulls
  anything by hand. Today an update means re-running `install-expert.bat`.
- **Not submitted anywhere.** Distribution is a manual folder drop / scripted install. The
  enterprise upload and the open platform at open.workbuddy.cn were considered and rejected:
  this engine talks to an internal JAS instance and handles real applicant PII.
- **`TESTING.md` Batch 5 (T20–T26) has not been run.** It needs a real Vera conversation.

## Packaging checklist (run before every handover)

The engine folder is not a git checkout — nothing prunes it for you. Two traps:

1. **`data/cache/` fills with real candidate data the moment anyone screens a job.**
   A single 7-CV run leaves seven `*-pii-redaction-v4-p1-fields.json` files (~10 KB each)
   holding redacted extracted fields. Delete the whole `data/cache/` folder before shipping.
   `data/taxonomy/skill_taxonomy.yaml` must stay — the scorer reads it and it is the only
   thing under `data/` that ships.
2. **`__pycache__` appears anywhere the engine has run.** Strip it, along with any
   `venv/`, `.env` holding a real key, and `venv-broken-*` left by a failed setup.

Then confirm the delivered `.env` still holds the placeholder, and re-run
`validate_expert.py` + `package_expert.py` if anything in this package changed.

## Grill stage

`agents/hr-cv-screener.md` carries the "after the refno, before parsing" conversation: quick-read
the ad, report what was parsed, ask at most five slot questions over at most two rounds, then
confirm the conditions and run.

HR supplements are written to `_pipeline/jd-overrides.yaml`, never appended to the JD as prose —
the engine does not score skills described in prose, and editing `jd.txt` would re-parse the job.
The pipeline then merges that file onto the parsed JD (`screening_core/jd_overrides.py`) and scores
against the result, so HR's corrections really do move the ranking. Each requirement HR changed is
stamped with a provenance origin, which the report renders as its own tooltip
("Moved by HR (conversation)"), and the report states which conditions produced the ranking
("Conditions: job ad only", or "Conditions: job ad + n HR supplements").

Two consequences worth knowing:

- `must_skills` / `preferred_skills` in the override are the **complete final lists**. A skill left
  out is treated as removed, and everyone is scored against the shorter list.
- Changing the override invalidates the cached scores but **not** the JD parse, so the must/nice
  assignment is never re-derived — re-parsing would make it probabilistic again.
