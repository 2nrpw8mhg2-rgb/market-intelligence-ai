from datetime import date

import pytest

from app.market_data.calendar import NYSETradingCalendar, group_consecutive_sessions


@pytest.fixture(scope="module")
def calendar() -> NYSETradingCalendar:
    return NYSETradingCalendar()


def test_nyse_calendar_distinguishes_session_weekend_and_holiday(calendar) -> None:
    assert calendar.is_trading_day(date(2024, 7, 3))
    assert not calendar.is_trading_day(date(2024, 7, 4))
    assert not calendar.is_trading_day(date(2024, 7, 6))


def test_previous_and_next_trading_day(calendar) -> None:
    assert calendar.previous_trading_day(date(2024, 1, 1)) == date(2023, 12, 29)
    assert calendar.next_trading_day(date(2024, 1, 1)) == date(2024, 1, 2)
    assert calendar.previous_trading_day(date(2024, 1, 2)) == date(2023, 12, 29)
    assert calendar.next_trading_day(date(2024, 1, 2)) == date(2024, 1, 3)


def test_trading_days_between_excludes_holiday(calendar) -> None:
    assert calendar.trading_days_between(date(2024, 7, 3), date(2024, 7, 5)) == [
        date(2024, 7, 3),
        date(2024, 7, 5),
    ]


def test_calendar_rejects_inverted_interval(calendar) -> None:
    with pytest.raises(ValueError, match="start_date"):
        calendar.trading_days_between(date(2024, 7, 5), date(2024, 7, 3))


def test_missing_sessions_are_grouped_by_market_adjacency() -> None:
    sessions = [
        date(2024, 7, 1),
        date(2024, 7, 2),
        date(2024, 7, 3),
        date(2024, 7, 5),
    ]

    groups = group_consecutive_sessions(
        [date(2024, 7, 2), date(2024, 7, 3), date(2024, 7, 5)], sessions
    )

    assert groups == [(date(2024, 7, 2), date(2024, 7, 5))]
