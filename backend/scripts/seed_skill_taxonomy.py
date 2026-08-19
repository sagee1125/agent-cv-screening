# CLI entry point to sync the YAML skill taxonomy into the skill_taxonomy table.
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.dependencies import AsyncSessionFactory
from app.services.taxonomy_sync import sync_taxonomy_to_db


async def run_sync(yaml_path: str) -> dict[str, int]:
    """Run the taxonomy sync against the configured database and return counts."""
    async with AsyncSessionFactory() as session:
        return await sync_taxonomy_to_db(session, yaml_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync the skill taxonomy YAML into the database.")
    parser.add_argument("--yaml", default="data/taxonomy/skill_taxonomy.yaml", help="Path to taxonomy YAML")
    args = parser.parse_args()
    counts = asyncio.run(run_sync(args.yaml))
    print(f"Taxonomy sync complete: {counts}")
