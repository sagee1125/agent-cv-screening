#!/bin/bash
# One-click installer for the CV screening engine (macOS).
# Provisions a PRIVATE Python 3.12 with uv (about 30 MB, one time). The Mac's
# own Python is never used, changed or required - nothing is installed
# system-wide.
# If macOS blocks this file: right-click it once and choose "Open".
set -u
cd "$(dirname "$0")" || exit 1

TARGET="$HOME/agent-cv-screening"
TOOLS="$TARGET/tools"
mkdir -p "$TOOLS" || exit 1

UV="$TOOLS/uv"
if [ ! -x "$UV" ]; then
  echo "Fetching the installer helper (uv, about 20 MB, one time)..."
  case "$(uname -m)" in
    arm64) ASSET="uv-aarch64-apple-darwin.tar.gz" ;;
    *)     ASSET="uv-x86_64-apple-darwin.tar.gz" ;;
  esac
  TMPDIR_UV="$(mktemp -d)"
  if ! curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/$ASSET" -o "$TMPDIR_UV/uv.tgz"; then
    echo ""
    echo "Could not download the installer helper. Check the internet connection"
    echo "(the download comes from github.com) and run setup.command again."
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
  fi
  tar -xzf "$TMPDIR_UV/uv.tgz" -C "$TMPDIR_UV" || exit 1
  UV_SRC="$(find "$TMPDIR_UV" -type f -name uv | head -n 1)"
  if [ -z "$UV_SRC" ]; then
    echo "The downloaded helper could not be unpacked."
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
  fi
  cp "$UV_SRC" "$UV"
  chmod +x "$UV"
  rm -rf "$TMPDIR_UV"
fi

echo "Setting up a private Python 3.12 (about 30 MB, one time)..."
"$UV" python install 3.12 || { echo "Could not set up Python 3.12."; read -n 1 -s -r -p "Press any key to close..."; exit 1; }

"$UV" venv --python 3.12 "$TARGET/venv" || { echo "Could not create the private environment."; read -n 1 -s -r -p "Press any key to close..."; exit 1; }

echo "Installing the screening components (a few minutes)..."
"$UV" pip install --python "$TARGET/venv/bin/python" -r engine/requirements.txt || { echo "Could not install the components."; read -n 1 -s -r -p "Press any key to close..."; exit 1; }

"$TARGET/venv/bin/python" scripts/setup_engine.py --engine-target "$TARGET" --skip-venv "$@"
status=$?
echo ""
read -n 1 -s -r -p "Press any key to close..."
exit $status
