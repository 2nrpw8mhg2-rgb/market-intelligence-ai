from collections import defaultdict
from datetime import date
from typing import Any

from app.backtesting import BacktestEngine, canonical_config
from app.database.repositories import BacktestRepository, MarketBarStore, UniverseRepository
from app.market_data.calendar import NYSETradingCalendar
from app.schemas.backtesting import (
    FIXED_UNIVERSE_WARNING, BacktestRequest, BacktestRunResult, UniverseMode,
)


class BacktestService:
    def __init__(
        self, *, bars: MarketBarStore, universes: UniverseRepository,
        runs: BacktestRepository, calendar: NYSETradingCalendar | None = None,
    ) -> None:
        self.bars = bars
        self.universes = universes
        self.runs = runs
        self.calendar = calendar or NYSETradingCalendar()

    async def execute(self, request: BacktestRequest, *, dry_run: bool = False) -> BacktestRunResult | dict[str, Any]:
        symbols, membership_records = await self._resolve_universe(request)
        warmup_start = self.calendar.session_offset(request.start_date, -260)
        forward_end = self.calendar.session_offset(request.end_date, 60)
        bars_by_ticker = {
            ticker: await self.bars.list_daily_bars(
                ticker, warmup_start, forward_end, provider=request.provider
            ) for ticker in symbols
        }
        benchmark_bars = await self.bars.list_daily_bars(
            request.benchmark, warmup_start, forward_end, provider=request.provider
        )
        _, config_hash = canonical_config(request)
        coverage = {
            "config_hash": config_hash, "universe_mode": request.universe_mode,
            "warning": FIXED_UNIVERSE_WARNING if request.universe_mode is UniverseMode.FIXED_UNIVERSE_RESEARCH else None,
            "symbols": len(symbols),
            "symbols_with_200_bars": sum(len(items) >= 200 for items in bars_by_ticker.values()),
            "symbols_without_200_bars": sorted(ticker for ticker, items in bars_by_ticker.items() if len(items) < 200),
            "benchmark_bars": len(benchmark_bars), "start_date": request.start_date,
            "end_date": request.end_date,
        }
        if dry_run:
            return {"status": "DRY_RUN", **coverage}
        if request.universe_mode is UniverseMode.POINT_IN_TIME and not membership_records:
            coverage["status"] = "DATA_UNAVAILABLE"
            coverage["message"] = "No documented historical memberships are available; current snapshot was not substituted."
            return coverage

        periods: dict[str, list[tuple[date, date | None]]] = defaultdict(list)
        for record in membership_records:
            periods[record.ticker].append((record.valid_from, record.valid_to))

        def is_member(ticker: str, session: date) -> bool:
            return any(start <= session and (end is None or end >= session)
                       for start, end in periods.get(ticker, []))

        result = BacktestEngine(self.calendar).run(
            request, bars_by_ticker, benchmark_bars,
            is_member if request.universe_mode is UniverseMode.POINT_IN_TIME else None,
        )
        config, _ = canonical_config(request)
        await self.runs.save(result, config)
        return result

    async def _resolve_universe(self, request: BacktestRequest):
        requested = (
            sorted({ticker.strip().upper() for ticker in request.tickers})
            if request.tickers else None
        )
        if request.universe_mode is UniverseMode.POINT_IN_TIME:
            records = await self.universes.list_period_memberships(
                request.universe_identifier, request.start_date, request.end_date
            )
            if requested is not None:
                requested_set = set(requested)
                records = [record for record in records if record.ticker in requested_set]
                return requested, records
            return sorted({record.ticker for record in records}), records
        if requested is not None:
            symbols = requested
        else:
            symbols = await self.universes.list_current_members(request.universe_identifier)
        return symbols, []
