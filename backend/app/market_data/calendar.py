from collections.abc import Iterable
from datetime import date
from typing import Protocol

import exchange_calendars as xcals
import pandas as pd


class TradingCalendar(Protocol):
    name: str

    def is_trading_day(self, value: date) -> bool: ...
    def previous_trading_day(self, value: date) -> date: ...
    def next_trading_day(self, value: date) -> date: ...
    def trading_days_between(self, start_date: date, end_date: date) -> list[date]: ...


class NYSETradingCalendar:
    """Regular XNYS sessions backed by exchange_calendars."""

    name = "XNYS"

    def __init__(self) -> None:
        self._calendar = xcals.get_calendar(self.name)

    def is_trading_day(self, value: date) -> bool:
        return bool(self._calendar.is_session(pd.Timestamp(value)))

    def previous_trading_day(self, value: date) -> date:
        timestamp = pd.Timestamp(value)
        if self._calendar.is_session(timestamp):
            return self._calendar.previous_session(timestamp).date()
        return self._calendar.date_to_session(timestamp, direction="previous").date()

    def next_trading_day(self, value: date) -> date:
        timestamp = pd.Timestamp(value)
        if self._calendar.is_session(timestamp):
            return self._calendar.next_session(timestamp).date()
        return self._calendar.date_to_session(timestamp, direction="next").date()

    def trading_days_between(self, start_date: date, end_date: date) -> list[date]:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        sessions = self._calendar.sessions_in_range(
            pd.Timestamp(start_date), pd.Timestamp(end_date)
        )
        return [session.date() for session in sessions]


def group_consecutive_sessions(
    missing: Iterable[date], expected_sessions: list[date]
) -> list[tuple[date, date]]:
    missing_set = set(missing)
    groups: list[list[date]] = []
    last_missing_position: int | None = None
    for position, session in enumerate(expected_sessions):
        if session not in missing_set:
            continue
        if not groups or last_missing_position is None or position != last_missing_position + 1:
            groups.append([session])
        else:
            groups[-1].append(session)
        last_missing_position = position
    return [(group[0], group[-1]) for group in groups]
