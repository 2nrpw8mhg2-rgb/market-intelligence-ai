from datetime import UTC, date, datetime

import exchange_calendars as xcals
import pandas as pd

from app.prospective_registry.models import RegistryStatus


class ProspectiveTiming:
    """XNYS-aware registration deadlines; never assumes a local wall-clock open."""

    def __init__(self) -> None:
        self._calendar = xcals.get_calendar("XNYS")

    def session_close(self, session: date) -> datetime:
        timestamp = pd.Timestamp(session)
        if not self._calendar.is_session(timestamp):
            raise ValueError(f"{session} is not an XNYS session")
        return self._calendar.session_close(timestamp).to_pydatetime().astimezone(UTC)

    def next_open(self, session: date) -> datetime:
        timestamp = pd.Timestamp(session)
        if not self._calendar.is_session(timestamp):
            raise ValueError(f"{session} is not an XNYS session")
        following = self._calendar.next_session(timestamp)
        return self._calendar.session_open(following).to_pydatetime().astimezone(UTC)

    def classify(
        self, *, session: date, data_ready_at: datetime, registered_at: datetime,
    ) -> tuple[RegistryStatus, datetime]:
        if data_ready_at.tzinfo is None or registered_at.tzinfo is None:
            raise ValueError("timing inputs must be timezone-aware")
        ready = data_ready_at.astimezone(UTC)
        registered = registered_at.astimezone(UTC)
        close = self.session_close(session)
        next_open = self.next_open(session)
        if ready < close:
            raise ValueError("data cannot be declared ready before the session close")
        if registered < ready:
            raise ValueError("registration cannot precede data readiness")
        return (
            RegistryStatus.TIMELY if registered < next_open else RegistryStatus.LATE,
            next_open,
        )
