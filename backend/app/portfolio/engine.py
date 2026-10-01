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
    PortfolioDailyResult, PortfolioEntryResult, PortfolioSimulationRequest, PortfolioSimulationResult,
    PortfolioTradeResult, SelectionPolicy, SkippedSignalResult,
)


PORTFOLIO_ENGINE_CONVENTIONS: dict[str, Any] = {
    "candidate_order_highest_score": ("score DESC", "security_id ASC"),
    "candidate_order_unranked": ("security_id ASC",),
    "position_sizing_rule": "min(previous_close_equity * target_allocation, affordable_cash)",
    "position_sizing_equity_basis": "previous XNYS session end-of-session equity",
    "entry_session": "signal_date + 1 XNYS session at OPEN",
    "scheduled_exit": "signal_date + holding_period XNYS sessions at CLOSE",
    "slot_release": "session after CLOSE exit; usable at next XNYS OPEN",
    "cash_availability": "exit proceeds credited at CLOSE; usable at next XNYS OPEN",
    "research_window_end": (
        "no forced liquidation; open positions remain marked at the final legitimate close "
        "and are reported as open_positions_at_research_end"
    ),
    "risk_free_rate": 0.0,
    "annualization_sessions": 252,
    "cagr": "(ending_equity / initial_capital) ** (1 / calendar_years) - 1; calendar_years=days/365.25",
    "sharpe": "mean(daily_return) / sample_stdev(daily_return) * sqrt(252); risk_free=0",
    "sortino": (
        "mean(daily_return) * 252 / (sqrt(mean(min(daily_return, 0)^2)) * sqrt(252)); MAR=0"
    ),
    "calmar": "CAGR / abs(maximum_drawdown)",
}


def portfolio_engine_conventions() -> dict[str, Any]:
    return dict(PORTFOLIO_ENGINE_CONVENTIONS)


@dataclass
class _Position:
    security_id: str
    ticker: str
    provenance: str | None
    event: BacktestEventResult
    quantity: float
    reference_entry: float
    entry_price: float
    entry_cost: float
    entry_commission: float
    exit_due: date
    last_price: float


@dataclass(frozen=True)
class PortfolioLifecycleEvent:
    security_id: str
    reason: str
    exit_session: date
    last_legitimate_close_session: date | None

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.security_id)
        except ValueError:
            raise ValueError("portfolio lifecycle policy requires security_id UUID") from None
        if self.reason not in {"ACQUISITION", "MERGER", "DELISTING_OTHER", "BANKRUPTCY"}:
            raise ValueError(f"unsupported portfolio lifecycle reason: {self.reason}")
        if self.reason != "BANKRUPTCY" and self.last_legitimate_close_session is None:
            raise ValueError("non-bankruptcy lifecycle exit requires a legitimate close session")


def portfolio_security_id(event: BacktestEventResult, *, required: bool) -> str:
    """Resolve the authoritative identity without translating a temporal ticker alias."""
    value = str(event.ticker)
    try:
        return str(uuid.UUID(value))
    except ValueError:
        if required:
            raise ValueError(
                f"security_id-native portfolio input required for signal {event.signal_date}"
            ) from None
        return value


def portfolio_candidate_order(
    event: BacktestEventResult, security_id: str, policy: SelectionPolicy,
) -> tuple[Any, ...]:
    if policy is SelectionPolicy.HIGHEST_SCORE_FIRST:
        return (-event.score, security_id)
    return (security_id,)


def validate_portfolio_score_invariance(
    fixed: list[BacktestEventResult], pit: list[BacktestEventResult],
) -> dict[str, Any]:
    def keyed(events: list[BacktestEventResult]) -> dict[tuple[str, date], float]:
        result = {}
        for event in events:
            security_id = portfolio_security_id(event, required=True)
            key = (security_id, event.signal_date)
            if key in result:
                raise ValueError(f"duplicate portfolio signal identity: {key}")
            result[key] = event.score
        return result

    left, right = keyed(fixed), keyed(pit)
    shared = sorted(left.keys() & right.keys())
    mismatches = [key for key in shared if left[key] != right[key]]
    return {"status": "PASS" if not mismatches else "FAIL",
            "shared_events": len(shared), "mismatches": len(mismatches)}


