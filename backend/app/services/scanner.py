import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

import pandas as pd

from app.database.repositories import MarketBarStore
from app.features import FeatureEngine
from app.explanations import explain_breakout
from app.market_data.calendar import TradingCalendar
from app.market_data.universe import MarketUniverse
from app.ranking import BreakoutRanker
from app.schemas.scanner import (
    OpportunityResult, ScanMode, ScanRequest, ScanResponse, ScanSummary,
)
from app.strategies import BreakoutVolumeStrategy


class OpportunityStore:
    async def upsert(self, opportunities: list[OpportunityResult], configuration: dict) -> None:
        raise NotImplementedError


class ScannerService:
    def __init__(
        self, *, universe: MarketUniverse, bars: MarketBarStore,
        opportunities: OpportunityStore, calendar: TradingCalendar,
        provider: str = "massive", now: Callable[[], datetime] | None = None,
        provider_delay_minutes: int = 30,
    ) -> None:
        self._universe = universe
        self._bars = bars
        self._opportunities = opportunities
        self._calendar = calendar
        self._provider = provider
        self._now = now or (lambda: datetime.now(UTC))
        self._provider_delay_minutes = provider_delay_minutes

    async def scan(self, request: ScanRequest) -> ScanResponse:
        started = time.perf_counter()
        executed_at = self._now()
        session = self._resolve_session(request, executed_at)
        symbols = (
            await self._universe.current_members()
            if request.mode is ScanMode.LATEST
            else await self._universe.members(session)
        )
        if not symbols:
            return self._response("UNIVERSE_DATA_UNAVAILABLE", session, [], {}, 0, 0, started)
        strategy = BreakoutVolumeStrategy(request.parameters)
        config = request.model_dump(mode="json")
        config_hash = hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        results: list[OpportunityResult] = []
        exclusions: dict[str, str] = {}
        processed = failed = 0
        for ticker in symbols:
            try:
                bars = await self._bars.list_daily_bars(
                    ticker, end_date=session, provider=self._provider
                )
                if len(bars) < 200:
                    exclusions[ticker] = "INSUFFICIENT_HISTORY"
                    continue
                if bars[-1].timestamp.date() != session:
                    exclusions[ticker] = "MISSING_MARKET_DATA"
                    continue
                frame = FeatureEngine().calculate(
                    pd.DataFrame([bar.model_dump() for bar in bars])
                )
                row = frame.iloc[-1].to_dict()
                if any(pd.isna(row.get(key)) for key in ("SMA_200", "PREVIOUS_HIGH_20D", "RELATIVE_VOLUME")):
                    exclusions[ticker] = "INVALID_FEATURES"
                    continue
                processed += 1
                accepted, breakout_pct = strategy.evaluate(row)
                if not accepted:
                    exclusions[ticker] = "FILTERED"
                    continue
                score = BreakoutRanker().score(
                    breakout_pct=breakout_pct, relative_volume=float(row["RELATIVE_VOLUME"]),
                    momentum_20d=float(row["MOMENTUM_20D"]), close=float(row["close"]),
                    sma_50=float(row["SMA_50"]),
                    avg_dollar_volume=float(row["AVG_DOLLAR_VOLUME_20D"]),
                    parameters=request.parameters,
                )
                results.append(OpportunityResult(
                    ticker=ticker, as_of_date=session, strategy=strategy.name,
                    strategy_version=strategy.version, universe=request.universe,
                    price=float(row["close"]), previous_high_20d=float(row["PREVIOUS_HIGH_20D"]),
                    breakout_pct=breakout_pct * 100, relative_volume=float(row["RELATIVE_VOLUME"]),
                    current_volume=float(row["volume"]),
                    average_volume_20d=float(row["AVG_VOLUME_20D"]),
                    rsi_14=float(row["RSI_14"]), sma_50=float(row["SMA_50"]),
                    sma_200=float(row["SMA_200"]), atr_14=float(row["ATR_14"]),
                    momentum_20d=float(row["MOMENTUM_20D"]),
                    avg_dollar_volume_20d=float(row["AVG_DOLLAR_VOLUME_20D"]),
                    score=score.score, score_components=score.components,
                    explanation=explain_breakout(
                        ticker=ticker, price=float(row["close"]),
                        previous_high=float(row["PREVIOUS_HIGH_20D"]),
                        breakout_pct=breakout_pct * 100,
                        current_volume=float(row["volume"]),
                        average_volume=float(row["AVG_VOLUME_20D"]),
                        relative_volume=float(row["RELATIVE_VOLUME"]),
                        sma_50=float(row["SMA_50"]), sma_200=float(row["SMA_200"]),
                        average_dollar_volume=float(row["AVG_DOLLAR_VOLUME_20D"]),
                        score=score.score, score_components=score.components,
                        min_relative_volume=request.parameters.min_relative_volume,
                        min_average_dollar_volume=request.parameters.min_avg_dollar_volume,
                    ),
                    configuration_hash=config_hash, data_provider=self._provider,
                    executed_at=executed_at,
                ))
            except Exception:
                failed += 1
                exclusions[ticker] = "PROCESSING_ERROR"
        results.sort(key=lambda item: (-item.score, item.ticker))
        await self._opportunities.upsert(results, config)
        return self._response("COMPLETED", session, results, exclusions, processed, failed, started, len(symbols))

    def _resolve_session(self, request: ScanRequest, now: datetime) -> date:
        if request.mode is ScanMode.HISTORICAL:
            assert request.as_of_date is not None
            if request.as_of_date >= now.date():
                return self._calendar.previous_trading_day(now.date())
            return request.as_of_date if self._calendar.is_trading_day(request.as_of_date) else self._calendar.previous_trading_day(request.as_of_date)
        return self._calendar.latest_complete_session(now, self._provider_delay_minutes)

    def _response(self, status, session, results, exclusions, processed, failed, started, requested=0):
        return ScanResponse(
            status=status, as_of_date=session, opportunities=results,
            summary=ScanSummary(
                symbols_requested=requested, symbols_processed=processed,
                symbols_skipped=max(0, requested - processed - failed), symbols_failed=failed,
                opportunities_found=len(results), execution_duration=round(time.perf_counter() - started, 6),
                exclusions=exclusions,
            ),
        )
