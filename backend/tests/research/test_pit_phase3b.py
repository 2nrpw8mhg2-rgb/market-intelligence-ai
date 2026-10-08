from datetime import UTC, date, datetime

import pytest

from app.market_data.calendar import NYSETradingCalendar
from app.portfolio import PortfolioEngine, PortfolioLifecycleEvent
from app.research.pit_phase3b import (
    accounting_reconciliation, classify_signal_outcomes, exposure_summary,
    open_position_ledger, portfolio_digest, portfolio_summary,
    realized_pnl_concentration, slippage_reconciliation,
)
from app.schemas.backtesting import (
    BacktestEventResult, BacktestRunResult, EntryModel, ForwardOutcome, UniverseMode,
)
from app.schemas.market_data import MarketBar
from app.schemas.research import PortfolioSimulationRequest


CALENDAR = NYSETradingCalendar()
SID_A = "00000000-0000-0000-0000-00000000000a"
SID_B = "00000000-0000-0000-0000-00000000000b"
START = date(2024, 1, 2)
END = date(2024, 6, 28)


def signal(security_id: str, when: date, *, executable: bool = True):
    return BacktestEventResult(
        ticker=security_id, signal_date=when, strategy="BREAKOUT_20D_VOLUME",
        strategy_version="1.0.0", universe_mode=UniverseMode.POINT_IN_TIME,
        universe_identifier="SP500", close=100, previous_high_20d=99,
        breakout_pct=1, relative_volume=2, sma_50=95, sma_200=90,
        momentum_20d=.1, avg_dollar_volume_20d=20_000_000,
        distance_from_sma50=.05, score=75,
        score_components={"breakout": 10}, entry_model=EntryModel.NEXT_OPEN,
        entry_date=CALENDAR.session_offset(when, 1) if executable else None,
        entry_price=100 if executable else None,
        outcomes=[ForwardOutcome(
            horizon=value, stock_return=.01, benchmark_return=0,
            excess_return=.01, forward_data_complete=True,
        ) for value in (1, 5, 10, 20, 60)],
    )


def bars(identity: str, *, price: float = 100):
    ticker = identity if len(identity) <= 16 else identity[-12:]
    return [MarketBar(
        ticker=ticker,
        timestamp=datetime.combine(session, datetime.min.time(), tzinfo=UTC),
        open=price, high=price * 1.01, low=price * .99, close=price,
        volume=1_000_000,
    ) for session in CALENDAR.trading_days_between(START, END)]


