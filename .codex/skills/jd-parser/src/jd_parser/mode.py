# Normalizes JD parser mode labels used by CLI and REST.
VALID_MODES = ("rule", "hybrid", "qwen")


# Maps a user-supplied parser mode to a known mode string.
def normalize_mode(mode: str | None) -> str:
    normalized = (mode or "").strip().lower()
    return normalized if normalized in VALID_MODES else "rule"
