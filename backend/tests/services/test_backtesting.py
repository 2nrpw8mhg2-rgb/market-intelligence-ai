from datetime import date
from types import SimpleNamespace
import uuid

import pytest

from app.schemas.backtesting import BacktestRequest, UniverseMode
from app.services.backtesting import BacktestService, membership_is_active
from app.database.repositories import PITIdentityResolutionError


class Bars:
    async def list_daily_bars(self, *args, **kwargs): return []


class Universes:
    historical_called = False
    current_called = False
    async def list_period_memberships(self, *args):
        self.historical_called = True
        return []
    async def list_current_members(self, *args):
        self.current_called = True
        return ["AAPL"]


class Runs:
    async def save(self, *args): raise AssertionError("unavailable PIT run must not persist")


def test_point_in_time_membership_exit_is_exclusive() -> None:
    periods = [(date(2020, 1, 1), date(2024, 1, 3))]
    assert membership_is_active(periods, date(2024, 1, 2))
    assert not membership_is_active(periods, date(2024, 1, 3))


@pytest.mark.asyncio
async def test_point_in_time_never_substitutes_current_snapshot() -> None:
    universes = Universes()
    result = await BacktestService(
        bars=Bars(), universes=universes, runs=Runs()
    ).execute(BacktestRequest(
        universe_mode=UniverseMode.POINT_IN_TIME,
        start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
    ))
    assert result["status"] == "DATA_UNAVAILABLE"
    assert universes.historical_called
    assert not universes.current_called


@pytest.mark.asyncio
async def test_fixed_universe_dry_run_has_explicit_warning() -> None:
    universes = Universes()
    result = await BacktestService(
        bars=Bars(), universes=universes, runs=Runs()
    ).execute(BacktestRequest(
        universe_mode=UniverseMode.FIXED_UNIVERSE_RESEARCH,
        start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
    ), dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert "survivorship bias" in result["warning"]
    assert universes.current_called


class TickerOnlyUniverses(Universes):
    async def list_period_memberships(self, *args):
        return [SimpleNamespace(ticker="ABC", valid_from=date(2020, 1, 1), valid_to=None)]


class ReusedTickerUniverses(Universes):
    async def list_period_memberships(self, *args):
        return [
            SimpleNamespace(ticker="ABC", security_id=uuid.UUID(int=1), eligibility_status="ELIGIBLE",
                            valid_from=date(2010, 1, 1), valid_to=date(2015, 1, 1)),
            SimpleNamespace(ticker="ABC", security_id=uuid.UUID(int=2), eligibility_status="ELIGIBLE",
                            valid_from=date(2020, 1, 1), valid_to=None),
        ]


@pytest.mark.asyncio
async def test_pit_backtest_rejects_ticker_only_membership() -> None:
    with pytest.raises(PITIdentityResolutionError, match="ticker-only"):
        await BacktestService(bars=Bars(), universes=TickerOnlyUniverses(), runs=Runs()).execute(
            BacktestRequest(universe_mode=UniverseMode.POINT_IN_TIME,
                            start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)), dry_run=True)


@pytest.mark.asyncio
async def test_pit_backtest_rejects_ticker_reuse_collapse() -> None:
    with pytest.raises(PITIdentityResolutionError, match="ticker reuse"):
        await BacktestService(bars=Bars(), universes=ReusedTickerUniverses(), runs=Runs()).execute(
            BacktestRequest(universe_mode=UniverseMode.POINT_IN_TIME,
                            start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)), dry_run=True)
