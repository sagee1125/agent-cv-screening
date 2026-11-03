# Local testing without JAS access

The internal JAS pages are only reachable on the tester's machine. Everything
except the browser download flow can be tested locally with synthetic data.

## Level 0 — the test suite (seconds, no network)

    cd <repo>
    venv/Scripts/python.exe -m pytest backend/tests -q

834 tests: parsers, masking, portraits, pipeline, board rendering, mock e2e.

## Level 1 — the pipeline directly (needs only an API key)

    venv/Scripts/python.exe .codex/skills/pipeline/scripts/run_pipeline.py \
        --jd-json <any parsed JD> --cv a.pdf --cv b.doc \
        --position "Test Post" --with-portrait --output-dir out

Feeds CVs straight into parsing/scoring/portraits/reports. Word files,
scanned files, multi-post (`--cv-post appno=Post`) all testable here.

## Level 2 — the full offline chain with a synthetic JAS job (recommended)

One command builds a fake JAS export folder whose six applicants deliberately
cover the interesting paths (comma-name PDF, honorific name repeated in
publications, Word-docx-bytes-named-.pdf, image-only scanned PDF, blank
"Post applied for", applicant with no CV):

    venv/Scripts/python.exe backend/scripts/make_local_test_job.py --out testjob

Then run the whole chain — records-page parsing, staging, conversion, OCR,
masking, portraits, per-post scoring, reports — with no browser and no
internal network:

    venv/Scripts/python.exe .codex/skills/jas-import/scripts/run_jas_import.py parse-job \
        --html-file testjob/records.html \
        --output-dir testjob/_out --state-dir testjob/_state \
        --scratch-dir testjob/_scratch --no-open

Expected on the generated folder: status success; two post groups
(Research Assistant x2, Part-time x2); 9900005 listed under needs_confirmation
(blank post is never silently scored or dropped); the ranking board carries an
"Applicants not in this ranking" card naming 9900006 (no CV). Reports land on
the Desktop under workbuddy-cv-screen/<refno>. Delete that folder afterwards.

This level caught two real bugs on its first run (missing onnxruntime in the
shipped requirements — every scanned CV failed; and the real-site multi-post
signal gap fixed in v1.2.56).

## Level 3 — demo mode (network, no internal access)

`JES_SITE_MODE=0` in the engine `.env` screens the public demo jobs; the
expert accepts `--driver http`. Covers the fetch layer against a live (demo)
site.

## Notes

- Synthetic CVs contain fake PII on purpose — it exercises masking and the
  pre-send guard. Never mix them into real job folders.
- The e2e suite (`backend/tests/e2e/`) runs Level 2 hermetically with a
  seeded cache (no LLM spend): `pytest backend/tests/e2e -q`.
