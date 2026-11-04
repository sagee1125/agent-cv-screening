"""Update the ZAI_API_KEY inside this engine's .env file.

Runs from update_key.bat in the engine root (the folder that also holds
venv/, check.bat and .env). Stdlib only, no venv required. The rest of the
.env - comments, database placeholders, storage paths - is preserved
byte-for-byte; only the ZAI_API_KEY line is rewritten.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PLACEHOLDER_MARKERS = ("<", "your-api-key")
KEY_LINE = re.compile(r"^ZAI_API_KEY=(.*)$", re.MULTILINE)


def looks_like_real_key(value: str) -> bool:
    """Same rule as the installer: non-empty and not a placeholder."""
    value = value.strip()
    return bool(value) and not value.startswith(PLACEHOLDER_MARKERS[0]) and PLACEHOLDER_MARKERS[1] not in value


def read_hidden(prompt: str) -> str:
    try:
        import getpass

        return getpass.getpass(prompt).strip()
    except Exception:
        # Some consoles cannot hide input; fall back to visible input so the
        # update can always complete.
        return input(prompt).strip()


def main() -> int:
    engine_root = Path(__file__).resolve().parent
    env_path = engine_root / ".env"
    if "--env" in sys.argv:
        # Optional override (used by tests and support diagnostics); the
        # double-click flow never passes it and resolves .env beside this file.
        env_path = Path(sys.argv[sys.argv.index("--env") + 1])
    if not env_path.is_file():
        print(f"ERROR: no .env found next to this script (looked in {engine_root}).")
        print("Run setup.bat first - it creates the .env file.")
        return 1

    existing = env_path.read_text(encoding="utf-8", errors="replace")
    if not KEY_LINE.search(existing):
        print("ERROR: this .env has no ZAI_API_KEY line; run setup.bat instead.")
        return 1

    print("Update the screening engine's API key (Zhipu open platform).")
    print("The input is hidden - right-click or Ctrl+V to paste, then Enter.")
    new_key = read_hidden("Paste the NEW API key: ")
    if not looks_like_real_key(new_key):
        print("CANCELLED: that does not look like a real key (empty or placeholder).")
        print("Nothing was changed.")
        return 1

    updated = KEY_LINE.sub(lambda match: f"ZAI_API_KEY={new_key}", existing, count=1)
    env_path.write_text(updated, encoding="utf-8")

    # Verify the write actually landed before claiming success.
    check = KEY_LINE.search(env_path.read_text(encoding="utf-8", errors="replace"))
    if check and looks_like_real_key(check.group(1)):
        print("[ok] New API key written.")
        print("Next: quit WorkBuddy completely and open it again, then screen as usual.")
        return 0
    print("ERROR: the write could not be verified - open .env in Notepad and check")
    print("the ZAI_API_KEY line by hand.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
