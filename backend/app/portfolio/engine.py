import hashlib
import json
import math
import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np

from app.market_data.calendar import NYSETradingCalendar
from app.schemas.backtesting import BacktestEventResult, BacktestRunResult
from app.schemas.market_data import MarketBar
from app.schemas.research import (
    PortfolioDailyResult, PortfolioSimulationRequest, PortfolioSimulationResult,
    PortfolioTradeResult, SelectionPolicy, SkippedSignalResult,
)


@dataclass
class _Position:
    event: BacktestEventResult
    quantity: float
    reference_entry: float
    entry_price: float
    entry_cost: float
    entry_commission: float
    exit_due: date
    last_price: float


def portfolio_identity(request: PortfolioSimulationRequest) -> tuple[dict[str, Any], str, str]:
    config = request.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return config, digest, str(uuid.uuid5(uuid.NAMESPACE_URL, digest))


def _max_drawdown(equity: list[float]) -> tuple[float | None, int]:
    if not equity:
        return None, 0
    peak = equity[0]
    max_dd = 0.0
    duration = longest = 0
    for value in equity:
        peak = max(peak, value)
        drawdown = value / peak - 1 if peak else 0
        if drawdown < 0:
            duration += 1
            longest = max(longest, duration)
        else:
            duration = 0
        max_dd = min(max_dd, drawdown)
    return max_dd, longest


def calculate_performance_metrics(
    daily: list[PortfolioDailyResult], trades: list[PortfolioTradeResult],
    *, initial_capital: float,
) -> dict[str, Any]:
    if not daily:
        return {"status": "NO_DATA", "number_of_trades": 0}
    returns = [item.daily_return for item in daily[1:]]
    years = max((daily[-1].session_date - daily[0].session_date).days / 365.25, 0)
    total_return = daily[-1].total_equity / initial_capital - 1
    annualized_return = (daily[-1].total_equity / initial_capital) ** (1 / years) - 1 if years >= 1 and daily[-1].total_equity > 0 else None
    volatility = statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 else None
    mean_daily = statistics.fmean(returns) if returns else None
    downside = [min(value, 0) for value in returns]
    downside_deviation = math.sqrt(statistics.fmean([value * value for value in downside])) * math.sqrt(252) if downside else None
    sharpe = mean_daily / statistics.stdev(returns) * math.sqrt(252) if len(returns) > 1 and statistics.stdev(returns) else None
    sortino = mean_daily * 252 / downside_deviation if mean_daily is not None and downside_deviation else None
    drawdown, drawdown_duration = _max_drawdown([item.total_equity for item in daily])
    calmar = annualized_return / abs(drawdown) if annualized_return is not None and drawdown else None
    trade_returns = [trade.net_return for trade in trades]
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [-trade.pnl for trade in trades if trade.pnl < 0]
    average_positions = statistics.fmean(item.open_positions for item in daily)
    average_exposure = statistics.fmean(item.gross_exposure for item in daily)
    turnover = sum(trade.quantity * (trade.reference_entry_price + trade.reference_exit_price) for trade in trades) / statistics.fmean(item.total_equity for item in daily)
    return {
        "total_return": total_return, "annualized_return_cagr": annualized_return,
        "annualized_volatility": volatility, "maximum_drawdown": drawdown,
        "maximum_drawdown_duration_sessions": drawdown_duration,
        "sharpe_ratio": sharpe, "sortino_ratio": sortino, "calmar_ratio": calmar,
        "positive_trade_rate": sum(value > 0 for value in trade_returns) / len(trade_returns) if trade_returns else None,
        "mean_trade_return": statistics.fmean(trade_returns) if trade_returns else None,
        "median_trade_return": statistics.median(trade_returns) if trade_returns else None,
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "average_holding_period": statistics.fmean(trade.holding_sessions for trade in trades) if trades else None,
        "number_of_trades": len(trades), "average_simultaneous_positions": average_positions,
        "average_gross_exposure": average_exposure,
        "time_in_market": sum(item.open_positions > 0 for item in daily) / len(daily),
        "cash_utilization": statistics.fmean(1 - item.cash / item.total_equity for item in daily if item.total_equity) if daily else None,
        "turnover": turnover, "total_commissions": sum(trade.commission for trade in trades),
        "total_slippage_cost": sum(trade.slippage_cost for trade in trades),
        "observation_years": years,
    }