def simulate(events, *, lifecycle=None, maximum_positions=10):
    source = BacktestRunResult(
        run_id="11111111-1111-1111-1111-111111111111", status="COMPLETED",
        config_hash="a" * 64, strategy="BREAKOUT_20D_VOLUME",
        strategy_version="1.0.0", universe_mode=UniverseMode.POINT_IN_TIME,
        universe_identifier="SP500", survivorship_bias_warning=None,
        start_date=START, end_date=END, entry_model=EntryModel.NEXT_OPEN,
        benchmark="SPY", event_count=len(events), data_coverage={},
        statistics_by_horizon={}, statistics_by_score_bucket={},
        statistics_by_year={}, statistics_by_quarter={},
        statistics_by_characteristic={}, events=events, data_quality_warnings=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    request = PortfolioSimulationRequest(
        backtest_run_id=source.run_id, initial_capital=100_000,
        maximum_positions=maximum_positions,
        target_allocation=1 / maximum_positions,
        holding_period=20, slippage_bps=5, security_id_native=True,
    )
    stock = {identity: bars(identity) for identity in {row.ticker for row in events}}
    result = PortfolioEngine().run(
        request, source, stock, bars("SPY"), lifecycle_events=lifecycle or [],
        ticker_by_security_id={SID_A: "AAA", SID_B: "BBB"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return result, stock


def test_primary_arms_execute_and_all_executable_signals_reconcile() -> None:
    events = [signal(SID_A, date(2024, 3, 1))]
    fixed, _ = simulate(events)
    pit, _ = simulate(events)
    assert len(fixed.entries) == len(pit.entries) == 1
    assert classify_signal_outcomes(fixed, expected_executable=1)["status"] == "PASS"
    assert classify_signal_outcomes(pit, expected_executable=1)["status"] == "PASS"


def test_end_window_open_position_is_marked_and_excluded_from_closed_statistics() -> None:
    events = [
        signal(SID_A, date(2024, 3, 1)),
        signal(SID_B, date(2024, 6, 20)),
    ]
    result, stock = simulate(events)
    ledger = open_position_ledger(result, stock)
    assert ledger["status"] == "PASS" and ledger["count"] == 1
    assert result.metrics["number_of_trades"] == 1
    assert result.metrics["mean_trade_return"] == pytest.approx(result.trades[0].net_return)
    assert result.daily_equity[-1].total_equity == pytest.approx(
        result.daily_equity[-1].cash + ledger["marked_market_value"]
    )


def test_lifecycle_position_accounting_and_non_executable_exclusion() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    exit_session = CALENDAR.session_offset(item.entry_date, 5)
    policy = PortfolioLifecycleEvent(SID_A, "ACQUISITION", exit_session, exit_session)
    nonexec = signal(SID_B, date(2024, 4, 1), executable=False)
    result, stock = simulate([item, nonexec], lifecycle=[policy])
    summary = portfolio_summary(
        result, expected_executable=1, bars_by_security=stock,
        lifecycle_by_security={SID_A: {
            "category": "ACQUISITION", "lifecycle_date": exit_session.isoformat(),
            "last_legitimate_close_date": exit_session.isoformat(),
        }},
    )
    assert len(summary["lifecycle_positions"]) == 1
    assert summary["signal_outcomes"]["non_executable_skipped"] == 1
    assert all(entry.security_id != SID_B for entry in result.entries)


def test_daily_accounting_slippage_exposure_and_performance_metrics_reconcile() -> None:
    result, _ = simulate([signal(SID_A, date(2024, 3, 1))])
    assert accounting_reconciliation(result, maximum_positions=10)["status"] == "PASS"
    slip = slippage_reconciliation(result)
    assert slip["status"] == "PASS" and slip["total_slippage_dollars"] > 0
    exposure = exposure_summary(result)
    assert exposure["maximum_positions"] == 1
    assert result.metrics["total_return"] is not None
    assert result.metrics["annualized_volatility"] is not None
    assert result.metrics["annualized_return_cagr"] is None  # span is under one year


def test_repeated_execution_has_identical_portfolio_digest() -> None:
    events = [signal(SID_A, date(2024, 3, 1))]
    first, _ = simulate(events)
    second, _ = simulate(events)
    assert portfolio_digest(first) == portfolio_digest(second)


def test_realized_pnl_concentration_uses_closed_trades_only() -> None:
    result, _ = simulate([
        signal(SID_A, date(2024, 3, 1)),
        signal(SID_B, date(2024, 6, 20)),
    ])
    concentration = realized_pnl_concentration(result)
    assert result.metrics["open_positions_at_research_end"] == 1
    assert concentration["best_trade"]["security_id"] == SID_A
    assert concentration["total_realized_trade_pnl"] == pytest.approx(result.trades[0].pnl)


def test_next_open_after_research_end_is_explicit_rejected_other() -> None:
    event = signal(SID_A, END)
    result, _ = simulate([event])
    outcomes = classify_signal_outcomes(result, expected_executable=1)
    assert outcomes["REJECTED_OTHER"] == 1
    assert outcomes["other_reasons"] == {
        "SIGNAL_SKIPPED_ENTRY_OUTSIDE_RESEARCH_WINDOW": 1
    }
    assert outcomes["status"] == "PASS"
