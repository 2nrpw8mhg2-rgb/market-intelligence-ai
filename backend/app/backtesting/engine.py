import hashlib
import json
import math
import statistics
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.features import FeatureEngine
from app.market_data.calendar import NYSETradingCalendar
from app.ranking import BreakoutRanker
from app.schemas.backtesting import (
    FIXED_UNIVERSE_WARNING, HORIZONS, BacktestEventResult, BacktestRequest,
    BacktestRunResult, EntryModel, ForwardOutcome, UniverseMode,
)
from app.schemas.market_data import MarketBar
from app.strategies import BreakoutVolumeStrategy


def canonical_config(request: BacktestRequest) -> tuple[dict[str, Any], str]:
    config = request.model_dump(mode="json")
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(encoded).hexdigest()


class BacktestEngine:
    """Causal event study. Signal detection is completed before forward data is read."""

    def __init__(self, calendar: NYSETradingCalendar | None = None) -> None:
        self.calendar = calendar or NYSETradingCalendar()

    def run(
        self, request: BacktestRequest, bars_by_ticker: dict[str, list[MarketBar]],
        benchmark_bars: list[MarketBar],
        is_member: Callable[[str, date], bool] | None = None,
        *, created_at: datetime | None = None,
    ) -> BacktestRunResult:
        _, config_hash = canonical_config(request)
        strategy = BreakoutVolumeStrategy(request.parameters)
        ranker = BreakoutRanker()
        events: list[BacktestEventResult] = []
        warnings: list[str] = []
        benchmark_map = {bar.timestamp.date(): bar for bar in benchmark_bars}
        if not benchmark_bars:
            warnings.append(f"Benchmark data unavailable for {request.benchmark}")

        for ticker in sorted(bars_by_ticker):
            bars = bars_by_ticker[ticker]
            if len(bars) < 200:
                warnings.append(f"{ticker}: insufficient history ({len(bars)} bars)")
                continue
            frame = FeatureEngine().calculate(
                pd.DataFrame([bar.model_dump() for bar in bars])
            )
            bar_map = {bar.timestamp.date(): bar for bar in bars}
            for _, series in frame.iterrows():
                signal_date = series["timestamp"].date()
                if not request.start_date <= signal_date <= request.end_date:
                    continue
                if request.universe_mode is UniverseMode.POINT_IN_TIME:
                    if is_member is None or not is_member(ticker, signal_date):
                        continue
                row = series.to_dict()
                required = ("SMA_200", "PREVIOUS_HIGH_20D", "RELATIVE_VOLUME", "MOMENTUM_20D")
                if any(pd.isna(row.get(key)) for key in required):
                    continue
                accepted, breakout_fraction = strategy.evaluate(row)
                if not accepted:
                    continue
                score = ranker.score(
                    breakout_pct=breakout_fraction,
                    relative_volume=float(row["RELATIVE_VOLUME"]),
                    momentum_20d=float(row["MOMENTUM_20D"]),
                    close=float(row["close"]), sma_50=float(row["SMA_50"]),
                    avg_dollar_volume=float(row["AVG_DOLLAR_VOLUME_20D"]),
                    parameters=request.parameters,
                )
                entry_date, entry_price = self._entry(request.entry_model, signal_date, bar_map)
                outcomes = [
                    self._outcome(
                        request.entry_model, signal_date, horizon, bar_map,
                        benchmark_map, float(row["close"]), entry_date, entry_price,
                    )
                    for horizon in HORIZONS
                ]
                events.append(BacktestEventResult(
                    ticker=ticker, signal_date=signal_date,
                    strategy=strategy.name, strategy_version=strategy.version,
                    universe_mode=request.universe_mode,
                    universe_identifier=request.universe_identifier,
                    close=float(row["close"]),
                    previous_high_20d=float(row["PREVIOUS_HIGH_20D"]),
                    breakout_pct=breakout_fraction * 100,
                    relative_volume=float(row["RELATIVE_VOLUME"]),
                    sma_50=float(row["SMA_50"]), sma_200=float(row["SMA_200"]),
                    momentum_20d=float(row["MOMENTUM_20D"]),
                    avg_dollar_volume_20d=float(row["AVG_DOLLAR_VOLUME_20D"]),
                    distance_from_sma50=float(row["close"] / row["SMA_50"] - 1),
                    score=score.score, score_components=score.components,
                    entry_model=request.entry_model, entry_date=entry_date,
                    entry_price=entry_price, outcomes=outcomes,
                ))

        events.sort(key=lambda event: (event.signal_date, event.ticker))
        statistics_by_horizon = aggregate_by_horizon(events)
        return BacktestRunResult(
            run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, config_hash)), status="COMPLETED",
            config_hash=config_hash, strategy=strategy.name,
            strategy_version=strategy.version, universe_mode=request.universe_mode,
            universe_identifier=request.universe_identifier,
            survivorship_bias_warning=(FIXED_UNIVERSE_WARNING if request.universe_mode is UniverseMode.FIXED_UNIVERSE_RESEARCH else None),
            start_date=request.start_date, end_date=request.end_date,
            entry_model=request.entry_model, benchmark=request.benchmark,
            event_count=len(events),
            data_coverage={"symbols_requested": len(bars_by_ticker),
                           "symbols_with_200_bars": sum(len(value) >= 200 for value in bars_by_ticker.values()),
                           "benchmark_bars": len(benchmark_bars)},
            statistics_by_horizon=statistics_by_horizon,
            statistics_by_score_bucket=aggregate_by_score(events, request.score_buckets),
            statistics_by_year=aggregate_by_period(events, "year"),
            statistics_by_quarter=aggregate_by_period(events, "quarter"),
            statistics_by_characteristic=aggregate_by_characteristic(events),
            events=events, data_quality_warnings=warnings,
            created_at=created_at or datetime.now(UTC),
        )

    def _entry(self, model: EntryModel, signal_date: date, bars: dict[date, MarketBar]) -> tuple[date | None, float | None]:
        if model is EntryModel.SIGNAL_CLOSE:
            bar = bars.get(signal_date)
            return (signal_date, bar.close) if bar else (None, None)
        entry_date = self.calendar.session_offset(signal_date, 1)
        bar = bars.get(entry_date)
        return (entry_date, bar.open) if bar else (None, None)

    def _outcome(
        self, model: EntryModel, signal_date: date, horizon: int,
        bars: dict[date, MarketBar], benchmark: dict[date, MarketBar],
        signal_close: float, entry_date: date | None, entry_price: float | None,
    ) -> ForwardOutcome:
        target = self.calendar.session_offset(signal_date, horizon)
        first = self.calendar.session_offset(signal_date, 1)
        expected = self.calendar.trading_days_between(first, target)
        stock_complete = entry_price is not None and all(day in bars for day in expected)
        target_bar = bars.get(target)
        stock_return = (target_bar.close / entry_price - 1) if stock_complete and target_bar else None

        benchmark_complete = all(day in benchmark for day in expected)
        if model is EntryModel.SIGNAL_CLOSE:
            benchmark_base = benchmark.get(signal_date).close if benchmark.get(signal_date) else None
        else:
            benchmark_base = benchmark.get(first).open if benchmark.get(first) else None
        benchmark_target = benchmark.get(target)
        benchmark_return = (
            benchmark_target.close / benchmark_base - 1
            if benchmark_complete and benchmark_base and benchmark_target else None
        )
        excess = stock_return - benchmark_return if stock_return is not None and benchmark_return is not None else None
        mfe = mae = None
        if horizon in {5, 10, 20, 60} and stock_complete and entry_price:
            window = [bars[day] for day in expected]
            mfe = max(bar.high / entry_price - 1 for bar in window)
            mae = min(bar.low / entry_price - 1 for bar in window)
        return ForwardOutcome(
            horizon=horizon, stock_return=stock_return,
            benchmark_return=benchmark_return, excess_return=excess,
            mfe=mfe, mae=mae,
            forward_data_complete=stock_complete and benchmark_return is not None,
        )


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("mean", "median", "positive_rate", "standard_deviation", "percentile_25", "percentile_75", "best", "worst", "confidence_interval_95_low", "confidence_interval_95_high")}
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    margin = 1.96 * std / math.sqrt(len(values))
    return {"mean": mean, "median": statistics.median(values),
            "positive_rate": sum(value > 0 for value in values) / len(values),
            "standard_deviation": std, "percentile_25": float(np.percentile(values, 25)),
            "percentile_75": float(np.percentile(values, 75)), "best": max(values),
            "worst": min(values), "confidence_interval_95_low": mean - margin,
            "confidence_interval_95_high": mean + margin}


