# The diagnostics trail: privacy-safe events, capped footprint, and a
# collector that never bundles .env/CVs/reports.
import json
import zipfile
from pathlib import Path


def test_log_event_writes_and_trims(tmp_path, monkeypatch) -> None:
    import screening_core.diagnostics as diag

    trail = tmp_path / "logs" / "diagnostics.jsonl"
    monkeypatch.setattr(diag, "diagnostics_log_path", lambda: trail)
    diag.log_event("run", refno="1", version="1.2.59")
    diag.log_event("update", **{"from": "1", "to": "2"})
    events = [json.loads(line) for line in trail.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["run", "update"]
    assert events[0]["version"] == "1.2.59"

    # Over the cap: trimmed to the most recent lines, never grows unbounded.
    diag._MAX_TRAIL_BYTES = 200
    for i in range(50):
        diag.log_event("tick", i=i)
    lines = trail.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= diag._KEEP_LINES
    assert json.loads(lines[-1])["i"] == 49


def test_collector_bundles_only_safe_text(tmp_path, monkeypatch) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[3] / "CV-Screening-Setup" / "engine" / "collect_diagnostics.py"
    if not script.is_file():  # repo checkout without the package folder: skip
        return
    spec = importlib.util.spec_from_file_location("collector", script)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)

    engine = tmp_path / "engine"
    (engine / "data" / "logs").mkdir(parents=True)
    (engine / "version.json").write_text('{"version": "1.2.59"}', encoding="utf-8")
    (engine / "requirements.txt").write_text("rapidocr==3.9.2\n", encoding="utf-8")
    (engine / "data" / "logs" / "diagnostics.jsonl").write_text(
        '{"event": "run", "failure_reasons": ["cv-parse: onnxruntime is not installed"]}\n',
        encoding="utf-8",
    )
    jobs = tmp_path / "desktop" / "workbuddy-cv-screen" / "260417018" / "_pipeline"
    jobs.mkdir(parents=True)
    (jobs / "last-error-305511.txt").write_text("reason: onnxruntime", encoding="utf-8")
    # decoys that must NEVER be collected
    (engine / ".env").write_text("ZAI_API_KEY=secret", encoding="utf-8")
    (jobs.parent / "cvs").mkdir()
    (jobs.parent / "cvs" / "305511.pdf").write_bytes(b"%PDF-fake")

    monkeypatch.setattr(collector, "ENGINE_ROOT", engine)
    monkeypatch.setattr(collector, "_desktop", lambda: tmp_path / "desktop")
    assert collector.main() == 0
    zips = list((tmp_path / "desktop").glob("cv-diagnostics-*.zip"))
    assert len(zips) == 1
    names = zipfile.ZipFile(zips[0]).namelist()
    assert "version.json" in names and "diagnostics.jsonl" in names
    assert "jobs/260417018/last-error-305511.txt" in names
    assert not any(".env" in n for n in names)
    assert not any(n.endswith(".pdf") for n in names)
