import hashlib
import json
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.engine import aggregate_by_horizon
from app.market_data.calendar import NYSETradingCalendar
from app.schemas.backtesting import BacktestEventResult, BacktestRunResult
from app.schemas.market_data import MarketBar
from app.schemas.research import (
    DependencyMode, MarketRegimeRequest, RESEARCH_HORIZONS, ResearchResult,
    ScoreResearchRequest,
)


def research_identity(kind: str, request: Any) -> tuple[dict[str, Any], str, str]:
    config = {"research_type": kind, **request.model_dump(mode="json")}
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return config, digest, str(uuid.uuid5(uuid.NAMESPACE_URL, digest))


def _horizon_stats(events: list[BacktestEventResult]) -> dict[str, Any]:
    all_stats = aggregate_by_horizon(events)
    return {str(h): all_stats[str(h)] for h in RESEARCH_HORIZONS}


def _bucket(score: float, boundaries: tuple[float, ...]) -> str:
    for low, high in zip(boundaries, boundaries[1:]):
        if low <= score < high or (high == boundaries[-1] and score == high):
            return f"{low:g}-{high:g}"
    raise ValueError(f"score outside configured buckets: {score}")


def dependency_filter(events: list[BacktestEventResult], cooldown: int, calendar: NYSETradingCalendar) -> list[BacktestEventResult]:
    """Keep a signal when it is at least `cooldown` XNYS sessions after the last kept signal.

    The boundary session is allowed: with cooldown=20, a signal exactly 20 sessions later is kept.
    """
    kept: list[BacktestEventResult] = []
    last: dict[str, date] = {}
    for event in sorted(events, key=lambda item: (item.signal_date, item.ticker)):
        previous = last.get(event.ticker)
        if previous is not None and event.signal_date < calendar.session_offset(previous, cooldown):
            continue
        kept.append(event)
        last[event.ticker] = event.signal_date
    return kept