def aggregate_by_horizon(events: list[BacktestEventResult]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in HORIZONS:
        outcomes = [next(item for item in event.outcomes if item.horizon == horizon) for event in events]
        stock = [item.stock_return for item in outcomes if item.stock_return is not None]
        excess = [item.excess_return for item in outcomes if item.excess_return is not None]
        mfes = [item.mfe for item in outcomes if item.mfe is not None]
        maes = [item.mae for item in outcomes if item.mae is not None]
        result[str(horizon)] = {
            "number_of_events": len(events),
            "number_with_complete_forward_data": sum(item.forward_data_complete for item in outcomes),
            **{f"return_{key}": value for key, value in _stats(stock).items()},
            "mean_excess_return": statistics.fmean(excess) if excess else None,
            "median_excess_return": statistics.median(excess) if excess else None,
            "positive_excess_return_rate": sum(value > 0 for value in excess) / len(excess) if excess else None,
            "median_mfe": statistics.median(mfes) if mfes else None,
            "median_mae": statistics.median(maes) if maes else None,
        }
    return result


def aggregate_by_score(events: list[BacktestEventResult], buckets: tuple[float, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for low, high in zip(buckets, buckets[1:]):
        selected = [event for event in events if low <= event.score < high or (high == buckets[-1] and event.score == high)]
        result[f"{low:g}-{high:g}"] = {key: value for key, value in aggregate_by_horizon(selected).items() if int(key) in {5, 10, 20, 60}}
    return result


def aggregate_by_period(events: list[BacktestEventResult], period: str) -> dict[str, Any]:
    grouped: dict[str, list[BacktestEventResult]] = defaultdict(list)
    for event in events:
        key = str(event.signal_date.year)
        if period == "quarter":
            key = f"{event.signal_date.year}-Q{(event.signal_date.month - 1) // 3 + 1}"
        grouped[key].append(event)
    return {key: aggregate_by_horizon(values) for key, values in sorted(grouped.items())}


def aggregate_by_characteristic(events: list[BacktestEventResult]) -> dict[str, Any]:
    """Exploratory feature/return associations; omitted when sample size is too small."""
    complete = []
    for event in events:
        outcome = next(item for item in event.outcomes if item.horizon == 20)
        if outcome.stock_return is not None:
            complete.append((event, outcome.stock_return))
    if len(complete) < 3:
        return {"sample_size": len(complete), "status": "INSUFFICIENT_SAMPLE"}
    fields = ("score", "breakout_pct", "relative_volume", "momentum_20d", "distance_from_sma50")
    correlations = {}
    returns = np.array([outcome for _, outcome in complete], dtype=float)
    for field in fields:
        values = np.array([float(getattr(event, field)) for event, _ in complete], dtype=float)
        correlations[field] = (
            float(np.corrcoef(values, returns)[0, 1])
            if np.std(values) > 0 and np.std(returns) > 0 else None
        )
    return {"sample_size": len(complete), "forward_horizon": 20,
            "pearson_correlations": correlations}
