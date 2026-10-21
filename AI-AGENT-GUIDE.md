# AI Agent Guide — what you must know before working on this repo

Audience: any AI agent (or engineer) about to modify this repository. This file covers
what the project actually is, how the release pipeline works, the invariants that were
learned the hard way, and a digest of every fixed bug so you do not re-diagnose them.
`AGENTS.md` (screening conversation contract, code comment rules) remains mandatory;
this file adds the engineering view.

Last updated for: **v1.2.35** — the v1.2.32 cycle shipped the v1.2.31 batch (key.txt build
guard, WorkBuddy-absent updater advice, install-page ordering) plus the pyvenv.cfg parse
fix (§6.14); v1.2.33 added the OneDrive-aware Desktop resolver (§6.15) and the
install-shape checks in the updater launchers; v1.2.34 filled doc gaps (this guide +
START-HERE troubleshooting); v1.2.35 corrected the expert's daemon-repair wording to
match what the engine actually does (§6.16) — no code changed.

## 1. What this product is

Non-technical HR users screen job applicants with an expert called **Vera** inside the
**WorkBuddy** desktop app. The engine repo is `sagee1125/agent-cv-screening` (mirrored to
PolyU GitLab, both interactively pushed on every release). The shipping surface:

1. **The zip.** GitHub CI builds `CV-Screening-Setup.zip` on every `vX.Y.Z` tag and attaches
   it (plus a `CV-Screening-Setup.zip.sha256` sidecar) to the GitHub release, but **only
   after** the Windows and macOS launcher rehearsals both pass.
2. **The installer.** HR double-clicks `setup.bat` (Windows) / `setup.command` (Mac). No
   Python is required: the launcher fetches a **pinned uv** (0.12.18), provisions a
   **private Python 3.12**, creates the venv, installs pinned requirements
   (`release/engine-requirements.txt`), installs the expert, and runs a self-test.
3. **The self-updater.** Screening conversations start with a quiet update check
   (`--quiet`). On a newer release it refreshes the engine code and the expert, refreshes
   dependencies only when `requirements.txt` changed, rebuilds the private venv when
   `requires_python` differs, verifies the download's sha256, and busts score caches so
   new code is never ignored by the `--resume` mechanism.

## 2. Source-of-truth and do-not-touch rules

- **`release/payload/` is the single source of truth for everything HR receives.** The
  zip is built from it by `release/build_release.py <X.Y.Z>`.
- **`C:\Users\User\Desktop\CV-Screening-Setup` is NOT the project.** It is an extracted
  *old test zip* that has drifted from the repo. Never "fix" it, never copy from it, and
  never spend a session reconciling it. Any file there is worthless.
- The repo root also contains an older web-app track (`backend/`, `frontend/`, Docker,
  `README.md` describes it). It is not part of the shipped release. Do not mix its
  assumptions into installer/updater work.
- Engine sources that get shipped into the install live at the repo root
  (`.codex/`, `data/taxonomy/`, `site_profiles.json`, `.env.example`) — `build_release.py`
  copies exactly those via `ENGINE_COPY`, plus `release/engine-requirements.txt`.

## 3. Where the important code lives

| File | Role |
|---|---|
| `release/payload/scripts/setup_engine.py` | installer core: env template, expert install, marketplace merge, SKILL.md path rewrite, version stamping, WorkBuddy-presence detection, self-test |
| `release/payload/scripts/update_engine.py` | self-updater: version check, checksum verify, apply, venv rebuild, cache busting |
| `release/payload/setup.bat` / `setup.command` | HR launchers: pinned-uv fetch, Python provisioning, single setup call |
| `release/payload/update_engine.cmd` / `.command` | updater entry: runs from installed engine, or updates the installed engine when launched from a downloaded zip folder |
| `release/payload/screen.cmd` / `screen.command` | host-envelope entrypoints: run one screening command with the installed venv's python; WorkBuddy calls these, they never create another environment |
| `release/build_release.py` | zip builder: staging, stamp, sidecar, sha256, forbidden-file guard |
| `release/tests/simulate_install.py` | rehearsal engine (see §5) |
| `release/expert/hr-cv-screener/skills/hr-cv-screening/SKILL.md` | the expert's operating manual, read by WorkBuddy at runtime; contains shell placeholders that the installer rewrites |
| `.github/workflows/release.yml` | 4-job pipeline: build → rehearse-windows / rehearse-macos → publish |
| `docs/FRS.md`, `docs/ENGINEERING_SPEC.md`, `docs/overall-logic-summary.md` | functional requirements (e.g. FR-10 cache rules, FR-11 per-post comparability) |

