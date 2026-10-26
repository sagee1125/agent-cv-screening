---
name: word-convert
description: "Convert submitted Word documents (.doc/.docx, including ones misnamed as .pdf) into real PDFs locally, so the PDF-only screening pipeline can parse them. No content ever leaves the machine. Use when: (1) a candidate submitted a Word CV instead of PDF, (2) a .pdf file fails to open because it is actually a Word document, or (3) the pipeline reports a file needs conversion before cv-parser can run."
---

# Word Convert Skill

Converts Word submissions to PDF **locally** (privacy-safe: nothing is uploaded)
so the rest of the screening pipeline (cv-parser masking, redaction, OCR)
works unchanged.

## Conversion backends (tried in order)

1. **Microsoft Word via COM** (Windows + installed Word, highest fidelity)
2. **LibreOffice headless** (`soffice`, Windows/macOS, if installed)
3. **Offline text extraction** (.docx only): pulls the text out of the docx XML
   and typesets a simple text-layer PDF with reportlab. Layout is lost, but
   the screening parser only needs the text layer and every masking rule
   still applies. Old `.doc` files have no offline fallback.

## Run

```bash
venv/Scripts/python.exe .codex/skills/word-convert/scripts/run_word_convert.py --file <cv.doc|cv.docx|cv.pdf> --output <cv.pdf>
```

| flag | meaning |
|---|---|
| `--file` (required) | Word document to convert (any extension; content is routed by magic bytes) |
| `--output` (optional) | Target PDF path (default: beside the source, same stem + `.pdf`) |

## Output JSON

```json
{"status": "success", "output": "C:/.../converted.pdf", "backend": "word_com|soffice|docx_text", "already_pdf": false}
```

Errors print `{"status": "error", "error_message": "..."}` on stderr and exit 1.
A file that is already a real PDF succeeds with `already_pdf: true` and is
copied to the output path, so callers need no routing logic of their own.

## Pipeline integration

`run_pipeline.py` calls this skill automatically whenever a `--cv` file is a
Word document by content (magic bytes), stores the PDF as
`converted-<slug>.pdf` beside the other artifacts, and resumes reuse it.
