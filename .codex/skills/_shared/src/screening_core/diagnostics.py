# Central, privacy-safe diagnostics trail for remote support.
#
# Every screening run and engine update appends one JSON line to
# <engine-root>/data/logs/diagnostics.jsonl: versions, counts, timings and
# failure REASONS only - never CV content, contact details or prompt text.
# collect_diagnostics.py bundles this trail (plus last-error files) into a
# zip the HR user can send to support.
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from screening_core.config import settings

_LOCK = threading.Lock()


# Resolves the engine-root logs directory (settings.cache_dir is <root>/data/cache).
def diagnostics_log_path() -> Path:
    return Path(settings.cache_dir).parent / "logs" / "diagnostics.jsonl"


# Appends one structured event; never raises into the caller's flow.
# Footprint guard: the trail is capped at ~1 MB (trimmed to the most recent
# 2000 lines), so years of runs cannot grow it meaningfully.
_MAX_TRAIL_BYTES = 1_000_000
_KEEP_LINES = 2000


def log_event(event: str, **fields: Any) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **fields,
    }
    try:
        path = diagnostics_log_path()
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > _MAX_TRAIL_BYTES:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                path.write_text("\n".join(lines[-_KEEP_LINES:]) + "\n", encoding="utf-8")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # diagnostics must never break a screening run
        pass


# Reads the trailing events for the collector; missing file is not an error.
def read_events(limit: int = 500) -> list[dict[str, Any]]:
    path = diagnostics_log_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
