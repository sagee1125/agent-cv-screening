# Resolves repo-root data files such as the skill taxonomy YAML.
from __future__ import annotations

from pathlib import Path

from screening_core.bootstrap import find_repo_root


# Returns the absolute path of skill_taxonomy.yaml under the repository.
def taxonomy_yaml_path(start: Path | None = None) -> Path:
    root = find_repo_root(start or Path(__file__).resolve())
    candidates = (
        root / "data" / "taxonomy" / "skill_taxonomy.yaml",
        root / "backend" / "data" / "taxonomy" / "skill_taxonomy.yaml",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]
