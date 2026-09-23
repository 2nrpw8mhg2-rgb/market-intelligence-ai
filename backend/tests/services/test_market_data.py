from datetime import UTC, date, datetime

import pytest

from app.market_data.base import MarketDataProvider
from app.schemas.market_data import MarketBar
from app.services.market_data import MarketDataService


def bar(day: int, ticker: str = "AAPL") -> MarketBar:
    return MarketBar(
        ticker=ticker,
        timestamp=datetime(2024, 1, day, tzinfo=UTC),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=100,
    )


class FakeProvider(MarketDataProvider):
    name = "fake"

    def __init__(self, bars: list[MarketBar]) -> None:
        self.bars = bars
        self.calls = 0

    async def get_daily_bars(self, ticker, start_date, end_date):
        self.calls += 1
        return self.bars


class FakeCalendar:
    name = "TEST"

    def is_trading_day(self, value):
        return value in {date(2024, 1, 1), date(2024, 1, 2)}

    def previous_trading_day(self, value):
        raise NotImplementedError

    def next_trading_day(self, value):
        raise NotImplementedError

    def trading_days_between(self, start_date, end_date):
        return [
            value
            for value in (date(2024, 1, 1), date(2024, 1, 2))
            if start_date <= value <= end_date
        ]


class InMemoryStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, object, str], MarketBar] = {}

    async def list_daily_bars(self, ticker, start_date=None, end_date=None, provider=None):
        values = [
            value
            for (stored_provider, _, _), value in self.values.items()
            if stored_provider == provider and value.ticker == ticker
        ]
        return sorted(values, key=lambda value: value.timestamp)

    async def upsert_daily_bars(self, bars, *, provider):
        for value in bars:
            self.values[(provider, value.timestamp, "1d")] = value
        return len(bars)


@pytest.mark.asyncio
async def test_ingestion_is_idempotent_and_avoids_second_provider_call() -> None:
    provider = FakeProvider([bar(1), bar(2)])
    store = InMemoryStore()
    service = MarketDataService(provider, store, FakeCalendar())

    first = await service.get_or_ingest_daily_bars("aapl", date(2024, 1, 1), date(2024, 1, 2))
    second = await service.get_or_ingest_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))

    assert first == second
    assert provider.calls == 1
    assert len(store.values) == 2


@pytest.mark.asyncio
async def test_provider_duplicates_are_rejected() -> None:
    service = MarketDataService(
        FakeProvider([bar(1), bar(1)]), InMemoryStore(), FakeCalendar()
    )

    with pytest.raises(ValueError, match="duplicate timestamps"):
        await service.get_or_ingest_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))


@pytest.mark.asyncio
async def test_provider_out_of_order_data_is_rejected() -> None:
    service = MarketDataService(
        FakeProvider([bar(2), bar(1)]), InMemoryStore(), FakeCalendar()
    )

    with pytest.raises(ValueError, match="chronological order"):
        await service.get_or_ingest_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))


@pytest.mark.asyncio
async def test_provider_cannot_return_different_ticker() -> None:
    service = MarketDataService(
        FakeProvider([bar(1, ticker="MSFT")]), InMemoryStore(), FakeCalendar()
    )

    with pytest.raises(ValueError, match="unexpected ticker"):
        await service.get_or_ingest_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))
