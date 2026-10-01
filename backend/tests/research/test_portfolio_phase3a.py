from datetime import UTC, date, datetime

import pytest

from app.market_data.calendar import NYSETradingCalendar
from app.portfolio import (
    PortfolioEngine, PortfolioLifecycleEvent, portfolio_candidate_order,
    portfolio_engine_conventions, portfolio_security_id,
    validate_portfolio_score_invariance,
)
from app.schemas.backtesting import (
    BacktestEventResult, BacktestRunResult, EntryModel, ForwardOutcome, UniverseMode,
)
from app.schemas.market_data import MarketBar
from app.schemas.research import PortfolioSimulationRequest, SelectionPolicy


CALENDAR = NYSETradingCalendar()
SID_A = "00000000-0000-0000-0000-00000000000a"
SID_B = "00000000-0000-0000-0000-00000000000b"


def signal(security_id: str, when: date, score: float = 75) -> BacktestEventResult:
    return BacktestEventResult(
        ticker=security_id, signal_date=when, strategy="BREAKOUT_20D_VOLUME",
        strategy_version="1.0.0", universe_mode=UniverseMode.POINT_IN_TIME,
        universe_identifier="SP500", close=100, previous_high_20d=99,
        breakout_pct=1, relative_volume=2, sma_50=95, sma_200=90,
        momentum_20d=.1, avg_dollar_volume_20d=20_000_000,
        distance_from_sma50=.05, score=score,
        score_components={"breakout": 10, "relative_volume": 10},
        entry_model=EntryModel.NEXT_OPEN,
        entry_date=CALENDAR.session_offset(when, 1), entry_price=100,
        outcomes=[ForwardOutcome(
            horizon=horizon, stock_return=.01, benchmark_return=0,
            excess_return=.01, mfe=.02, mae=-.01, forward_data_complete=True,
        ) for horizon in (1, 5, 10, 20, 60)],
    )


