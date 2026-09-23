from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.database.repositories import MarketBarRepository
from app.schemas.market_data import MarketBar


class Result:
    rowcount = 1


class FakeSession:
    def __init__(self) -> None:
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return Result()

    async def scalar(self, statement):
        self.statements.append(statement)
        return 42

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_bar_upsert_targets_provider_aware_unique_constraint() -> None:
    session = FakeSession()
    repository = MarketBarRepository(session)
    market_bar = MarketBar(
        ticker="AAPL",
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=100,
    )

    affected = await repository.upsert_daily_bars([market_bar], provider="massive")

    compiled = str(session.statements[-1].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_market_bars_identity DO UPDATE" in compiled
    assert affected == 1
    assert session.commits == 1


@pytest.mark.asyncio
async def test_empty_upsert_is_a_noop() -> None:
    session = FakeSession()

    affected = await MarketBarRepository(session).upsert_daily_bars([], provider="massive")

    assert affected == 0
    assert session.statements == []
    assert session.commits == 0
