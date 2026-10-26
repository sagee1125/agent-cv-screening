---
name: word-cv-parser
description: "Parse a candidate CV submitted as a Word document (.doc/.docx, including files misnamed as .pdf) into the same structured JSON the pdf cv-parser produces, by converting to PDF locally first and running the shared parser core. Privacy is preserved: conversion and parsing both happen on this machine; only masked content is sent to the LLM. Use when a CV file is a Word document by content and needs structured candidate data."
---

# Word CV Parser Skill

Entry point for Word submissions. Produces **the exact same JSON envelope** as
the `cv-parser` skill (same schema, same cache, same privacy pipeline), so
scoring/matching consumes both identically.

## How it works

1. Local conversion to PDF via the `word-convert` skill's converter
   (MS Word COM -> LibreOffice -> offline docx-text fallback).
2. The converted PDF is parsed by the regular `cv-parser` skill CLI
   (masking, redaction, OCR, text-first routing all apply unchanged).

## Run

```bash
venv/Scripts/python.exe .codex/skills/word-cv-parser/scripts/run_word_cv_parse.py --file <cv.doc|cv.docx> --output <extracted.json> [--jd-file <jd.txt>] [--converted-pdf <reuse-path.pdf>]
```

| flag | meaning |
|---|---|
| `--file` (required) | Word document (any extension; routed by magic bytes) |
| `--output` (required) | Target JSON path - identical format to cv-parser output |
| `--jd-file` (optional) | JD context forwarded to the parser |
| `--converted-pdf` (optional) | Reuse an existing converted PDF instead of re-converting |

Errors print `{"status": "error", "error_message": "..."}` on stderr and exit 1.

## Pipeline integration

`run_pipeline.py` routes by file content: real PDFs go to `cv-parser`, Word
documents go to this skill. The converted PDF is kept as
`converted-<slug>.pdf` in the output directory so retries and `--resume`
reuse it.