## 4. The release ritual (unchanged, mandatory)

1. Fix/feature lands on `main`.
2. Commit and push **both remotes**: `github` and `origin` (GitLab mirror).
3. Tag `vX.Y.Z` and push the tag.
4. CI runs `build` (zip + artifact), then launcher rehearsals, then `publish` attaches
   the zip + sidecar to the release created for the tag.
5. Verify anonymously via the GitHub REST API (no `gh` CLI and no token live on the dev
   machine; Actions logs need a login — use the public REST endpoints, e.g.
   `actions/runs`, `actions/runs/<id>/jobs`, `releases/latest`).
6. Spot-check the released asset contents (download the zip and read files inside it)
   before reporting success.

Tag the release even for small changes — the fleet self-updates from tags, and the
version stamp is derived from the tag at build time.

**The published asset is what CI built from the tag — never distribute a locally built
`release/dist/CV-Screening-Setup.zip`.** A dev-machine build made before the tag will not
share the published sha256 (autocrlf line-ending checkout, plus build-versus-tag timing),
so a hash mismatch against `releases/latest` for it is expected. Point users at the
GitHub release instead: that asset is the only one the updater's checksum chain (§6.2)
is built around. Seen directly on 2026-10-20: the local v1.2.33 dist zip hashed
`8ddf03c8…`, the published asset `f741303f…`, with byte-identical payloads once CRLF
was normalized — the only difference that was real was nothing in the files.

## 5. The rehearsal system (know it before changing anything shipped)

`release/tests/simulate_install.py` installs the zip into a disposable sandbox (a fake
home; nothing touches the real profile) and asserts the result. Modes:

- default — drives uv and `setup_engine.py` directly (fast; skilled hands, not the UI).
- `--setup-bat` / `--setup-command` — runs the launcher HR actually double-clicks,
  end to end (Windows-only / macOS-only; re-downloads uv).
- `--update` — after the install, stamps it as version 0.0.0 and lets the live updater
  pull the previous release from github.com and apply it.