class ScoreResearchEngine:
    COMPONENTS = {
        "breakout_strength": "breakout_pct",
        "relative_volume": "relative_volume",
        "momentum": "momentum_20d",
        "distance_sma50": "distance_from_sma50",
        "liquidity": "avg_dollar_volume_20d",
    }

    def __init__(self, calendar: NYSETradingCalendar | None = None) -> None:
        self.calendar = calendar or NYSETradingCalendar()

    def run(self, request: ScoreResearchRequest, source: BacktestRunResult, *, created_at: datetime | None = None) -> ResearchResult:
        _, digest, run_id = research_identity("SCORE_RESEARCH", request)
        events = source.events
        buckets: dict[str, list[BacktestEventResult]] = defaultdict(list)
        for event in events:
            buckets[_bucket(event.score, request.score_buckets)].append(event)
        by_bucket = {}
        for low, high in zip(request.score_buckets, request.score_buckets[1:]):
            name = f"{low:g}-{high:g}"
            by_bucket[name] = _horizon_stats(buckets[name])
        by_year_bucket: dict[str, Any] = {}
        for year in sorted({event.signal_date.year for event in events}):
            by_year_bucket[str(year)] = {}
            yearly = [event for event in events if event.signal_date.year == year]
            for low, high in zip(request.score_buckets, request.score_buckets[1:]):
                name = f"{low:g}-{high:g}"
                selected = [event for event in yearly if _bucket(event.score, request.score_buckets) == name]
                by_year_bucket[str(year)][name] = {
                    "low_sample_warning": len(selected) < 30,
                    **_horizon_stats(selected),
                }

        component_results: dict[str, Any] = {}
        for name, field in self.COMPONENTS.items():
            component_results[name] = self._component(events, field)

        dependency: dict[str, Any] = {}
        variants = {
            DependencyMode.ALL_EVENTS.value: events,
            DependencyMode.FIRST_SIGNAL_ONLY_20D.value: dependency_filter(events, 20, self.calendar),
            DependencyMode.FIRST_SIGNAL_ONLY_60D.value: dependency_filter(events, 60, self.calendar),
        }
        for name, selected in variants.items():
            dependency[name] = {"event_count": len(selected), "statistics": _horizon_stats(selected)}
        dates = Counter(event.signal_date.isoformat() for event in events)
        symbol_groups: dict[str, list[BacktestEventResult]] = defaultdict(list)
        for event in events:
            symbol_groups[event.ticker].append(event)
        dependency["diagnostics"] = {
            "same_day_signal_dates": sum(count > 1 for count in dates.values()),
            "maximum_signals_same_day": max(dates.values(), default=0),
            "symbols_with_repeated_signals": sum(len(values) > 1 for values in symbol_groups.values()),
            "same_symbol_within_20_sessions": self._nearby_count(symbol_groups, 20),
            "same_symbol_within_60_sessions": self._nearby_count(symbol_groups, 60),
            "consecutive_same_symbol_signals": self._nearby_count(symbol_groups, 1),
            "sector_concentration": "UNAVAILABLE_NO_VALID_SECTOR_METADATA",
        }
        return ResearchResult(
            run_id=run_id, config_hash=digest, research_type="SCORE_RESEARCH",
            source_backtest_run_id=source.run_id, event_count=len(events),
            strategy_version=source.strategy_version, universe_mode=source.universe_mode.value,
            start_date=source.start_date, end_date=source.end_date,
            results={"score_buckets": by_bucket, "score_buckets_by_year": by_year_bucket,
                     "components": component_results, "dependency": dependency,
                     "confidence_interval_method": "normal approximation: mean ± 1.96 * sample_std / sqrt(n)",
                     "independence_warning": "Overlapping events are not treated as statistically independent."},
            created_at=created_at or datetime.now(UTC),
        )

    def _nearby_count(self, groups: dict[str, list[BacktestEventResult]], sessions: int) -> int:
        count = 0
        for values in groups.values():
            ordered = sorted(values, key=lambda item: item.signal_date)
            for previous, current in zip(ordered, ordered[1:]):
                if current.signal_date <= self.calendar.session_offset(previous.signal_date, sessions):
                    count += 1
        return count

    @staticmethod
    def _component(events: list[BacktestEventResult], field: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for horizon in RESEARCH_HORIZONS:
            rows = []
            for event in events:
                outcome = next(item for item in event.outcomes if item.horizon == horizon)
                if outcome.stock_return is not None:
                    rows.append((float(getattr(event, field)), outcome.stock_return, event.signal_date.year))
            values = np.array([row[0] for row in rows], dtype=float)
            returns = np.array([row[1] for row in rows], dtype=float)
            if len(rows) < 3:
                result[str(horizon)] = {"sample_size": len(rows), "status": "INSUFFICIENT_SAMPLE"}
                continue
            ranks_v = pd.Series(values).rank(method="average").to_numpy()
            ranks_r = pd.Series(returns).rank(method="average").to_numpy()
            quantile_edges = np.quantile(values, [0, .2, .4, .6, .8, 1])
            quantiles = {}
            for index in range(5):
                mask = (values >= quantile_edges[index]) & ((values <= quantile_edges[index + 1]) if index == 4 else (values < quantile_edges[index + 1]))
                subset = returns[mask]
                quantiles[f"Q{index + 1}"] = {"n": int(mask.sum()), "mean_return": float(np.mean(subset)) if len(subset) else None,
                                                   "median_return": float(np.median(subset)) if len(subset) else None}
            yearly = {}
            for year in sorted({row[2] for row in rows}):
                mask = np.array([row[2] == year for row in rows])
                yearly_values, yearly_returns = values[mask], returns[mask]
                yearly[str(year)] = {
                    "n": int(mask.sum()), "pearson": ScoreResearchEngine._corr(yearly_values, yearly_returns),
                    "spearman": ScoreResearchEngine._corr(
                        pd.Series(yearly_values).rank(method="average").to_numpy(),
                        pd.Series(yearly_returns).rank(method="average").to_numpy(),
                    ),
                }
            result[str(horizon)] = {"sample_size": len(rows), "pearson": ScoreResearchEngine._corr(values, returns),
                                    "spearman": ScoreResearchEngine._corr(ranks_v, ranks_r),
                                    "quantile_method": "retrospective full-sample quintiles", "quantiles": quantiles,
                                    "by_year": yearly}
        return result

    @staticmethod
    def _corr(left: np.ndarray, right: np.ndarray) -> float | None:
        return float(np.corrcoef(left, right)[0, 1]) if len(left) > 2 and np.std(left) and np.std(right) else None


class MarketRegimeEngine:
    def run(self, request: MarketRegimeRequest, source: BacktestRunResult, benchmark: list[MarketBar], *, created_at: datetime | None = None) -> ResearchResult:
        _, digest, run_id = research_identity("MARKET_REGIME_RESEARCH", request)
        frame = pd.DataFrame([bar.model_dump() for bar in benchmark]).sort_values("timestamp")
        if frame.empty:
            observations = {}
        else:
            frame["session"] = pd.to_datetime(frame["timestamp"], utc=True).dt.date
            close = frame["close"].astype(float)
            frame["sma50"] = close.rolling(50, min_periods=50).mean()
            frame["sma200"] = close.rolling(200, min_periods=200).mean()
            frame["realized_vol"] = close.pct_change(fill_method=None).rolling(request.volatility_window, min_periods=request.volatility_window).std(ddof=1) * np.sqrt(252)
            observations = {row["session"]: row for _, row in frame.iterrows()}
        # Volatility thresholds are advanced once per benchmark session, never once
        # per event.  This keeps same-day classifications identical and causal.
        prior_vols: list[float] = []
        volatility_by_session: dict[date, str] = {}
        for session, row in sorted(observations.items()):
            vol_value = None if pd.isna(row["realized_vol"]) else float(row["realized_vol"])
            if vol_value is None or len(prior_vols) < request.volatility_min_history:
                volatility_by_session[session] = "REGIME_UNAVAILABLE"
            else:
                low, high = np.quantile(prior_vols, [1 / 3, 2 / 3])
                volatility_by_session[session] = (
                    "VOL_LOW" if vol_value <= low else ("VOL_HIGH" if vol_value > high else "VOL_MID")
                )
            if vol_value is not None:
                prior_vols.append(vol_value)

        classified: dict[str, list[BacktestEventResult]] = defaultdict(list)
        rows = []
        for event in sorted(source.events, key=lambda item: (item.signal_date, item.ticker)):
            row = observations.get(event.signal_date)
            if row is None or pd.isna(row["sma200"]):
                sma200 = "REGIME_UNAVAILABLE"
                sma50 = "REGIME_UNAVAILABLE"
                configuration = "REGIME_UNAVAILABLE"
                volatility = "REGIME_UNAVAILABLE"
                vol_value = None
            else:
                sma200 = "SPY_ABOVE_SMA200" if row["close"] > row["sma200"] else "SPY_BELOW_SMA200"
                sma50 = "SPY_ABOVE_SMA50" if row["close"] > row["sma50"] else "SPY_BELOW_SMA50"
                if row["close"] > row["sma50"] > row["sma200"]:
                    configuration = "SPY_GT_SMA50_GT_SMA200"
                elif row["close"] < row["sma50"] < row["sma200"]:
                    configuration = "SPY_LT_SMA50_LT_SMA200"
                else:
                    configuration = "OTHER_CONFIGURATION"
                vol_value = None if pd.isna(row["realized_vol"]) else float(row["realized_vol"])
                volatility = volatility_by_session[event.signal_date]
            for label in set((sma200, sma50, configuration, volatility)):
                classified[label].append(event)
            rows.append({"ticker": event.ticker, "signal_date": event.signal_date.isoformat(),
                         "sma200_regime": sma200, "sma50_regime": sma50,
                         "configuration": configuration, "volatility_regime": volatility,
                         "realized_volatility": vol_value})
        regime_stats = {name: _horizon_stats(values) for name, values in sorted(classified.items())}
        cross: dict[str, Any] = {}
        for regime, values in classified.items():
            if not regime.startswith(("SPY_ABOVE_SMA200", "SPY_BELOW_SMA200")):
                continue
            cross[regime] = {}
            for low, high in zip((0, 20, 40, 60, 80), (20, 40, 60, 80, 100)):
                selected = [event for event in values if low <= event.score < high or (high == 100 and event.score == high)]
                cross[regime][f"{low}-{high}"] = _horizon_stats(selected)
        return ResearchResult(
            run_id=run_id, config_hash=digest, research_type="MARKET_REGIME_RESEARCH",
            source_backtest_run_id=source.run_id, event_count=len(source.events),
            strategy_version=source.strategy_version, universe_mode=source.universe_mode.value,
            start_date=source.start_date, end_date=source.end_date,
            results={"regimes": regime_stats, "score_by_sma200_regime": cross,
                     "observations": rows,
                     "volatility_method": "20-session annualized realized volatility; expanding terciles use only prior observations"},
            created_at=created_at or datetime.now(UTC),
        )
