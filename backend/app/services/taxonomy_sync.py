# Syncs the curated YAML skill taxonomy into the skill_taxonomy database table.
from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.taxonomy import SkillTaxonomyLoader
from app.models.database import SkillTaxonomy

DEFAULT_TAXONOMY_PATH = "data/taxonomy/skill_taxonomy.yaml"


def build_taxonomy_rows(nodes: dict[str, Any]) -> list[dict[str, Any]]:
    """Map taxonomy nodes to plain skill_taxonomy row dicts for upsert."""
    return [
        {
            "skill_name": node.skill,
            "category": node.category,
            "synonyms": list(node.synonyms),
            "parent_name": node.parent,
        }
        for node in nodes.values()
    ]


def build_sync_plan(rows: list[dict[str, Any]], existing_names: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Split taxonomy rows into insert and update buckets by existing skill names."""
    return {
        "to_insert": [row for row in rows if row["skill_name"] not in existing_names],
        "to_update": [row for row in rows if row["skill_name"] in existing_names],
    }


async def sync_taxonomy_to_db(
    session: AsyncSession,
    yaml_path: str = DEFAULT_TAXONOMY_PATH,
) -> dict[str, int]:
    """Upsert the YAML taxonomy into skill_taxonomy and return inserted/updated counts."""
    loader = SkillTaxonomyLoader(yaml_path)
    loader.load()
    rows = build_taxonomy_rows(loader.nodes)

    existing = set((await session.execute(select(SkillTaxonomy.skill_name))).scalars().all())
    plan = build_sync_plan(rows, existing)

    if plan["to_insert"]:
        await session.execute(
            insert(SkillTaxonomy),
            [
                {
                    "skill_name": row["skill_name"],
                    "category": row["category"],
                    "synonyms": row["synonyms"],
                    "is_active": True,
                }
                for row in plan["to_insert"]
            ],
        )
    for row in plan["to_update"]:
        await session.execute(
            update(SkillTaxonomy)
            .where(SkillTaxonomy.skill_name == row["skill_name"])
            .values(category=row["category"], synonyms=row["synonyms"], is_active=True)
        )

    await session.flush()
    name_to_id = dict((await session.execute(select(SkillTaxonomy.skill_name, SkillTaxonomy.id))).all())
    for row in rows:
        parent_id = name_to_id.get(row["parent_name"]) if row["parent_name"] else None
        await session.execute(
            update(SkillTaxonomy)
            .where(SkillTaxonomy.skill_name == row["skill_name"])
            .values(parent_skill_id=parent_id)
        )

    await session.commit()
    return {"inserted": len(plan["to_insert"]), "updated": len(plan["to_update"]), "total": len(rows)}
