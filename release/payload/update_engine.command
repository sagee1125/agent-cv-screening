#!/bin/bash
# Self-updater for the CV screening engine (macOS). Safe to run any time.
cd "$(dirname "$0")" || exit 1
PY="venv/bin/python"
[ -x "$PY" ] || PY=python3
exec "$PY" scripts/update_engine.py "$@"
