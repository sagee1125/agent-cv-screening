from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes.feedback import feedback_analytics


class _Result:
    def __init__(self, *, scalar_one_or_none=None, scalar_one=None, all_rows=None) -> None:
        self._scalar_one_or_none = scalar_one_or_none
        self._scalar_one = scalar_one
        self._all_rows = all_rows or []

    def scalar_one_or_none(self):
        return self._scalar_one_or_none

    def scalar_one(self):
        return self._scalar_one

    def all(self):
        return self._all_rows


class FakeSession:
    def __init__(self) -> None:
        self._calls = 0
        self.job_created = datetime(2026, 1, 1)

    async def execute(self, _stmt):
        self._calls += 1
        if self._calls == 1:
            return _Result(scalar_one_or_none=SimpleNamespace(created_at=self.job_created))
        if self._calls == 2:
            rows = [
                (
                    SimpleNamespace(action="invite", created_at=datetime(2026, 1, 11)),
                    SimpleNamespace(rank=2, total_score=90),
                    SimpleNamespace(candidate_id=uuid4()),
                ),
                (
                    SimpleNamespace(action="invite", created_at=datetime(2026, 1, 21)),
                    SimpleNamespace(rank=12, total_score=80),
                    SimpleNamespace(candidate_id=uuid4()),
                ),
            ]
            return _Result(all_rows=rows)
        return _Result(scalar_one=2)


@pytest.mark.asyncio
async def test_feedback_analytics_formula() -> None:
    result = await feedback_analytics(uuid4(), db=FakeSession())
    assert result.top_10_hit_rate == 0.5
    assert result.average_score_invited == 85.0
    assert result.avg_time_to_hire_days == 10.0