class PortfolioEngine:
    """Long-only, fractional-share, close-to-open deterministic simulator.

    Entries at an open use cash available after the previous close. Exits at today's
    close are processed after entries and therefore cannot finance today's open.
    Missing marks carry the last valid close; missing exits defer to the next valid close.
    """

    def __init__(self, calendar: NYSETradingCalendar | None = None) -> None:
        self.calendar = calendar or NYSETradingCalendar()

    def run(
        self, request: PortfolioSimulationRequest, source: BacktestRunResult,
        bars_by_ticker: dict[str, list[MarketBar]], benchmark_bars: list[MarketBar],
        *, created_at: datetime | None = None,
    ) -> PortfolioSimulationResult:
        config, digest, run_id = portfolio_identity(request)
        bar_maps = {ticker: {bar.timestamp.date(): bar for bar in bars} for ticker, bars in bars_by_ticker.items()}
        benchmark = {bar.timestamp.date(): bar for bar in benchmark_bars}
        sessions = self.calendar.trading_days_between(source.start_date, source.end_date)
        entries: dict[date, list[BacktestEventResult]] = defaultdict(list)
        skipped: list[SkippedSignalResult] = []
        for event in source.events:
            if event.entry_date and event.entry_model.value == "NEXT_OPEN":
                entries[event.entry_date].append(event)
        cash = request.initial_capital
        positions: dict[str, _Position] = {}
        trades: list[PortfolioTradeResult] = []
        daily: list[PortfolioDailyResult] = []
        previous_equity = request.initial_capital
        benchmark_start = next((benchmark[day].open for day in sessions if day in benchmark), None)

        for session in sessions:
            # Open: rank and execute entries using only cash carried from the prior close.
            candidates = entries.get(session, [])
            candidates = sorted(candidates, key=(
                (lambda event: (-event.score, event.ticker))
                if request.selection_policy is SelectionPolicy.HIGHEST_SCORE_FIRST
                else (lambda event: event.ticker)
            ))
            slots = max(0, request.maximum_positions - len(positions))
            for event in candidates:
                if event.ticker in positions:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_ALREADY_HELD"))
                    continue
                if slots <= 0:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_MAX_POSITIONS"))
                    continue
                bar = bar_maps.get(event.ticker, {}).get(session)
                if bar is None:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_MISSING_ENTRY_PRICE"))
                    continue
                target = min(previous_equity * request.target_allocation, previous_equity * request.maximum_exposure)
                commission_rate = request.commission_bps / 10_000
                slip = request.slippage_bps / 10_000
                execution_price = bar.open * (1 + slip)
                affordable = cash / (1 + commission_rate)
                allocation = min(target, affordable)
                if allocation <= 0:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_NO_CAPITAL"))
                    continue
                quantity = allocation / execution_price
                commission = allocation * commission_rate
                total_cost = allocation + commission
                if total_cost > cash + 1e-8:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_NO_CAPITAL"))
                    continue
                positions[event.ticker] = _Position(
                    event=event, quantity=quantity, reference_entry=bar.open,
                    entry_price=execution_price, entry_cost=total_cost,
                    entry_commission=commission,
                    exit_due=self.calendar.session_offset(event.signal_date, request.holding_period),
                    last_price=bar.open,
                )
                cash -= total_cost
                slots -= 1

            # Close: mark first, then execute due exits. Proceeds become available tomorrow.
            exit_tickers = []
            for ticker, position in positions.items():
                bar = bar_maps.get(ticker, {}).get(session)
                if bar is not None:
                    position.last_price = bar.close
                if session >= position.exit_due and bar is not None:
                    slip = request.slippage_bps / 10_000
                    commission_rate = request.commission_bps / 10_000
                    exit_price = bar.close * (1 - slip)
                    gross_proceeds = position.quantity * exit_price
                    exit_commission = gross_proceeds * commission_rate
                    proceeds = gross_proceeds - exit_commission
                    cash += proceeds
                    gross_return = bar.close / position.reference_entry - 1
                    net_return = proceeds / position.entry_cost - 1
                    entry_slippage = position.quantity * (position.entry_price - position.reference_entry)
                    exit_slippage = position.quantity * (bar.close - exit_price)
                    trades.append(PortfolioTradeResult(
                        ticker=ticker, signal_date=position.event.signal_date,
                        entry_date=position.event.entry_date, exit_date=session,
                        score=position.event.score, quantity=position.quantity,
                        reference_entry_price=position.reference_entry, entry_price=position.entry_price,
                        reference_exit_price=bar.close, exit_price=exit_price,
                        gross_return=gross_return, net_return=net_return,
                        pnl=proceeds - position.entry_cost,
                        commission=position.entry_commission + exit_commission,
                        slippage_cost=entry_slippage + exit_slippage,
                        holding_sessions=len(self.calendar.trading_days_between(position.event.entry_date, session)),
                        exit_reason=f"TIME_EXIT_{request.holding_period}D",
                    ))
                    exit_tickers.append(ticker)
            for ticker in exit_tickers:
                del positions[ticker]

            market_value = sum(position.quantity * position.last_price for position in positions.values())
            equity = cash + market_value
            daily_return = equity / previous_equity - 1 if previous_equity else 0
            benchmark_equity = (
                request.initial_capital * benchmark[session].close / benchmark_start
                if benchmark_start and session in benchmark else None
            )
            daily.append(PortfolioDailyResult(
                session_date=session, cash=cash, positions_market_value=market_value,
                gross_exposure=market_value / equity if equity else 0,
                net_exposure=market_value / equity if equity else 0,
                total_equity=equity, daily_return=daily_return,
                cumulative_return=equity / request.initial_capital - 1,
                open_positions=len(positions), benchmark_equity=benchmark_equity,
            ))
            previous_equity = equity

        metrics = calculate_performance_metrics(daily, trades, initial_capital=request.initial_capital)
        benchmark_daily = [item for item in daily if item.benchmark_equity is not None]
        benchmark_returns = [benchmark_daily[index].benchmark_equity / benchmark_daily[index - 1].benchmark_equity - 1 for index in range(1, len(benchmark_daily))]
        benchmark_dd, benchmark_duration = _max_drawdown([item.benchmark_equity for item in benchmark_daily])
        benchmark_metrics = {
            "total_return": benchmark_daily[-1].benchmark_equity / request.initial_capital - 1 if benchmark_daily else None,
            "annualized_volatility": statistics.stdev(benchmark_returns) * math.sqrt(252) if len(benchmark_returns) > 1 else None,
            "maximum_drawdown": benchmark_dd,
            "maximum_drawdown_duration_sessions": benchmark_duration,
        }
        metrics["portfolio_excess_return"] = metrics["total_return"] - benchmark_metrics["total_return"] if benchmark_metrics["total_return"] is not None else None
        return PortfolioSimulationResult(
            run_id=run_id, config_hash=digest, source_backtest_run_id=source.run_id,
            strategy_version=source.strategy_version, start_date=source.start_date,
            universe_mode=source.universe_mode.value,
            end_date=source.end_date, configuration=config, metrics=metrics,
            benchmark_metrics=benchmark_metrics, trades=trades, daily_equity=daily,
            skipped_signals=skipped, created_at=created_at or datetime.now(UTC),
        )

    @staticmethod
    def _skip(event: BacktestEventResult, reason: str) -> SkippedSignalResult:
        return SkippedSignalResult(ticker=event.ticker, signal_date=event.signal_date,
                                   entry_date=event.entry_date, score=event.score, reason=reason)
