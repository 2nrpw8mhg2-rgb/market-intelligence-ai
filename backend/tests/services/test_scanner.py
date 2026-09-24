from datetime import UTC, date, datetime, timedelta

import pytest

from app.schemas.market_data import MarketBar
from app.schemas.scanner import ScanMode, ScanRequest
from app.services.scanner import ScannerService


class Universe:
    async def members(self, as_of): return ["PASS", "SHORT"]


class Calendar:
    def is_trading_day(self, value): return value.weekday() < 5
    def previous_trading_day(self, value): return value - timedelta(days=1)
    def latest_complete_session(self, now, delay_minutes=0): return date(2024, 8, 7)


def history(ticker, count=220):
    start = date(2024, 1, 1)
    bars = []
    for i in range(count):
        close = 100 + i
        volume = 100_000
        if i == count - 1:
            close += 15
            volume = 300_000
        bars.append(MarketBar(
            ticker=ticker, timestamp=datetime.combine(start + timedelta(days=i), datetime.min.time(), tzinfo=UTC),
            open=close - 1, high=close + 1, low=close - 2, close=close, volume=volume,
        ))
    return bars


class Bars:
    async def list_daily_bars(self, ticker, start_date=None, end_date=None, provider=None):
        values = history(ticker, 220 if ticker == "PASS" else 50)
        return [bar for bar in values if end_date is None or bar.timestamp.date() <= end_date]


class Opportunities:
    def __init__(self): self.values = []
    async def upsert(self, values, configuration): self.values = values


@pytest.mark.asyncio
async def test_scanner_processes_multiple_symbols_and_skips_short_history() -> None:
    store = Opportunities()
    target = history("PASS")[-1].timestamp.date()
    service = ScannerService(
        universe=Universe(), bars=Bars(), opportunities=store, calendar=Calendar(),
        now=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )
    response = await service.scan(ScanRequest(mode=ScanMode.HISTORICAL, as_of_date=target))
    assert response.status == "COMPLETED"
    assert response.summary.symbols_requested == 2
    assert response.summary.exclusions["SHORT"] == "INSUFFICIENT_HISTORY"
    assert [item.ticker for item in response.opportunities] == ["PASS"]
    assert store.values == response.opportunities


@pytest.mark.asyncio
async def test_unavailable_historical_universe_is_explicit() -> None:
    class EmptyUniverse:
        async def members(self, as_of): return []
    response = await ScannerService(
        universe=EmptyUniverse(), bars=Bars(), opportunities=Opportunities(), calendar=Calendar()
    ).scan(ScanRequest(mode=ScanMode.HISTORICAL, as_of_date=date(2020, 1, 2)))
    assert response.status == "UNIVERSE_DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_latest_uses_current_snapshot_and_completed_session() -> None:
    class CurrentUniverse:
        called = False
        async def current_members(self):
            self.called = True
            return []
        async def members(self, as_of):
            raise AssertionError("LATEST must not query historical membership")

    universe = CurrentUniverse()
    response = await ScannerService(
        universe=universe, bars=Bars(), opportunities=Opportunities(), calendar=Calendar(),
        now=lambda: datetime(2024, 8, 8, 12, tzinfo=UTC), provider_delay_minutes=45,
    ).scan(ScanRequest(mode=ScanMode.LATEST))
    assert universe.called
    assert response.as_of_date == date(2024, 8, 7)
    assert response.status == "UNIVERSE_DATA_UNAVAILABLE"
