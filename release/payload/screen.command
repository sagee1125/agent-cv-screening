#!/bin/bash
# Run one screening command with the private interpreter already installed here.
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/venv/bin/python" "$ROOT/.codex/skills/host-envelope/scripts/run_workbuddy_tool.py" "$@"
