#!/bin/bash
# Self-updater for the CV screening engine (macOS). Safe to run any time.
# Works from the installed engine folder AND from the downloaded zip folder.
# The WorkBuddy expert also runs this quietly before the first screen.
cd "$(dirname "$0")" || exit 1

# The WorkBuddy expert calls this with --quiet from a hidden console; a
# "press any key" there would block the conversation. Manual double-click
# runs, however, must not see the update result vanish instantly.
quiet=0
if [ "${1-}" = "--quiet" ]; then
  quiet=1
fi

status=0
if [ -x "venv/bin/python" ] && [ -f "scripts/update_engine.py" ]; then
  venv/bin/python scripts/update_engine.py "$@"
  status=$?
else
  # Update the installed engine instead - but only a CURRENT-shape install
  # (private venv AND the updater script inside it); an old-architecture copy
  # (everything in the home folder root, no scripts/) would crash with
  # "can't open file" behind a success-shaped exit.
  TARGET="$HOME/agent-cv-screening"
  if [ -x "$TARGET/venv/bin/python" ] && [ -f "$TARGET/scripts/update_engine.py" ]; then
    "$TARGET/venv/bin/python" "$TARGET/scripts/update_engine.py" "$@"
    status=$?
  else
    echo "The screening engine is not installed on this computer yet."
    echo "Run setup.command first - it needs no other software and takes a few minutes."
    if [ "$quiet" -ne 1 ]; then
      read -n 1 -s -r -p "Press any key to close..."
    fi
    exit 1
  fi
fi

if [ "$quiet" -ne 1 ]; then
  read -n 1 -s -r -p "Press any key to close..."
fi
exit $status
