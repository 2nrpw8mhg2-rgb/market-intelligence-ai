from datetime import UTC, date, datetime

import pytest

from app.backtesting import BacktestEngine, canonical_config
from app.market_data.calendar import NYSETradingCalendar
from app.schemas.backtesting import (
    FIXED_UNIVERSE_WARNING,
    BacktestRequest,
    EntryModel,
    UniverseMode,
)
from app.schemas.market_data import MarketBar


CALENDAR = NYSETradingCalendar()


def bars(ticker: str, *, mutate_after: date | None = None) -> list[MarketBar]:
    sessions = CALENDAR.trading_days_between(date(2024, 1, 2), date(2025, 5, 30))
    result = []
    for index, session in enumerate(sessions):
        close = 100 + index * 0.10
        volume = 100_000.0
        if index == 250:
            close += 5
            volume = 300_000.0
        if mutate_after and session > mutate_after:
            close *= 2
        result.append(MarketBar(
            ticker=ticker,
            timestamp=datetime.combine(session, datetime.min.time(), tzinfo=UTC),
            open=close - 0.25,
            high=close + 0.75,
            low=close - 0.75,
            close=close,
            volume=volume,
        ))
    return result


def request(**updates) -> BacktestRequest:
    values = {
        "universe_mode": UniverseMode.FIXED_UNIVERSE_RESEARCH,
        "tickers": ["TEST"],
        "start_date": date(2024, 12, 20),
        "end_date": date(2025, 1, 31),
        "entry_model": EntryModel.SIGNAL_CLOSE,
    }
    values.update(updates)
    return BacktestRequest(**values)


def execute(**updates):
    item = request(**updates)
    stock = bars("TEST")
    benchmark = bars("SPY")
    return BacktestEngine(CALENDAR).run(
        item, {"TEST": stock}, benchmark,
        is_member=lambda _ticker, _session: True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_signal_is_causal_when_future_prices_are_mutated() -> None:
    baseline = execute()
    assert baseline.event_count == 1
    signal_date = baseline.events[0].signal_date
    mutated = BacktestEngine(CALENDAR).run(
        request(), {"TEST": bars("TEST", mutate_after=signal_date)}, bars("SPY"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    first = baseline.events[0]
    second = mutated.events[0]
    assert (first.signal_date, first.score, first.previous_high_20d) == (
        second.signal_date, second.score, second.previous_high_20d
    )
    assert first.outcomes[1].stock_return != second.outcomes[1].stock_return


@pytest.mark.parametrize("entry_model", [EntryModel.SIGNAL_CLOSE, EntryModel.NEXT_OPEN])
def test_entry_models_and_all_exact_session_horizons(entry_model: EntryModel) -> None:
    result = execute(entry_model=entry_model)
    event = result.events[0]
    expected_entry = (
        event.signal_date if entry_model is EntryModel.SIGNAL_CLOSE
        else CALENDAR.session_offset(event.signal_date, 1)
    )
    assert event.entry_date == expected_entry
    assert [outcome.horizon for outcome in event.outcomes] == [1, 5, 10, 20, 60]
    assert all(outcome.stock_return is not None for outcome in event.outcomes)


def test_benchmark_excess_returns_and_excursions_are_calculated() -> None:
    event = execute().events[0]
    outcome = next(item for item in event.outcomes if item.horizon == 20)
    assert outcome.excess_return == pytest.approx(
        outcome.stock_return - outcome.benchmark_return
    )
    assert outcome.mfe is not None and outcome.mfe > outcome.mae


def test_incomplete_forward_window_is_explicit_not_silently_shortened() -> None:
    result = execute(start_date=date(2025, 5, 29), end_date=date(2025, 5, 30))
    assert result.event_count == 0
    original = execute()
    event_date = original.events[0].signal_date
    stock = [bar for bar in bars("TEST") if bar.timestamp.date() <= CALENDAR.session_offset(event_date, 10)]
    result = BacktestEngine(CALENDAR).run(request(), {"TEST": stock}, bars("SPY"))
    assert next(item for item in result.events[0].outcomes if item.horizon == 10).forward_data_complete
    assert not next(item for item in result.events[0].outcomes if item.horizon == 20).forward_data_complete


def test_universe_modes_and_survivorship_warning_are_explicit() -> None:
    fixed = execute()
    assert fixed.survivorship_bias_warning == FIXED_UNIVERSE_WARNING
    pit_request = request(universe_mode=UniverseMode.POINT_IN_TIME)
    excluded = BacktestEngine(CALENDAR).run(
        pit_request, {"TEST": bars("TEST")}, bars("SPY"),
        is_member=lambda _ticker, _session: False,
    )
    assert excluded.event_count == 0
    assert excluded.survivorship_bias_warning is None


def test_configuration_hash_and_results_are_reproducible() -> None:
    first = execute()
    second = execute()
    assert canonical_config(request()) == canonical_config(request())
    assert first.model_dump(exclude={"created_at"}) == second.model_dump(exclude={"created_at"})
    assert first.statistics_by_horizon["20"]["number_of_events"] == 1
    assert first.statistics_by_score_bucket
