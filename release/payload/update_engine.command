#!/bin/bash
# Self-updater for the CV screening engine (macOS). Safe to run any time.
# Works from the installed engine folder AND from the downloaded zip folder.
# The WorkBuddy expert also runs this quietly before the first screen.
cd "$(dirname "$0")" || exit 1
if [ -x "venv/bin/python" ]; then
  exec venv/bin/python scripts/update_engine.py "$@"
fi

# No private environment in this folder, so this is the downloaded zip.
# Update the installed engine instead (setup.command installs it here).
TARGET="$HOME/agent-cv-screening"
if [ -x "$TARGET/venv/bin/python" ]; then
  exec "$TARGET/venv/bin/python" "$TARGET/scripts/update_engine.py" "$@"
fi

echo "The screening engine is not installed on this computer yet."
echo "Run setup.command first - it needs no other software and takes a few minutes."
read -n 1 -s -r -p "Press any key to close..."
exit 1
