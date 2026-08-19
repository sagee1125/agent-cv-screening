# Unit tests for syncing the YAML skill taxonomy into the skill_taxonomy table.
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.sql import Insert, Select, Update

from app.core.taxonomy import SkillTaxonomyLoader
from app.services.taxonomy_sync import build_sync_plan, build_taxonomy_rows, sync_taxonomy_to_db

TAXONOMY_PATH = "data/taxonomy/skill_taxonomy.yaml"


def _taxonomy_names() -> list[str]:
    loader = SkillTaxonomyLoader(TAXONOMY_PATH)
    loader.load()
    return [node.skill for node in loader.nodes.values()]


def test_build_taxonomy_rows_maps_all_nodes() -> None:
    """Every taxonomy node maps to a row with category, synonyms, and parent name."""
    loader = SkillTaxonomyLoader(TAXONOMY_PATH)
    loader.load()
    rows = build_taxonomy_rows(loader.nodes)
    assert len(rows) == len(loader.nodes)
    python_row = next(row for row in rows if row["skill_name"] == "Python")
    assert python_row["category"] == "Programming Language"
    assert "python" in python_row["synonyms"]
    assert python_row["parent_name"] is None
    torch_row = next(row for row in rows if row["skill_name"] == "PyTorch")
    assert torch_row["parent_name"] == "Deep Learning"


def test_build_sync_plan_splits_inserts_and_updates() -> None:
    """Rows are split into inserts and updates based on existing skill names."""
    rows = [
        {"skill_name": "Python", "category": "Programming Language", "synonyms": [], "parent_name": None},
        {"skill_name": "Java", "category": "Programming Language", "synonyms": [], "parent_name": None},
    ]
    plan = build_sync_plan(rows, {"Python"})
    assert [row["skill_name"] for row in plan["to_insert"]] == ["Java"]
    assert [row["skill_name"] for row in plan["to_update"]] == ["Python"]


class FakeScalars:
    """Stands in for a result scalars() collection."""

    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values


class FakeResult:
    """Stands in for a query result."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalars:
        return FakeScalars([row[0] for row in self._rows])

    def all(self) -> list[Any]:
        return self._rows


class FakeSession:
    """Records executed SQL and serves canned rows for the sync flow."""

    def __init__(self, existing: list[str] | None = None) -> None:
        self.names: list[str] = list(existing or [])
        self.inserted: list[dict[str, Any]] = []
        self.updated: list[Update] = []
        self.flushed = False
        self.committed = False

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> FakeResult:
        if isinstance(stmt, Select):
            cols = [column["name"] for column in stmt.column_descriptions]
            if cols == ["skill_name"]:
                return FakeResult([(name,) for name in self.names])
            if cols == ["skill_name", "id"]:
                return FakeResult([(name, idx) for idx, name in enumerate(self.names)])
        if isinstance(stmt, Insert):
            params = args[0] if args else kwargs.get("params", [])
            for row in params:
                self.names.append(row["skill_name"])
                self.inserted.append(row)
        if isinstance(stmt, Update):
            self.updated.append(stmt)
        return FakeResult([])

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_sync_inserts_full_taxonomy() -> None:
    """First sync inserts every taxonomy row and commits."""
    session = FakeSession()
    counts = await sync_taxonomy_to_db(session, TAXONOMY_PATH)
    assert counts["inserted"] == 708
    assert counts["updated"] == 0
    assert counts["total"] == 708
    assert len(session.inserted) == 708
    assert session.flushed is True
    assert session.committed is True


@pytest.mark.asyncio
async def test_sync_updates_existing_rows() -> None:
    """Second sync updates existing rows instead of duplicating them."""
    session = FakeSession(existing=_taxonomy_names())
    counts = await sync_taxonomy_to_db(session, TAXONOMY_PATH)
    assert counts["inserted"] == 0
    assert counts["updated"] == 708
    # 708 row updates plus 708 parent-link updates.
    assert len(session.updated) == 708 * 2
    assert len(session.inserted) == 0
