#!/bin/bash
# One-click installer for the CV screening engine (macOS).
# Installs to ~/agent-cv-screening by default and registers the WorkBuddy expert.
# If macOS blocks this file: right-click it once and choose "Open".
cd "$(dirname "$0")" || exit 1

PY=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ok=$("$candidate" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)' 2>/dev/null)
    if [ "$ok" = "1" ]; then PY="$candidate"; break; fi
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is required."
  echo "Option 1: run  xcode-select --install  (includes python3), or"
  echo "Option 2: install from https://www.python.org/downloads/"
  echo "Then run setup.command again."
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

"$PY" scripts/setup_engine.py "$@"
status=$?
echo ""
read -n 1 -s -r -p "Press any key to close..."
exit $status
