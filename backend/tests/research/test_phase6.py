from datetime import UTC, date, datetime

import pytest

from app.market_data.calendar import NYSETradingCalendar
from app.portfolio import PortfolioEngine, calculate_performance_metrics
from app.research import MarketRegimeEngine, ScoreResearchEngine, dependency_filter
from app.schemas.backtesting import BacktestEventResult, BacktestRunResult, EntryModel, ForwardOutcome, UniverseMode
from app.schemas.market_data import MarketBar
from app.schemas.research import MarketRegimeRequest, PortfolioDailyResult, PortfolioSimulationRequest, ScoreResearchRequest, SelectionPolicy

CALENDAR = NYSETradingCalendar()


def event(ticker: str, signal_date: date, score: float = 75) -> BacktestEventResult:
    return BacktestEventResult(
        ticker=ticker, signal_date=signal_date, strategy="BREAKOUT_20D_VOLUME", strategy_version="1.0.0",
        universe_mode=UniverseMode.FIXED_UNIVERSE_RESEARCH, universe_identifier="SP500", close=100,
        previous_high_20d=99, breakout_pct=.01, relative_volume=2, sma_50=95, sma_200=90,
        momentum_20d=.1, avg_dollar_volume_20d=10_000_000, distance_from_sma50=.05,
        score=score, score_components={"breakout": 1}, entry_model=EntryModel.NEXT_OPEN,
        entry_date=CALENDAR.session_offset(signal_date, 1), entry_price=101,
        outcomes=[ForwardOutcome(horizon=h, stock_return=.01 * h, benchmark_return=.005 * h,
                                 excess_return=.005 * h, mfe=.02 * h, mae=-.005 * h,
                                 forward_data_complete=True) for h in (1, 5, 10, 20, 60)],
    )