def portfolio_identity(
    request: PortfolioSimulationRequest,
    lifecycle_events: list[PortfolioLifecycleEvent] | None = None,
) -> tuple[dict[str, Any], str, str]:
    config = request.model_dump(mode="json")
    config["lifecycle_events"] = [
        {
            "security_id": item.security_id, "reason": item.reason,
            "exit_session": item.exit_session.isoformat(),
            "last_legitimate_close_session": (
                item.last_legitimate_close_session.isoformat()
                if item.last_legitimate_close_session else None
            ),
        }
        for item in sorted(
            lifecycle_events or [], key=lambda value: (value.security_id, value.exit_session)
        )
    ]
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
    Open positions require a same-security close on every ordinary session. Missing
    marks fail closed; lifecycle exits use only their explicit terminal treatment.
    """

    def __init__(self, calendar: NYSETradingCalendar | None = None) -> None:
        self.calendar = calendar or NYSETradingCalendar()

    def run(
        self, request: PortfolioSimulationRequest, source: BacktestRunResult,
        bars_by_ticker: dict[str, list[MarketBar]], benchmark_bars: list[MarketBar],
        *, lifecycle_events: list[PortfolioLifecycleEvent] | None = None,
        ticker_by_security_id: dict[str, str] | None = None,
        provenance_by_event: dict[tuple[str, date], str] | None = None,
        created_at: datetime | None = None,
    ) -> PortfolioSimulationResult:
        config, digest, run_id = portfolio_identity(request, lifecycle_events)
        bar_maps = {ticker: {bar.timestamp.date(): bar for bar in bars} for ticker, bars in bars_by_ticker.items()}
        benchmark = {bar.timestamp.date(): bar for bar in benchmark_bars}
        sessions = self.calendar.trading_days_between(source.start_date, source.end_date)
        entries: dict[date, list[tuple[BacktestEventResult, str]]] = defaultdict(list)
        skipped: list[SkippedSignalResult] = []
        entry_ledger: list[PortfolioEntryResult] = []
        ticker_by_security_id = ticker_by_security_id or {}
        provenance_by_event = provenance_by_event or {}
        lifecycle_by_security = {item.security_id: item for item in lifecycle_events or []}
        if len(lifecycle_by_security) != len(lifecycle_events or []):
            raise ValueError("duplicate lifecycle policy for security_id")
        for event in source.events:
            security_id = portfolio_security_id(event, required=request.security_id_native)
            if event.entry_date and event.entry_model.value == "NEXT_OPEN":
                entries[event.entry_date].append((event, security_id))
            elif event.entry_model.value == "NEXT_OPEN":
                skipped.append(self._skip(
                    event, "NON_EXECUTABLE_LIFECYCLE_TERMINATION", security_id,
                    ticker_by_security_id.get(security_id, str(event.ticker)),
                    provenance_by_event.get((security_id, event.signal_date)),
                ))
        cash = request.initial_capital
        positions: dict[str, _Position] = {}
        trades: list[PortfolioTradeResult] = []
        daily: list[PortfolioDailyResult] = []
        previous_equity = request.initial_capital
        benchmark_start = next((benchmark[day].open for day in sessions if day in benchmark), None)
        peak_equity = request.initial_capital

        for session in sessions:
            # Open: rank and execute entries using only cash carried from the prior close.
            candidates = entries.get(session, [])
            candidates = sorted(
                candidates,
                key=lambda item: portfolio_candidate_order(
                    item[0], item[1], request.selection_policy
                ),
            )
            slots = max(0, request.maximum_positions - len(positions))
            entered_ids = []
            exited_ids = []
            for event, security_id in candidates:
                ticker = ticker_by_security_id.get(security_id, str(event.ticker))
                provenance = provenance_by_event.get((security_id, event.signal_date))
                lifecycle = lifecycle_by_security.get(security_id)
                if lifecycle is not None and session > lifecycle.exit_session:
                    raise ValueError(
                        f"portfolio entry occurs after lifecycle termination: {security_id}"
                    )
                if security_id in positions:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_ALREADY_HELD",
                                              security_id, ticker, provenance))
                    continue
                if slots <= 0:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_MAX_POSITIONS",
                                              security_id, ticker, provenance))
                    continue
                bar = bar_maps.get(security_id, {}).get(session)
                if bar is None:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_MISSING_ENTRY_PRICE",
                                              security_id, ticker, provenance))
                    continue
                target = min(previous_equity * request.target_allocation, previous_equity * request.maximum_exposure)
                commission_rate = request.commission_bps / 10_000
                slip = request.slippage_bps / 10_000
                execution_price = bar.open * (1 + slip)
                affordable = cash / (1 + commission_rate)
                allocation = min(target, affordable)
                if allocation <= 0:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_NO_CAPITAL",
                                              security_id, ticker, provenance))
                    continue
                quantity = allocation / execution_price
                commission = allocation * commission_rate
                total_cost = allocation + commission
                if total_cost > cash + 1e-8:
                    skipped.append(self._skip(event, "SIGNAL_SKIPPED_NO_CAPITAL",
                                              security_id, ticker, provenance))
                    continue
                exit_due = self.calendar.session_offset(event.signal_date, request.holding_period)
                positions[security_id] = _Position(
                    security_id=security_id, ticker=ticker, provenance=provenance,
                    event=event, quantity=quantity, reference_entry=bar.open,
                    entry_price=execution_price, entry_cost=total_cost,
                    entry_commission=commission,
                    exit_due=exit_due,
                    last_price=bar.open,
                )
                entry_ledger.append(PortfolioEntryResult(
                    security_id=security_id, ticker=ticker, provenance=provenance,
                    signal_date=event.signal_date, entry_date=session, score=event.score,
                    reference_entry_price=bar.open, entry_price=execution_price,
                    quantity=quantity, position_size=allocation,
                    entry_slippage_cost=quantity * (execution_price - bar.open),
                    scheduled_exit_date=exit_due,
                ))
                cash -= total_cost
                slots -= 1
                entered_ids.append(security_id)

            # Close: mark first, then execute due exits. Proceeds become available tomorrow.
            exit_security_ids = []
            for security_id, position in positions.items():
                bar = bar_maps.get(security_id, {}).get(session)
                if bar is not None:
                    position.last_price = bar.close
                lifecycle = lifecycle_by_security.get(security_id)
                lifecycle_due = lifecycle is not None and session >= lifecycle.exit_session
                if bar is None and not lifecycle_due:
                    raise ValueError(
                        f"missing same-security mark for open position security_id={security_id} "
                        f"session={session}"
                    )
                time_due = session >= position.exit_due and bar is not None
                if lifecycle_due or time_due:
                    slip = request.slippage_bps / 10_000
                    commission_rate = request.commission_bps / 10_000
                    if lifecycle_due and lifecycle.reason == "BANKRUPTCY":
                        reference_exit = 0.0
                        exit_price = 0.0
                        lifecycle_treatment = "BANKRUPTCY_ZERO_TERMINAL_VALUE"
                    elif lifecycle_due:
                        assert lifecycle.last_legitimate_close_session is not None
                        legitimate = bar_maps.get(security_id, {}).get(
                            lifecycle.last_legitimate_close_session
                        )
                        if legitimate is None:
                            raise ValueError(
                                f"missing legitimate lifecycle close for security_id={security_id}"
                            )
                        reference_exit = legitimate.close
                        exit_price = reference_exit * (1 - slip)
                        lifecycle_treatment = f"{lifecycle.reason}_LAST_LEGITIMATE_CLOSE"
                    else:
                        assert bar is not None
                        reference_exit = bar.close
                        exit_price = reference_exit * (1 - slip)
                        lifecycle_treatment = None
                    gross_proceeds = position.quantity * exit_price
                    exit_commission = gross_proceeds * commission_rate
                    proceeds = gross_proceeds - exit_commission
                    cash += proceeds
                    gross_return = reference_exit / position.reference_entry - 1
                    net_return = proceeds / position.entry_cost - 1
                    entry_slippage = position.quantity * (position.entry_price - position.reference_entry)
                    exit_slippage = position.quantity * (reference_exit - exit_price)
                    slot_release = self.calendar.session_offset(session, 1)
                    trades.append(PortfolioTradeResult(
                        security_id=security_id, ticker=position.ticker,
                        provenance=position.provenance,
                        signal_date=position.event.signal_date,
                        entry_date=position.event.entry_date, exit_date=session,
                        score=position.event.score, quantity=position.quantity,
                        reference_entry_price=position.reference_entry, entry_price=position.entry_price,
                        reference_exit_price=reference_exit, exit_price=exit_price,
                        exit_value=proceeds,
                        gross_return=gross_return, net_return=net_return,
                        pnl=proceeds - position.entry_cost,
                        commission=position.entry_commission + exit_commission,
                        slippage_cost=entry_slippage + exit_slippage,
                        entry_slippage_cost=entry_slippage,
                        exit_slippage_cost=exit_slippage,
                        holding_sessions=len(self.calendar.trading_days_between(position.event.entry_date, session)),
                        exit_reason=(f"LIFECYCLE_{lifecycle.reason}" if lifecycle_due
                                     else f"TIME_EXIT_{request.holding_period}D"),
                        lifecycle_treatment=lifecycle_treatment,
                        slot_release_date=slot_release,
                    ))
                    exit_security_ids.append(security_id)
                    exited_ids.append(security_id)
            for security_id in exit_security_ids:
                del positions[security_id]

            market_value = sum(position.quantity * position.last_price for position in positions.values())
            equity = cash + market_value
            if cash < -1e-8:
                raise RuntimeError("portfolio cash became materially negative")
            if len(positions) > request.maximum_positions:
                raise RuntimeError("portfolio position limit exceeded")
            daily_return = equity / previous_equity - 1 if previous_equity else 0
            peak_equity = max(peak_equity, equity)
            drawdown = equity / peak_equity - 1 if peak_equity else 0
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
                available_slots=request.maximum_positions - len(positions),
                entries=entered_ids, exits=exited_ids, drawdown=drawdown,
            ))
            previous_equity = equity

        metrics = calculate_performance_metrics(daily, trades, initial_capital=request.initial_capital)
        metrics["open_positions_at_research_end"] = len(positions)
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
            warning=source.survivorship_bias_warning,
            end_date=source.end_date, configuration=config, metrics=metrics,
            benchmark_metrics=benchmark_metrics, entries=entry_ledger,
            trades=trades, daily_equity=daily,
            skipped_signals=skipped, created_at=created_at or datetime.now(UTC),
        )

    @staticmethod
    def _skip(
        event: BacktestEventResult, reason: str, security_id: str,
        ticker: str, provenance: str | None,
    ) -> SkippedSignalResult:
        return SkippedSignalResult(
            security_id=security_id, ticker=ticker, provenance=provenance,
            signal_date=event.signal_date, entry_date=event.entry_date,
            score=event.score, reason=reason,
        )
