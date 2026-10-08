from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.research.pit_phase3c import (
    both_four_way, bucket, capacity_and_cash, common_trade_effect, concentration,
    cross_arm_matching, diagnostic_digest, equity_path, first_divergence,
    lifecycle_diagnostics,
    market_regime_labels, pnl_reconciliation, provenance_diagnostics,
    rejection_diagnostics, score_bucket_diagnostics, sequential_step_summary,
)
from app.schemas.market_data import MarketBar
from app.schemas.research import (
    PortfolioDailyResult, PortfolioEntryResult, PortfolioSimulationResult,
    PortfolioTradeResult, SkippedSignalResult,
)


SID_A = "00000000-0000-0000-0000-00000000000a"
SID_B = "00000000-0000-0000-0000-00000000000b"
SID_C = "00000000-0000-0000-0000-00000000000c"
D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def entry(sid=SID_A, signal=D1, *, score=75, size=10_000, provenance="BOTH"):
    return PortfolioEntryResult(
        security_id=sid, ticker={SID_A: "AAA", SID_B: "BBB", SID_C: "CCC"}[sid],
        provenance=provenance, signal_date=signal, entry_date=signal + timedelta(days=1),
        score=score, reference_entry_price=99.95, entry_price=100, quantity=size / 100,
        position_size=size, entry_slippage_cost=size * .0005,
        scheduled_exit_date=signal + timedelta(days=28),
    )


def trade(item, *, pnl=1000, lifecycle=None):
    net = pnl / item.position_size
    return PortfolioTradeResult(
        security_id=item.security_id, ticker=item.ticker, provenance=item.provenance,
        signal_date=item.signal_date, entry_date=item.entry_date,
        exit_date=item.scheduled_exit_date, score=item.score, quantity=item.quantity,
        reference_entry_price=item.reference_entry_price, entry_price=item.entry_price,
        reference_exit_price=item.entry_price * (1 + net) / .9995,
        exit_price=item.entry_price * (1 + net), exit_value=item.position_size + pnl,
        gross_return=net, net_return=net, pnl=pnl, commission=0,
        slippage_cost=10, entry_slippage_cost=5, exit_slippage_cost=5,
        holding_sessions=20, lifecycle_treatment=lifecycle,
    )


def skipped(sid, signal, reason, *, score=50, provenance="BOTH"):
    return SkippedSignalResult(
        security_id=sid, ticker={SID_A: "AAA", SID_B: "BBB", SID_C: "CCC"}[sid],
        provenance=provenance, signal_date=signal, entry_date=signal + timedelta(days=1),
        score=score, reason=reason,
    )


