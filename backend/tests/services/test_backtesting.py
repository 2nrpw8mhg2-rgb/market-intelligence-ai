from datetime import date

import pytest

from app.schemas.backtesting import BacktestRequest, UniverseMode
from app.services.backtesting import BacktestService


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
