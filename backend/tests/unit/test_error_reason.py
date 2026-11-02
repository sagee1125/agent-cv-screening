# The failure reason shown to HR must be the child's real error, never the
# library log noise around it. Regression: the tester's board showed
# "not scored: <green>[INFO] ... [RapidOCR] ... Using engine_name: onnxruntime"
# because the first stderr line was a coloured OCR log line.
import json
import subprocess
import sys
from pathlib import Path


def _load_pipeline():
    import importlib.util

    scripts = Path(__file__).resolve().parents[3] / ".codex" / "skills" / "pipeline" / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("rp_err", scripts / "run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rp_err"] = module
    spec.loader.exec_module(module)
    return module


NOISY_STDERR = (
    "\x1b[32m[INFO] 2026-11-02 11:51:30,714 [RapidOCR] base.py:23: Using engine_name: onnxruntime\x1b[0m\n"
    "\x1b[32m[INFO] 2026-11-02 11:51:31,002 [RapidOCR] base.py:23: det model loaded\x1b[0m\n"
    + json.dumps({"status": "error", "error_message": "Local OCR could not extract text from the PDF."})
    + "\n"
)


def test_strip_ansi_and_extract_envelope() -> None:
    rp = _load_pipeline()
    cleaned = rp._strip_ansi(NOISY_STDERR)
    assert "\x1b" not in cleaned
    assert rp._extract_child_error_message(cleaned) == "Local OCR could not extract text from the PDF."


def test_human_reason_skips_log_lines() -> None:
    rp = _load_pipeline()
    reason = rp._human_error_reason(NOISY_STDERR)
    assert reason == "Local OCR could not extract text from the PDF."
    assert "RapidOCR" not in reason and "engine_name" not in reason
    # No envelope at all: fall back to the last non-log line, not the first.
    only_logs = "[INFO] line one\n[INFO] line two\nreal failure happened here"
    assert rp._human_error_reason(only_logs) == "real failure happened here"
    # Pure log noise with nothing else: a safe generic, never raw noise.
    assert rp._human_error_reason("[INFO] only noise") == "file could not be processed"
    assert rp._human_error_reason("") == "file could not be processed"


def test_run_raises_the_envelope_message_not_the_log_line() -> None:
    rp = _load_pipeline()
    import base64

    payload = base64.b64encode(NOISY_STDERR.encode("utf-8")).decode("ascii")
    child = (
        "import sys, base64; sys.stderr.buffer.write("
        f"base64.b64decode('{payload}')); sys.exit(1)"
    )
    try:
        rp._run([sys.executable, "-c", child])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert str(exc) == "Local OCR could not extract text from the PDF."
        assert "RapidOCR" not in str(exc)


def test_unparsed_note_shows_the_real_reason() -> None:
    rp = _load_pipeline()
    failures = [
        rp.Failure(
            source="C:/x/305511.pdf",
            stage="cv-parse",
            attempts=1,
            error_message=NOISY_STDERR.strip(),
        )
    ]
    lines = rp._collect_unparsed_note(Path(__file__).parent, failures)
    assert len(lines) == 1
    assert "305511" in lines[0]
    assert "Local OCR could not extract text" in lines[0]
    assert "RapidOCR" not in lines[0] and "\x1b" not in lines[0]