def result(*, entries=None, trades=None, skipped_rows=None, daily=None):
    entries = entries or []
    trades = trades or []
    daily = daily or [
        PortfolioDailyResult(
            session_date=D1, cash=100_000, positions_market_value=0,
            gross_exposure=0, net_exposure=0, total_equity=100_000,
            daily_return=0, cumulative_return=0, open_positions=0,
            benchmark_equity=100_000,
        ),
        PortfolioDailyResult(
            session_date=D2, cash=100_000 - sum(row.position_size for row in entries),
            positions_market_value=sum(row.position_size for row in entries),
            gross_exposure=sum(row.position_size for row in entries) / 100_000,
            net_exposure=sum(row.position_size for row in entries) / 100_000,
            total_equity=100_000, daily_return=0, cumulative_return=0,
            open_positions=len(entries), benchmark_equity=100_000,
            entries=[row.security_id for row in entries],
        ),
    ]
    return PortfolioSimulationResult(
        run_id="11111111-1111-1111-1111-111111111111", config_hash="a" * 64,
        source_backtest_run_id="22222222-2222-2222-2222-222222222222",
        warning=None, strategy_version="1.0.0", universe_mode="POINT_IN_TIME",
        start_date=D1, end_date=D2,
        configuration={"initial_capital": 100_000, "maximum_positions": 10,
                       "target_allocation": .1},
        metrics={"total_return": 0, "annualized_return_cagr": .1,
                 "annualized_volatility": .2, "maximum_drawdown": -.1,
                 "sharpe_ratio": .5, "sortino_ratio": .8, "calmar_ratio": 1,
                 "open_positions_at_research_end": len(entries) - len(trades)},
        benchmark_metrics={}, entries=entries, trades=trades, daily_equity=daily,
        skipped_signals=skipped_rows or [], created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def bars(sid=SID_A, close=110):
    return {sid: [MarketBar(
        ticker="AAA", timestamp=datetime(2024, 1, 3, tzinfo=UTC),
        open=close, high=close, low=close, close=close, volume=1_000,
    )]}


@pytest.mark.parametrize("score, expected", [
    (0, "0-20"), (19.999, "0-20"), (20, "20-40"), (40, "40-60"),
    (60, "60-80"), (80, "80-100"), (100, "80-100"),
])
def test_score_bucket_boundaries(score, expected):
    assert bucket(score) == expected


def test_signal_provenance_reconciles_available_accepted_and_rejected():
    a, b = entry(), entry(SID_B, provenance="FIXED_ONLY")
    fixed = result(entries=[a, b], skipped_rows=[
        skipped(SID_C, D3, "SIGNAL_SKIPPED_MAX_POSITIONS", provenance="FIXED_ONLY")
    ])
    pit = result(entries=[a])
    rows = provenance_diagnostics(
        fixed, pit, {(SID_A, D1), (SID_B, D1), (SID_C, D3)}, {(SID_A, D1)}
    )
    assert rows["BOTH"]["fixed"]["accepted"] == 1
    assert rows["FIXED_ONLY"]["fixed"]["rejected"] == 1
    assert rows["FIXED_ONLY"]["pit"]["eligibility"] == "NOT_APPLICABLE"


def test_both_four_way_and_opposite_reasons_reconcile():
    fixed = result(entries=[entry()], skipped_rows=[
        skipped(SID_B, D1, "SIGNAL_SKIPPED_ALREADY_HELD"),
        skipped(SID_C, D1, "SIGNAL_SKIPPED_MAX_POSITIONS"),
    ])
    pit = result(entries=[entry(SID_B)], skipped_rows=[
        skipped(SID_A, D1, "SIGNAL_SKIPPED_MAX_POSITIONS"),
        skipped(SID_C, D1, "SIGNAL_SKIPPED_ALREADY_HELD"),
    ])
    rows = both_four_way(fixed, pit, {(SID_A, D1), (SID_B, D1), (SID_C, D1)})
    assert rows["counts"] == {
        "ACCEPTED_IN_BOTH": 0, "ACCEPTED_FIXED_ONLY": 1,
        "ACCEPTED_PIT_ONLY": 1, "REJECTED_IN_BOTH": 1,
    }
    assert rows["fixed_only_acceptances"][0]["opposite_rejection"] == "SIGNAL_SKIPPED_MAX_POSITIONS"
    assert rows["status"] == "PASS"


def test_capacity_displacement_and_cash_constrained_entry_are_distinct():
    item = entry(size=8_000)
    portfolio = result(entries=[item], skipped_rows=[
        skipped(SID_B, D1, "SIGNAL_SKIPPED_MAX_POSITIONS")
    ])
    rows = capacity_and_cash(portfolio, [])
    assert rows["rejected_full"] == 1
    assert rows["cash_constrained_entries"]["count"] == 1
    assert rows["cash_constrained_entries"]["aggregate_shortfall"] == 2_000


def test_first_path_divergence_separates_signal_holdings_cash_and_equity_dates():
    item = entry()
    fixed_daily = [
        PortfolioDailyResult(session_date=D1, cash=100_000, positions_market_value=0,
            gross_exposure=0, net_exposure=0, total_equity=100_000, daily_return=0,
            cumulative_return=0, open_positions=0, benchmark_equity=100_000),
        PortfolioDailyResult(session_date=D2, cash=90_000, positions_market_value=10_100,
            gross_exposure=.1, net_exposure=.1, total_equity=100_100, daily_return=.001,
            cumulative_return=.001, open_positions=1, benchmark_equity=100_000,
            entries=[SID_A]),
    ]
    pit_daily = [fixed_daily[0], fixed_daily[1].model_copy(update={
        "cash": 100_000, "positions_market_value": 0, "total_equity": 100_000,
        "open_positions": 0, "entries": [],
    })]
    fixed = result(entries=[item], daily=fixed_daily)
    pit = result(daily=pit_daily)
    event = SimpleNamespace(
        security_id=SID_A, ticker=SID_A, signal_date=D1, entry_date=D2, score=75,
    )
    rows = first_divergence(fixed, pit, [event], [])
    assert rows["first_accepted_trade_difference"]["ticker"] == "AAA"
    assert rows["first_holdings_difference"] == D2.isoformat()
    assert rows["first_cash_difference"] == D2.isoformat()
    assert rows["first_equity_difference"] == D2.isoformat()


def test_common_trade_return_invariance_with_different_notionals_and_pnl():
    left, right = entry(size=10_000), entry(size=20_000)
    fixed = result(entries=[left], trades=[trade(left, pnl=1_000)])
    pit = result(entries=[right], trades=[trade(right, pnl=2_000)])
    rows = common_trade_effect(fixed, pit)
    assert rows["common_executed_positions"] == 1
    assert rows["different_position_sizes"] == 1
    assert rows["largest_notional_differences"][0]["return_pct_fixed"] == pytest.approx(10)
    assert rows["largest_notional_differences"][0]["pnl_pit"] == 2_000
    assert rows["status"] == "PASS"


def test_realized_plus_unrealized_and_provenance_pnl_identity():
    closed, opened = entry(), entry(SID_B, provenance="PIT_ONLY")
    closed_trade = trade(closed, pnl=1_000)
    daily = [PortfolioDailyResult(
        session_date=D2, cash=91_000, positions_market_value=11_000,
        gross_exposure=.108, net_exposure=.108, total_equity=102_000,
        daily_return=.02, cumulative_return=.02, open_positions=1,
        benchmark_equity=100_000,
    )]
    portfolio = result(entries=[closed, opened], trades=[closed_trade], daily=daily)
    rows = pnl_reconciliation(portfolio, bars(SID_B, 110))
    assert rows["realized_pnl"] == 1_000
    assert rows["unrealized_pnl"] == 1_000
    assert sum(value["total_pnl"] for value in rows["by_provenance"].values()) == 2_000
    assert rows["status"] == "PASS"


def test_concentration_uses_realized_and_initial_capital_denominators():
    one, two = entry(), entry(SID_B)
    portfolio = result(entries=[one, two], trades=[trade(one, pnl=2_000), trade(two, pnl=-500)])
    rows = concentration(portfolio)
    assert rows["total_realized_pnl"] == 1_500
    assert rows["pct_of_realized_pnl"]["top_1"] == pytest.approx(2_000 / 1_500)
    assert rows["pct_of_initial_capital"]["top_1"] == .02


def test_cross_arm_matching_classifies_rejected_and_unavailable():
    source_entry = entry()
    selected = concentration(result(entries=[source_entry], trades=[trade(source_entry)]))["top_10"]
    rejected_other = result(skipped_rows=[skipped(SID_A, D1, "SIGNAL_SKIPPED_MAX_POSITIONS")])
    assert cross_arm_matching(result(), rejected_other, selected, {(SID_A, D1)})[0]["classification"] == "REJECTED_IN_OTHER_ARM"
    assert cross_arm_matching(result(), result(), selected, set())[0]["classification"] == "NOT_ELIGIBLE_IN_OTHER_ARM"


def test_score_bucket_diagnostics_separates_open_positions():
    closed, opened = entry(score=80), entry(SID_B, score=20)
    rows = score_bucket_diagnostics(result(entries=[closed, opened], trades=[trade(closed)]))
    assert rows["80-100"]["closed_trades"] == 1
    assert rows["20-40"]["open_positions"] == 1


def test_existing_market_regime_definition_uses_past_only_volatility_thresholds():
    series = [MarketBar(
        ticker="SPY", timestamp=datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=index),
        open=100 + index, high=101 + index, low=99 + index, close=100 + index,
        volume=1_000,
    ) for index in range(220)]
    original = market_regime_labels(series)
    changed = [*series, MarketBar(
        ticker="SPY", timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        open=500, high=500, low=500, close=500, volume=1_000,
    )]
    assert original[series[210].timestamp.date()] == market_regime_labels(changed)[series[210].timestamp.date()]
    assert original[series[210].timestamp.date()]["sma200"] != "REGIME_UNAVAILABLE"
    assert original[series[100].timestamp.date()] == {
        "sma200": "REGIME_UNAVAILABLE", "sma50": "REGIME_UNAVAILABLE",
        "volatility": "REGIME_UNAVAILABLE",
    }


