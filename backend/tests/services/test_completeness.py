from datetime import UTC, date, datetime

import pytest

from app.market_data.base import MarketDataProvider
from app.schemas.market_data import MarketBar
from app.services.market_data import MarketDataService, MarketSessionError

SESSIONS = [date(2024, 7, 1), date(2024, 7, 2), date(2024, 7, 3), date(2024, 7, 5)]


def bar(value: date) -> MarketBar:
    return MarketBar(
        ticker="AAPL",
        timestamp=datetime.combine(value, datetime.min.time(), tzinfo=UTC),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=100,
    )


class Calendar:
    name = "TEST"

    def is_trading_day(self, value):
        return value in SESSIONS

    def trading_days_between(self, start_date, end_date):
        return [value for value in SESSIONS if start_date <= value <= end_date]

    def previous_trading_day(self, value):
        raise NotImplementedError

    def next_trading_day(self, value):
        raise NotImplementedError


class Store:
    def __init__(self, values):
        self.values = {value.timestamp.date(): value for value in values}

    async def list_daily_bars(self, ticker, start_date=None, end_date=None, provider=None):
        return [
            value
            for day, value in sorted(self.values.items())
            if (start_date is None or day >= start_date)
            and (end_date is None or day <= end_date)
        ]

    async def upsert_daily_bars(self, bars, *, provider):
        self.values.update({value.timestamp.date(): value for value in bars})
        return len(bars)


class Provider(MarketDataProvider):
    name = "fake"

    def __init__(self):
        self.calls = []

    async def get_daily_bars(self, ticker, start_date, end_date):
        self.calls.append((start_date, end_date))
        return [bar(value) for value in SESSIONS if start_date <= value <= end_date]


def test_completeness_ignores_holidays_but_detects_missing_sessions() -> None:
    service = MarketDataService(Provider(), Store([]), Calendar())
    report = service.assess_daily_completeness(
        [bar(date(2024, 7, 1)), bar(date(2024, 7, 3))],
        date(2024, 7, 1),
        date(2024, 7, 5),
    )

    assert report.missing_sessions == (date(2024, 7, 2), date(2024, 7, 5))
    assert date(2024, 7, 4) not in report.missing_sessions
    assert not report.is_complete


@pytest.mark.asyncio
async def test_only_missing_session_ranges_are_requested() -> None:
    provider = Provider()
    store = Store([bar(date(2024, 7, 1)), bar(date(2024, 7, 5))])
    service = MarketDataService(provider, store, Calendar())

    values = await service.get_or_ingest_daily_bars(
        "AAPL", date(2024, 7, 1), date(2024, 7, 5)
    )

    assert provider.calls == [(date(2024, 7, 2), date(2024, 7, 3))]
    assert [value.timestamp.date() for value in values] == SESSIONS


@pytest.mark.asyncio
async def test_non_session_provider_bar_is_rejected() -> None:
    class BadProvider(Provider):
        async def get_daily_bars(self, ticker, start_date, end_date):
            return [bar(date(2024, 7, 4))]

    service = MarketDataService(BadProvider(), Store([]), Calendar())
    with pytest.raises(MarketSessionError, match="non-trading sessions"):
        await service.get_or_ingest_daily_bars(
            "AAPL", date(2024, 7, 1), date(2024, 7, 5)
        )


@pytest.mark.asyncio
async def test_non_session_stored_bar_is_rejected() -> None:
    service = MarketDataService(Provider(), Store([bar(date(2024, 7, 4))]), Calendar())
    with pytest.raises(MarketSessionError, match="stored daily bars"):
        await service.get_or_ingest_daily_bars(
            "AAPL", date(2024, 7, 1), date(2024, 7, 5)
        )
