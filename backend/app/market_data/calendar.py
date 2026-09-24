from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import exchange_calendars as xcals
import pandas as pd


class TradingCalendar(Protocol):
    name: str

    def is_trading_day(self, value: date) -> bool: ...
    def previous_trading_day(self, value: date) -> date: ...
    def next_trading_day(self, value: date) -> date: ...
    def trading_days_between(self, start_date: date, end_date: date) -> list[date]: ...
    def latest_complete_session(self, now: datetime, delay_minutes: int = 0) -> date: ...
    def session_offset(self, value: date, offset: int) -> date: ...


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

    def latest_complete_session(self, now: datetime, delay_minutes: int = 0) -> date:
        """Last XNYS session whose real close plus provider delay has elapsed."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        now_utc = now.astimezone(UTC)
        today = pd.Timestamp(now_utc.date())
        candidate = self._calendar.date_to_session(today, direction="previous")
        close = self._calendar.session_close(candidate).to_pydatetime()
        if now_utc >= close + timedelta(minutes=delay_minutes):
            return candidate.date()
        return self._calendar.previous_session(candidate).date()

    def sessions_ending_on(self, end_date: date, count: int) -> list[date]:
        if count < 1:
            raise ValueError("count must be positive")
        end = self._calendar.date_to_session(pd.Timestamp(end_date), direction="previous")
        start = self._calendar.session_offset(end, -(count - 1))
        sessions = self._calendar.sessions_in_range(start, end)
        return [session.date() for session in sessions]

    def session_offset(self, value: date, offset: int) -> date:
        session = self._calendar.date_to_session(pd.Timestamp(value), direction="previous")
        return self._calendar.session_offset(session, offset).date()


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
