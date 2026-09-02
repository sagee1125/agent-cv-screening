---
name: host-envelope
description: "Project pipeline or screening-agent JSON onto the WorkBuddy host-visible whitelist so the host LLM never sees CV/JD bodies, cookies, or candidate names."
---

# Host Envelope Skill

WorkBuddy (and any other chat host) must not attach raw skill stdout to the conversation model. This skill reads pipeline / screening-agent / JAS JSON from disk and prints a `HostToolReturn` object that matches `docs/workbuddy/host-tool-return.schema.json`.

## PII boundary

- Host-visible rows are keyed by `appno` (plus `refno` on the envelope). Names, first-letter masks, emails, cookies, JD/CV text, and report file contents are dropped.
- Report paths become booleans (`comparison_xlsx`, `pdf_count`, `html_ready`). `reports.directory` stays `null`.
- Cookie files are represented only as `auth.cookie_file_present`.

## Run

```bash
venv/Scripts/python.exe .codex/skills/host-envelope/scripts/run_host_envelope.py \
  --tool screen_refno \
  --input data/pipeline_out/manifest.json \
  --jas-manifest data/jas_out/jas-manifest.json \
  --jas-session granted \
  --cookie-file-present
```

Request JAS access (no skill stdout):

```bash
venv/Scripts/python.exe .codex/skills/host-envelope/scripts/run_host_envelope.py \
  --tool request_jas_access \
  --jas-session missing
```

Exit codes: `0` success / partial_success, `2` need_input, `1` error (`envelope_rejected` or projected `error`).

Contract: `docs/workbuddy/PRD-Host_Tool_Return_Whitelist_v1.0.md`