def test_lifecycle_reconciliation_retains_known_lower_bound():
    item = entry()
    portfolio = result(entries=[item], trades=[trade(item, lifecycle="ACQUISITION_LAST_LEGITIMATE_CLOSE")])
    rows = lifecycle_diagnostics(portfolio, {SID_A: {"category": "ACQUISITION"}})
    assert rows["positions"][0]["scheduled_exit"] == item.scheduled_exit_date.isoformat()
    assert rows["coverage_qualification"] == "KNOWN_LIFECYCLE_LOWER_BOUND"


def test_rejection_diagnostics_preserve_provenance_year_score_and_out_of_window():
    portfolio = result(skipped_rows=[
        skipped(SID_A, D1, "SIGNAL_SKIPPED_MAX_POSITIONS", score=20),
        skipped(SID_B, D3, "SIGNAL_SKIPPED_ENTRY_OUTSIDE_RESEARCH_WINDOW", score=80),
    ])
    rows = rejection_diagnostics(portfolio)
    assert rows["by_calendar_year"]["2024"]["REJECTED_PORTFOLIO_FULL"] == 1
    assert rows["by_score_bucket"]["80-100"]["REJECTED_OTHER"] == 1
    assert len(rows["out_of_window_next_open"]) == 1


def test_equity_path_and_calendar_summaries_are_reconciled():
    fixed_daily = [
        PortfolioDailyResult(session_date=D1, cash=100_000, positions_market_value=0,
            gross_exposure=0, net_exposure=0, total_equity=100_000, daily_return=0,
            cumulative_return=0, open_positions=0, benchmark_equity=100_000),
        PortfolioDailyResult(session_date=D2, cash=101_000, positions_market_value=0,
            gross_exposure=0, net_exposure=0, total_equity=101_000, daily_return=.01,
            cumulative_return=.01, open_positions=0, benchmark_equity=100_000),
    ]
    pit_daily = [fixed_daily[0], fixed_daily[1].model_copy(update={"total_equity": 99_000})]
    rows = equity_path(result(daily=fixed_daily), result(daily=pit_daily))
    assert rows["first_equity_divergence"]["session"] == D2.isoformat()
    assert rows["final_dollar_gap_pit_minus_fixed"] == -2_000
    assert rows["annual"]["FIXED_REBUILT"][0]["ending_equity"] == 101_000


def test_sequential_summary_and_phase3c_digest_are_deterministic_without_step3():
    portfolio = result()
    summary = sequential_step_summary(portfolio)
    payload = {"STEP_0": summary, "STEP_1": summary, "STEP_2": summary}
    assert summary["final_equity"] == 100_000
    assert "STEP_3" not in payload
    assert diagnostic_digest(payload) == diagnostic_digest(payload)