def source(events: list[BacktestEventResult], start=date(2024, 1, 2), end=date(2024, 12, 31)) -> BacktestRunResult:
    return BacktestRunResult(
        run_id="11111111-1111-1111-1111-111111111111", status="COMPLETED", config_hash="x" * 64,
        strategy="BREAKOUT_20D_VOLUME", strategy_version="1.0.0",
        universe_mode=UniverseMode.FIXED_UNIVERSE_RESEARCH, universe_identifier="SP500",
        survivorship_bias_warning="fixed", start_date=start, end_date=end, entry_model=EntryModel.NEXT_OPEN,
        benchmark="SPY", event_count=len(events), data_coverage={}, statistics_by_horizon={},
        statistics_by_score_bucket={}, statistics_by_year={}, statistics_by_quarter={},
        statistics_by_characteristic={}, events=events, data_quality_warnings=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def bars(ticker: str, start=date(2023, 1, 3), end=date(2024, 12, 31), growth=.001) -> list[MarketBar]:
    result = []
    for index, session in enumerate(CALENDAR.trading_days_between(start, end)):
        close = 100 * (1 + growth) ** index
        result.append(MarketBar(ticker=ticker, timestamp=datetime.combine(session, datetime.min.time(), tzinfo=UTC),
                                open=close * .999, high=close * 1.01, low=close * .99, close=close, volume=1_000_000))
    return result


def test_score_research_is_deterministic_and_has_requested_sections() -> None:
    events = [event("AAA", date(2024, 3, 1), 10), event("BBB", date(2024, 4, 1), 90)]
    request = ScoreResearchRequest(backtest_run_id=source(events).run_id)
    first = ScoreResearchEngine().run(request, source(events), created_at=datetime(2026, 1, 1, tzinfo=UTC))
    second = ScoreResearchEngine().run(request, source(events), created_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert first == second
    assert set(first.results) >= {"score_buckets", "score_buckets_by_year", "components", "dependency"}


def test_dependency_filter_allows_exact_cooldown_boundary() -> None:
    first = date(2024, 1, 2)
    events = [event("AAA", first), event("AAA", CALENDAR.session_offset(first, 19)),
              event("AAA", CALENDAR.session_offset(first, 20))]
    assert [item.signal_date for item in dependency_filter(events, 20, CALENDAR)] == [first, events[2].signal_date]


def test_same_day_events_receive_same_causal_volatility_regime() -> None:
    signal = date(2024, 9, 3)
    events = [event("AAA", signal), event("BBB", signal)]
    result = MarketRegimeEngine().run(
        MarketRegimeRequest(backtest_run_id=source(events).run_id, volatility_min_history=20),
        source(events), bars("SPY"),
    )
    rows = result.results["observations"]
    assert rows[0]["volatility_regime"] == rows[1]["volatility_regime"]
    assert rows[0]["sma200_regime"] == "SPY_ABOVE_SMA200"


def test_regime_classification_is_not_changed_by_future_bars() -> None:
    signal = date(2024, 9, 3)
    base = bars("SPY")
    mutated = [bar.model_copy(update={"close": bar.close * 4}) if bar.timestamp.date() > signal else bar for bar in base]
    request = MarketRegimeRequest(backtest_run_id=source([event("AAA", signal)]).run_id, volatility_min_history=20)
    a = MarketRegimeEngine().run(request, source([event("AAA", signal)]), base).results["observations"][0]
    b = MarketRegimeEngine().run(request, source([event("AAA", signal)]), mutated).results["observations"][0]
    assert a == b


def test_regime_is_unavailable_without_sufficient_sma_history() -> None:
    signal = date(2023, 2, 1)
    result = MarketRegimeEngine().run(
        MarketRegimeRequest(backtest_run_id=source([event("AAA", signal)]).run_id),
        source([event("AAA", signal)]), bars("SPY", start=date(2023, 1, 3)),
    )
    assert result.results["observations"][0]["sma200_regime"] == "REGIME_UNAVAILABLE"


def test_portfolio_prefers_highest_score_and_enforces_capacity() -> None:
    signal = date(2024, 3, 1)
    events = [event("AAA", signal, 10), event("BBB", signal, 90)]
    request = PortfolioSimulationRequest(backtest_run_id=source(events).run_id, maximum_positions=1,
                                         target_allocation=1, slippage_bps=0)
    result = PortfolioEngine().run(request, source(events), {"AAA": bars("AAA"), "BBB": bars("BBB")}, bars("SPY"))
    assert result.trades[0].ticker == "BBB"
    assert any(item.ticker == "AAA" and item.reason == "SIGNAL_SKIPPED_MAX_POSITIONS" for item in result.skipped_signals)


def test_portfolio_costs_reduce_return_and_results_are_deterministic() -> None:
    item = event("AAA", date(2024, 3, 1))
    zero = PortfolioSimulationRequest(backtest_run_id=source([item]).run_id, maximum_positions=1,
                                      target_allocation=1, slippage_bps=0, commission_bps=0)
    costly = zero.model_copy(update={"slippage_bps": 10, "commission_bps": 10})
    inputs = (source([item]), {"AAA": bars("AAA")}, bars("SPY"))
    baseline = PortfolioEngine().run(zero, *inputs, created_at=datetime(2026, 1, 1, tzinfo=UTC))
    repeated = PortfolioEngine().run(zero, *inputs, created_at=datetime(2026, 1, 1, tzinfo=UTC))
    with_costs = PortfolioEngine().run(costly, *inputs)
    assert baseline == repeated
    assert with_costs.metrics["total_return"] < baseline.metrics["total_return"]
    assert with_costs.metrics["total_commissions"] > 0


def test_unranked_baseline_uses_ticker_order() -> None:
    signal = date(2024, 3, 1)
    events = [event("ZZZ", signal, 99), event("AAA", signal, 1)]
    request = PortfolioSimulationRequest(backtest_run_id=source(events).run_id, maximum_positions=1,
        target_allocation=1, selection_policy=SelectionPolicy.DETERMINISTIC_UNRANKED_BASELINE, slippage_bps=0)
    result = PortfolioEngine().run(request, source(events), {ticker: bars(ticker) for ticker in ("AAA", "ZZZ")}, bars("SPY"))
    assert result.trades[0].ticker == "AAA"


def test_close_exit_cannot_fund_same_day_open() -> None:
    first_signal = date(2024, 3, 1)
    replacement_signal = CALENDAR.session_offset(first_signal, 19)
    events = [event("AAA", first_signal), event("BBB", replacement_signal)]
    request = PortfolioSimulationRequest(backtest_run_id=source(events).run_id, maximum_positions=1,
                                         target_allocation=1, holding_period=20, slippage_bps=0)
    result = PortfolioEngine().run(request, source(events), {"AAA": bars("AAA"), "BBB": bars("BBB")}, bars("SPY"))
    assert result.trades[0].exit_date == events[1].entry_date
    assert result.trades[0].holding_sessions == 20
    assert any(item.ticker == "BBB" and item.reason == "SIGNAL_SKIPPED_MAX_POSITIONS" for item in result.skipped_signals)


def test_signal_for_open_position_is_recorded_as_skipped() -> None:
    first = date(2024, 3, 1)
    events = [event("AAA", first), event("AAA", CALENDAR.session_offset(first, 5))]
    request = PortfolioSimulationRequest(backtest_run_id=source(events).run_id, maximum_positions=1,
                                         target_allocation=1, holding_period=20, slippage_bps=0)
    result = PortfolioEngine().run(request, source(events), {"AAA": bars("AAA")}, bars("SPY"))
    assert any(item.reason == "SIGNAL_SKIPPED_ALREADY_HELD" for item in result.skipped_signals)


def test_missing_entry_price_is_skipped_and_never_assumed_zero() -> None:
    item = event("AAA", date(2024, 3, 1))
    stock = [bar for bar in bars("AAA") if bar.timestamp.date() != item.entry_date]
    request = PortfolioSimulationRequest(backtest_run_id=source([item]).run_id, maximum_positions=1, target_allocation=1)
    result = PortfolioEngine().run(request, source([item]), {"AAA": stock}, bars("SPY"))
    assert not result.trades
    assert result.skipped_signals[0].reason == "SIGNAL_SKIPPED_MISSING_ENTRY_PRICE"
    assert all(day.total_equity == 100_000 for day in result.daily_equity)


def test_equity_curve_reconciles_cash_and_market_value_and_has_benchmark() -> None:
    item = event("AAA", date(2024, 3, 1))
    request = PortfolioSimulationRequest(backtest_run_id=source([item]).run_id, maximum_positions=1,
                                         target_allocation=1, slippage_bps=0)
    result = PortfolioEngine().run(request, source([item]), {"AAA": bars("AAA")}, bars("SPY"))
    assert all(day.total_equity == pytest.approx(day.cash + day.positions_market_value) for day in result.daily_equity)
    assert all(day.benchmark_equity is not None for day in result.daily_equity)


def test_performance_metrics_report_drawdown_and_omit_short_period_cagr() -> None:
    sessions = CALENDAR.trading_days_between(date(2024, 1, 2), date(2024, 1, 5))
    equity = [100, 120, 90, 100]
    daily = [PortfolioDailyResult(session_date=session, cash=value, positions_market_value=0,
        gross_exposure=0, net_exposure=0, total_equity=value,
        daily_return=0 if index == 0 else value / equity[index - 1] - 1,
        cumulative_return=value / 100 - 1, open_positions=0, benchmark_equity=value)
        for index, (session, value) in enumerate(zip(sessions, equity))]
    metrics = calculate_performance_metrics(daily, [], initial_capital=100)
    assert metrics["maximum_drawdown"] == pytest.approx(-.25)
    assert metrics["annualized_return_cagr"] is None
    assert metrics["sharpe_ratio"] is not None
    assert metrics["sortino_ratio"] is not None


def test_invalid_overallocated_portfolio_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds maximum exposure"):
        PortfolioSimulationRequest(backtest_run_id="x", maximum_positions=10, target_allocation=.2)