def source(events: list[BacktestEventResult], *, end: date = date(2024, 6, 28)) -> BacktestRunResult:
    return BacktestRunResult(
        run_id="11111111-1111-1111-1111-111111111111", status="COMPLETED",
        config_hash="a" * 64, strategy="BREAKOUT_20D_VOLUME", strategy_version="1.0.0",
        universe_mode=UniverseMode.POINT_IN_TIME, universe_identifier="SP500",
        survivorship_bias_warning=None, start_date=date(2024, 1, 2), end_date=end,
        entry_model=EntryModel.NEXT_OPEN, benchmark="SPY", event_count=len(events),
        data_coverage={}, statistics_by_horizon={}, statistics_by_score_bucket={},
        statistics_by_year={}, statistics_by_quarter={},
        statistics_by_characteristic={}, events=events, data_quality_warnings=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def bars(identity: str, *, end: date = date(2024, 6, 28), price: float = 100) -> list[MarketBar]:
    ticker = identity if len(identity) <= 16 else f"T{identity[-6:]}"
    return [MarketBar(
        ticker=ticker, timestamp=datetime.combine(session, datetime.min.time(), tzinfo=UTC),
        open=price, high=price * 1.01, low=price * .99, close=price,
        volume=1_000_000,
    ) for session in CALENDAR.trading_days_between(date(2024, 1, 2), end)]


def request(**updates) -> PortfolioSimulationRequest:
    values = dict(
        backtest_run_id="11111111-1111-1111-1111-111111111111",
        initial_capital=100_000, maximum_positions=10, target_allocation=.1,
        maximum_exposure=1, holding_period=20, commission_bps=0,
        slippage_bps=5, security_id_native=True,
    )
    values.update(updates)
    return PortfolioSimulationRequest(**values)


def run(events, *, stock_bars=None, lifecycle=None, end=date(2024, 6, 28), **updates):
    stock_bars = stock_bars or {event.ticker: bars(event.ticker, end=end) for event in events}
    return PortfolioEngine().run(
        request(**updates), source(events, end=end), stock_bars, bars("SPY", end=end),
        lifecycle_events=lifecycle or [],
        ticker_by_security_id={SID_A: "AAA", SID_B: "BBB"},
        provenance_by_event={(event.ticker, event.signal_date): "BOTH" for event in events},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_ordering_uses_score_then_security_id_not_ticker() -> None:
    when = date(2024, 3, 1)
    events = [signal(SID_B, when), signal(SID_A, when)]
    result = run(events, maximum_positions=1, target_allocation=1)
    assert result.entries[0].security_id == SID_A
    assert portfolio_candidate_order(events[0], SID_B, SelectionPolicy.HIGHEST_SCORE_FIRST) == (-75, SID_B)


def test_unranked_order_is_security_id_only() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    assert portfolio_candidate_order(
        item, SID_A, SelectionPolicy.DETERMINISTIC_UNRANKED_BASELINE
    ) == (SID_A,)


def test_security_id_native_mode_has_no_ticker_fallback() -> None:
    item = signal(SID_A, date(2024, 3, 1)).model_copy(update={"ticker": "AAA"})
    with pytest.raises(ValueError, match="security_id-native"):
        run([item], stock_bars={"AAA": bars("AAA")})
    with pytest.raises(ValueError, match="security_id-native"):
        portfolio_security_id(item, required=True)


def test_score_is_security_local_and_invariant_for_shared_event() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    assert validate_portfolio_score_invariance([item], [item])["status"] == "PASS"
    changed = item.model_copy(update={"score": item.score + 1})
    assert validate_portfolio_score_invariance([item], [changed])["status"] == "FAIL"


def test_equal_weight_uses_previous_close_equity_and_no_leverage() -> None:
    result = run([signal(SID_A, date(2024, 3, 1))])
    assert result.entries[0].position_size == pytest.approx(10_000)
    assert all(day.cash >= -1e-8 for day in result.daily_equity)
    assert portfolio_engine_conventions()["position_sizing_equity_basis"].startswith("previous")


def test_maximum_ten_positions_and_duplicate_identity_protection() -> None:
    when = date(2024, 3, 1)
    identities = [f"00000000-0000-0000-0000-{index:012x}" for index in range(1, 12)]
    events = [signal(identity, when) for identity in identities]
    result = run(events)
    assert max(day.open_positions for day in result.daily_equity) == 10
    assert any(item.reason == "SIGNAL_SKIPPED_MAX_POSITIONS" for item in result.skipped_signals)
    duplicate = signal(SID_A, CALENDAR.session_offset(when, 5))
    held = run([signal(SID_A, when), duplicate])
    assert any(item.reason == "SIGNAL_SKIPPED_ALREADY_HELD" for item in held.skipped_signals)


def test_next_open_entry_and_entry_slippage_are_exactly_once() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    result = run([item])
    entry = result.entries[0]
    assert entry.entry_date == CALENDAR.session_offset(item.signal_date, 1)
    assert entry.entry_price == pytest.approx(100.05)
    assert entry.entry_slippage_cost == pytest.approx(entry.quantity * .05)


def test_twenty_session_alignment_and_close_exit_slippage() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    result = run([item])
    trade = result.trades[0]
    assert trade.exit_date == CALENDAR.session_offset(item.signal_date, 20)
    assert trade.holding_sessions == 20
    assert trade.reference_exit_price == 100
    assert trade.exit_price == pytest.approx(99.95)
    assert trade.exit_slippage_cost == pytest.approx(trade.quantity * .05)


def test_close_exit_slot_and_cash_are_available_only_next_session() -> None:
    first = signal(SID_A, date(2024, 3, 1))
    same_close_signal = signal(SID_B, CALENDAR.session_offset(first.signal_date, 19))
    result = run([first, same_close_signal], maximum_positions=1, target_allocation=1)
    trade = result.trades[0]
    assert trade.exit_date == same_close_signal.entry_date
    assert trade.slot_release_date == CALENDAR.session_offset(trade.exit_date, 1)
    assert any(item.security_id == SID_B and item.reason == "SIGNAL_SKIPPED_MAX_POSITIONS"
               for item in result.skipped_signals)


def test_index_removal_does_not_close_and_post_membership_bars_are_used() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    hypothetical_removal = CALENDAR.session_offset(item.signal_date, 5)
    result = run([item])
    assert result.trades[0].exit_date > hypothetical_removal
    assert result.trades[0].exit_reason == "TIME_EXIT_20D"


@pytest.mark.parametrize("reason", ["ACQUISITION", "MERGER", "DELISTING_OTHER"])
def test_lifecycle_exit_uses_last_legitimate_close_with_exit_slippage(reason: str) -> None:
    item = signal(SID_A, date(2024, 3, 1))
    exit_session = CALENDAR.session_offset(item.entry_date, 5)
    policy = PortfolioLifecycleEvent(SID_A, reason, exit_session, exit_session)
    result = run([item], lifecycle=[policy])
    trade = result.trades[0]
    assert trade.exit_date == exit_session
    assert trade.reference_exit_price == 100
    assert trade.exit_price == pytest.approx(99.95)
    assert trade.lifecycle_treatment == f"{reason}_LAST_LEGITIMATE_CLOSE"
    assert trade.slot_release_date == CALENDAR.session_offset(exit_session, 1)


def test_bankruptcy_is_minus_100_with_zero_cash_and_no_exit_slippage() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    exit_session = CALENDAR.session_offset(item.entry_date, 5)
    policy = PortfolioLifecycleEvent(SID_A, "BANKRUPTCY", exit_session, None)
    result = run([item], lifecycle=[policy])
    trade = result.trades[0]
    assert trade.reference_exit_price == trade.exit_price == 0
    assert trade.gross_return == -1
    assert trade.exit_slippage_cost == 0
    assert trade.lifecycle_treatment == "BANKRUPTCY_ZERO_TERMINAL_VALUE"


def test_lifecycle_cash_credit_reconciles_and_no_successor_is_substituted() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    exit_session = CALENDAR.session_offset(item.entry_date, 5)
    stock = {SID_A: bars(SID_A), SID_B: bars(SID_B, price=1_000)}
    policy = PortfolioLifecycleEvent(SID_A, "ACQUISITION", exit_session, exit_session)
    result = run([item], stock_bars=stock, lifecycle=[policy])
    exit_day = next(day for day in result.daily_equity if day.session_date == exit_session)
    assert exit_day.cash == pytest.approx(result.trades[0].quantity * 99.95 + 90_000)
    assert result.trades[0].reference_exit_price == 100


def test_missing_same_security_mark_and_lifecycle_close_fail_closed() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    missing_session = CALENDAR.session_offset(item.entry_date, 2)
    own = [bar for bar in bars(SID_A) if bar.timestamp.date() != missing_session]
    with pytest.raises(ValueError, match="missing same-security mark"):
        run([item], stock_bars={SID_A: own, SID_B: bars(SID_B, price=1_000)})
    policy = PortfolioLifecycleEvent(SID_A, "MERGER", missing_session, missing_session)
    with pytest.raises(ValueError, match="missing legitimate lifecycle close"):
        run([item], stock_bars={SID_A: own, SID_B: bars(SID_B, price=1_000)}, lifecycle=[policy])


def test_non_executable_signal_is_recorded_and_cannot_enter() -> None:
    item = signal(SID_A, date(2024, 3, 1)).model_copy(
        update={"entry_date": None, "entry_price": None}
    )
    result = run([item])
    assert result.entries == [] and result.trades == []
    assert result.skipped_signals[0].reason == "NON_EXECUTABLE_LIFECYCLE_TERMINATION"


def test_research_window_end_preserves_open_position_without_forced_exit() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    short_end = CALENDAR.session_offset(item.signal_date, 5)
    result = run([item], end=short_end)
    assert result.trades == []
    assert result.metrics["open_positions_at_research_end"] == 1
    assert result.daily_equity[-1].open_positions == 1


def test_accounting_and_ledger_capability_reconcile_without_silent_deletion() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    result = run([item])
    assert all(day.total_equity == pytest.approx(day.cash + day.positions_market_value)
               for day in result.daily_equity)
    assert len(result.entries) == len(result.trades) + result.metrics["open_positions_at_research_end"]
    assert result.entries[0].provenance == "BOTH"
    assert result.trades[0].security_id == SID_A
    assert result.trades[0].exit_value > 0
    assert result.trades[0].slot_release_date is not None
    assert all(day.available_slots == 10 - day.open_positions for day in result.daily_equity)
    assert any(day.entries for day in result.daily_equity)
    assert any(day.exits for day in result.daily_equity)
    assert result.warning is None


def test_engine_conventions_freeze_metrics_and_path_policy() -> None:
    conventions = portfolio_engine_conventions()
    assert conventions["risk_free_rate"] == 0
    assert conventions["annualization_sessions"] == 252
    assert "365.25" in conventions["cagr"]
    assert "sample_stdev" in conventions["sharpe"]
    assert "MAR=0" in conventions["sortino"]
    assert conventions["calmar"] == "CAGR / abs(maximum_drawdown)"
    assert "no forced liquidation" in conventions["research_window_end"]


def test_portfolio_rerun_is_deterministic() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    assert run([item]) == run([item])


def test_lifecycle_policy_is_part_of_deterministic_identity() -> None:
    item = signal(SID_A, date(2024, 3, 1))
    exit_session = CALENDAR.session_offset(item.entry_date, 5)
    acquisition = PortfolioLifecycleEvent(SID_A, "ACQUISITION", exit_session, exit_session)
    merger = PortfolioLifecycleEvent(SID_A, "MERGER", exit_session, exit_session)
    assert run([item], lifecycle=[acquisition]).config_hash != run(
        [item], lifecycle=[merger]
    ).config_hash