Diagnostics rule: every step's output is teed to `release/tests/rehearsal-output.txt`
via the `record()` helper, and on failure the workflow opens a **GitHub issue with that
file** (issues are readable without a login). This exists because Actions logs require a
login — it is the only way remote failures were ever diagnosed. Anything new that runs
in CI rehearse must wrap its output through `run(...)/record(...)`; an unhandled
exception must still land in the diagnostics file (see `main()`'s except blocks).

A rehearsal never asserts against a path with spaces in the username (CI runners are
`runneradmin`), so space-path behavior is unit-tested or reasoned, not CI-proven.

## 6. Invariants and edge cases (each one has a broken-deploy backstory)

**Broken-deploy history**: every CI run #35–#45 fixed one real, previously unknown
failure. Constraints now considered "obvious" were learned there; the sections below
name the version whose CI failure produced the constraint. Run #46+ are clean.

### 6.1 Update check must not touch api.github.com (v1.2.29, run #44)
Unauthenticated GitHub API calls are capped at **60 per hour per IP** and a whole office
shares one public address: every machine failed at once on a busy morning and was told
"offline". The release tag is read from the redirect of
`releases/latest/download/CV-Screening-Setup.zip` (HEAD request; not rate-limited). If
the redirect cannot be parsed (some proxies rewrite it), fall back to downloading the
zip and reading `engine/version.json` — and reuse that copy for the update. Do not
re-introduce API calls to "simplify".

### 6.2 Download integrity (v1.2.30)
Every applied download is verified against `CV-Screening-Setup.zip.sha256` (same
`releases/latest/download/` endpoint). Semantics are deliberate:
- **mismatch → hard abort** (a truncated/tampered zip must never overwrite a working engine);
- **missing sidecar or fetch error → continue with a note** (releases ≤ v1.2.29 have no
  sidecar; the zip is already fully on disk and TLS-protected; the first-boot path must
  not gain new hard failure modes).
When you change packaging, update the sidecar story together with it.

### 6.3 Version stamp discipline (v1.2.19 / v1.2.30)
`version.json` on an installed root carries `version`, `requirements_sha256`,
`requires_python`. Rules:
- A fresh install must stamp the **shipped** version, never `0.0.0` (a 0.0.0 stamp made
  every new install re-download and re-apply the same release minutes after installing).
- Dependencies are refreshed **before** the stamp advances; a dependency failure
  **restores the previous stamp** so the next conversation retries the whole update.
  Advancing first would report a half-applied update as done — the one failure that
  must never be silent.
- `requires_python` must ride along through install (the installer rebuilds the stamp
  from the payload's `engine/version.json`; it once silently dropped the field, which
  would have disabled future interpreter rebuilds on every machine — caught by the
  rehearsal check, not by CI).

### 6.4 Interpreter bump = build-then-swap, never delete the running venv (v1.2.30)
`requires_python` says what a release needs; `venv/pyvenv.cfg` says what the machine has
(the file format differs between `uv venv` and the `venv` module — subsequent keys
identical). On a mismatch the updater rebuilds a sibling `venv-new-*` (python fetch,
venv create, pinned requirements) and swaps only after full success. **Windows cannot
delete a running interpreter but can rename it** — so the swap renames the old venv to
`venv-old-*` and the leftovers are swept on the next update. Do not replace this with
in-place deletion; do not be tempted to `rmtree` the venv while the updater runs from it.

### 6.5 Path hazards
- **Forward slashes are rejected by the Windows command runner** (`C:/` reads as
  "permission denied"). The SKILL.md fixed-path contract intentionally says so, and the
  installer rewrites the placeholders to the OS's own separators
  (`rewrite_skill_paths`). The installed skill must never carry another machine's paths.
- **Spaces in Windows usernames.** The engine only lands on a spacey path when `C:\` is
  not writable and the launcher fell back to the user profile. `rewrite_skill_paths`
  then quotes every engine path (cmd.exe accepts a quoted path; a bare spacey path tears
  the command apart at the first space). Every engine path in SKILL.md is bare
  (start-of-line/command), so a single wrap is unambiguous. The "When a command is
  refused" ladder ends with the PowerShell `& ` prefix for quoted lines.
- **CRLF.** The dev checkout has `core.autocrlf=true`: git's CRLF warnings are normal
  noise, never fix them by re-normalizing files. What matters: `build_release.py`
  normalizes the three commands to LF inside the zip, because bash on macOS cannot run a
  CRLF shell script.

### 6.6 Update apply: expert = total refresh, engine = merge (v1.2.28)
The **expert** install is delete-first: `install_expert` removes the destination
directory and copies the new tree, so files removed upstream do not linger on machines
that have updated for months (the stale-file fix). The marketplace merge of the expert
happens **outside** the wiped dir. The **engine** update is a
`copytree(dirs_exist_ok=True)` **merge** with ignore patterns, not a wipe — the engine
root holds live state (`venv`, `.env`, `data/`) that must survive an update.
Consequence to remember: a file upstream *deleted* inside the engine tree keeps
lingering on updated machines (harmless but real); only the expert tree gets the
delete-first guarantee. `.env`, `venv` and `_backup-*` are never touched by either copy.

### 6.7 Cache rules (FR-10)
On a version change, score-cache families (`detail-*.json`, `rows.json`,
`board-row-*.json`, `report-fingerprints.json`) are **moved** into a per-job
`_pipeline/_backup-<ts>/` — never deleted. `jd-overrides.yaml` and the JD parse cache
are **never touched** (HR's conditions and cached parses are not invalidated by a code
update; re-parsing would not be score-neutral).

### 6.8 uv is pinned (0.12.18), not "latest"
A previous version habit (pinning `releases/latest`) handed every machine whatever uv
most recently published; one broken build then broke installs everywhere that day,
with no fallback. Keep the pin; bump it deliberately and update both launchers at once.

### 6.9 Apple-Silicon uv asset names (v1.2.25)
`UV_ASSETS` in `simulate_install.py` maps `(os, arch)` → uv asset; the table is
lowercase-canonical, and an early version case-bug killed every Apple Silicon
rehearsal with `SystemExit`. Normalize case when adding platforms.

### 6.10 Never block a screening
The expert calls the updater with `--quiet` at the start of a conversation. Quiet mode
prints exactly one `update_status=...` line and exits 0 — **including when the check
fails**. Any change that makes the updater raise or emit more lines in quiet mode
will block HR's screening; conversely a `check` run (non-quiet) explains to the user.
After applying an update the expert tells HR to restart WorkBuddy so the new expert
loads (wording lives in SKILL.md's "Engine self-update" section and the updater's
non-quiet output).

### 6.11 WorkBuddy may be absent — never block the install (v1.2.19)

The desktop app is GUI-only (a Windows .exe or a macOS .dmg from the official install
page): there is no CLI, no silent install and no package manager entry, so the most an
installer can do is detect the absence and open the official page. Rules:

- Detection paths: Windows `%LOCALAPPDATA%\Programs\WorkBuddyAI` (or `...\WorkBuddy`);
  macOS `/Applications/WorkBuddy.app` or `~/Applications/WorkBuddy.app`. It is only a
  hint — a missing app never blocks the install.
- Either way the engine, the private venv and the expert are installed in full.
  WorkBuddy scans `plugins/marketplaces/my-experts` on startup, so an expert written
  before the app is installed is picked up when the app first runs.
  `workbuddy_config_dir()` writes `~/.workbuddy-ai`, falling back to `~/.workbuddy`
  only when that already exists.
- The install URLs live in exactly one place (`WORKBUDDY_INSTALL_GUIDES` /
  `WORKBUDDY_SITE` in setup_engine.py). A missing app changes only the final
  instructions (setup_engine.py's ending) and START-HERE.txt's lead section.
- The non-quiet updater reuses the same detection for its post-update advice
  (post-v1.2.30): restart advice when the app is present, install-page guidance when it
  is not. The expert's quiet path prints neither.

### 6.12 The API-key protocol (three entry points, one file)

HR supplies `ZAI_API_KEY` themselves; nothing is invented. `write_env` priority: an
existing real key in `.env` is kept verbatim on re-runs; otherwise `key.txt` (first
non-empty line — read, then **deleted**, so no copy lingers); otherwise the
`CVS_API_KEY` environment variable (what the rehearsal, and an assistant installing on
the user's behalf, use); otherwise a hidden getpass prompt (visible input only when the
console cannot hide it). With no usable key a placeholder is written and the installer
says so — screening fails authentication until `.env` is edited and setup is re-run.
Nothing else may join that chain: a key must never travel through a command line or a
chat message.

### 6.13 Private files never ship (build guard)

`sanity_checks` in `build_release.py` scans the staged tree for every name in
`FORBIDDEN_IN_ZIP` (`.env`, `key.txt`, `id_rsa`, `*.pem`, `jas_state`) and one hit
aborts the build before a zip exists. `key.txt` joined the list post-v1.2.30: the
installer protocol (§6.12) has users drop it next to setup.bat, and `payload/` mirrors
the zip layout, so a leftover test copy in `payload/` would publish a user's API key
inside the public release asset.

### 6.14 Reading pyvenv.cfg by key name — uv's own version line is a trap

`venv_python_version` reads the installed venv's interpreter from `venv/pyvenv.cfg`
(`requires_python` says what a release needs; the cfg says what the machine has).
Read the **named keys** — `version` / `version_info`, with a `home`-dir
`cpython-3.12-...` fallback — never "the first dotted number in the file": uv 0.12.18
(the pinned launcher version) emits `uv = 0.12.18` **before** `version_info = 3.12`,
and a blind regex read **uv's own version** — the venv looked like Python 0.12, so
**every update** decided the interpreter had to be rebuilt (a needless ~5-minute
rebuild per update on real machines, and a hard failure on any install without
`<engine>/tools/uv`; the CI direct-drive rehearsal hit exactly that in the v1.2.31
run — the first rehearsal to meet a live release carrying `requires_python`). The
venv-module format (`version = 3.12.0`) and older uv (`version_info = 3.12.14`) parse
correctly either way; only the pinned uv's two-part `version_info` plus its
self-version line broke it. `reprovision_venv` also accepts a uv found on PATH, for
installs made without a launcher.

### 6.15 Every shipped Desktop lookup goes through the OneDrive-aware resolver (v1.2.33)

The engine resolves the visible Desktop through `hr_output.user_desktop()` —
plain `Desktop`, then `OneDrive/Desktop`, then both under the Chinese-named
`桌面` — because OneDrive redirection and Chinese desktop names are both common
on staff machines. Three shipped files once hardcoded `Path.home()/Desktop`
instead and silently missed those machines:

- `update_engine.py`'s cache bust skipped invalidation on exactly those
  machines, so `--resume` kept serving scores produced by the OLD engine — the
  stale-score failure FR-10 exists to prevent. It now mirrors `user_desktop()`
  locally (`reports_desktop()`); the resolver must stay stdlib-only because the
  updater also ships inside the zip and runs without the engine's deps.
- `run_workbuddy_tool.py`'s pipeline/JAS manifest reads returned `{}` there,
  degrading the host projection to the skill's raw stdout. They now import
  `screening_core.hr_output.user_desktop` — `_bootstrap` already puts
  `_shared/src` on `sys.path`, so keep it that way.
- `webridge-collect` and the report writers were always correct: they already
  used `hr_output`'s resolver, which is why the two regressions above could
  hide for so long — reports still landed in the redirected folder while the
  cleanup/projection side looked elsewhere.

Rule: never introduce another `Path.home() / "Desktop"` in shipped code —
import `user_desktop()` (engine side) or mirror `reports_desktop()` (updater
side). Rehearsals can never prove it (CI runners have plain Desktops), so
treat a change there as eyes-on only.

Related v1.2.33 hardening in the updater launchers (`update_engine.cmd` /
`.command`): they now only route to an install holding BOTH its private venv
and `scripts/update_engine.py` (a pre-payload ancient layout met on a real
machine ran the updater against its own missing file and still reported
success), never pause under `--quiet` (the expert's hidden console must not
block), keep the window open for double-click runs, and pass the updater's
exit code through.

### 6.16 Shipped docs must only cite artifacts the code actually creates (v1.2.35)

SKILL.md's daemon-repair bullet told HR to double-click
`Startup\start-webbridge-daemon.cmd` / `Desktop\start-webbridge-daemon.cmd` and called
"a logon-started instance" the durable one — but nothing in this repository (setup,
updater, engine, daemon client) has ever created either file; the only real mechanism is
`ensure_webbridge_daemon()`'s per-run auto-start of `~\.kimi-webbridge\bin\kimi-webbridge`
(commit 802a9f9). The wording rode in with the packaging commit (5e10432) and described
intent, not code. An expert doc is an executable part of the product: Vera relays it as a
procedure, so a fictional path sends a non-technical user looking for files that are not
there — in exactly the "second screen in one conversation" race the earlier loop fought.
v1.2.35 rewrote the two paragraphs to describe per-run auto-start plus the real manual
remedy (helper CLI `start`, then wake Chrome so the MV3 worker reconnects). Rule: before
shipping any instruction that names a file, grep the repo for what creates it; when the
fix needs an artifact the code does not make, either make the code or drop the
instruction.

## 7. The WorkBuddy conversation contract (summary — full text in AGENTS.md and SKILL.md)

This is what made the product survive real HR use; do not water it down:

- **Ask for the refno immediately** when one was not supplied. Never scan the file
  system for previous runs, never invent one.
- **Reply in the language HR used** — and "Chinese" is decided by script, not a word
  list: a Simplified-character message must be answered in **Traditional** Chinese.
- **One reply, one deliverable, one language.** No recap, no "in short", no echo of the
  same outcome in the other language. Both shapes have actually leaked into production
  replies after separate fixes.
- **Never leak the engine's internal vocabulary** (`pipeline`, `gate`, `cache`,
  `dimension`, …) into HR-facing text. Say "required skills", "the conditions you set
  earlier".
- **Privacy red line**: identification is `refno`/`appno` only. Never candidate names,
  emails, phones or salaries in reports. Reports live on the Desktop
  (`workbuddy-cv-screen/<refno>/`), not in the chat — do not load report files into the
  chat model.
- **Multi-post jobs**: scores are comparable within a post and not across posts (FR-11);
  every multi-post summary must say so, per post.

## 8. Console output rules

- **English only, ASCII-safe.** Installer/sysmsg console output must survive Windows
  code pages. Traditional Chinese is for HR-facing WorkBuddy replies (SKILL.md), not
  for installer console printouts.
- **Console mojibake is display, not corruption.** The WorkBuddy display fields in
  `plugin.json` (the zh `displayName` / `profession` / `quickPrompts`) and all SKILL.md
  text are UTF-8 without BOM. PowerShell's default `Get-Content` renders them as
  garbage — that is the console's code page, the file itself is fine (verify with
  Python: `json.loads(path.read_bytes().decode("utf-8-sig"))`, or any editor that
  shows an encoding picker). Never "fix" this by resaving through an ANSI-default
  editor or pipeline: WorkBuddy reads these fields as Traditional Chinese, and a
  mojibake save would ship mojibake to every HR machine. When editing, save as UTF-8
  and re-verify the zh fields parse.
- Comments: this repo's house style is heavy explanatory comments that capture *why*,
  especially failure histories. Preserve them; they are the institutional memory that
  keeps agents from re-breaking things. Follow the comment format rules in AGENTS.md.

## 9. Verified-facts vs. assumption discipline

Any claim that is load-bearing must be verified before it is trusted:

- **Two different API surfaces — do not confuse them.** The *installed updater* must
  never call `api.github.com` at runtime (§6.1, rate limit). Verifying *CI status and
  releases* from a dev session via the anonymous REST API is fine and is the standard
  way to confirm a release here.
- Local dev machine quirks: PowerShell **5.1** (no `try/catch` as an expression,
  here-string quirks — pass commit messages with `git commit -F <file>` instead of
  inline quoting), no `gh` CLI, no GitHub token — `gh`-based commands exist only in CI.
- Wheels for the rehearsal cache live in `release/tests/wheels/` (used by the sim's
  uv install; `--setup-*` modes hit pypi live instead).

## 10. Known open items

- The old rehearsal-diagnostics issues (#7–#10, v1.2.19–v1.2.28 loop) are all closed.
  #11 documents run #46 (v1.2.31, the pyvenv.cfg failure of §6.14) — its fix shipped in
  v1.2.32 and v1.2.32/v1.2.33 both ran green, so the issue holds no open work and can be
  closed by hand whenever someone is logged in (the machine opening issues has no token
  to close with).
- The persistent-daemon question (v1.2.35, §6.16): the installer still does not create a
  logon-started WebBridge daemon; the expert docs now truthfully describe per-run
  auto-start plus the helper-CLI manual start. If this is ever wanted (calm cycle):
  setup_engine + update_engine write an idempotent logon entry + Desktop shortcut
  (Windows) and a LaunchAgent (macOS), and SKILL.md may name those files again. The
  2026-10-21 cycle shipped only the doc correction under a same-day on-site deadline.
  Until then, watch live screenings for the second-screen daemon race; the manual start
  path is the daily fix.
- The updater rehearsal in CI validates against the **previous** live release (the one
  already published). Rehearsals for tags up to v1.2.30 therefore exercised the tolerant
  legacy path — no `requires_python`, no sidecar — which is exactly why the pyvenv.cfg
  regression of §6.14 walked past every green run until v1.2.31's rehearsal was the
  first whose target (v1.2.30) carried the new fields. From that run on, every
  rehearsal validates the modern path (stamp fields + sidecar), and the asymmetry
  survives only as a diagnostic lens: a failure while the target release still lacked
  the fields is a legacy-parsing regression, a failure once it carries them is the
  §6.14 class. Keep this in mind when a rehearsal elusively passes for what looks like
  the wrong reason.
- A future `requires_python` bump procedure: change `REQUIRES_PYTHON` in
  `build_release.py` **and** the launchers' pinned `uv python install 3.x` and
  `uv venv --python 3.x` in the same commit; expect every installation to take a
  one-time ~5-minute rebuild on their next update, and verify the wheels actually ship
  for the new minor (the pinned dependency set only has wheels for certain minors —
  see SUPPORTED_PYTHON in setup_engine.py for the verified set). Post-v1.2.31 such a
  bump is also rehearse-able end to end: the direct rehearsal path now mirrors the
  launcher layout (uv left in `<engine>/tools`), and `reprovision_venv` accepts a uv
  from PATH too.
- The CI runners never have WorkBuddy installed, so the rehearsals always execute the
  installer's missing-app branch — but nothing asserts its message text, and the
  installed-app branch never runs in CI at all. Both are plain logging; a change there
  needs eyes, not just green CI.

## 11. Change style

- Keep changes surgical and typed: one batch of fixes = one commit = one tag = one CI
  run to verify (a batch may bundle pairs like #7+#10, but never unrelated tracks).
- Heavy "why" comments in the style already in the files; a fix without its history
  attached will be "refactored away" by the next agent and re-broken.
- Every new invariant above began as somebody's "harmless simplification". When you
  add one, add it to this file (§6) in the same commit.
