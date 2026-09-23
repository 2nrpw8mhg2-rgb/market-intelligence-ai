from dataclasses import dataclass
from datetime import UTC, date

from app.core.logging import get_logger
from app.database.repositories import MarketBarStore
from app.market_data.base import MarketDataProvider
from app.market_data.calendar import NYSETradingCalendar, TradingCalendar, group_consecutive_sessions
from app.schemas.market_data import MarketBar

logger = get_logger(__name__)


class MarketSessionError(ValueError):
    pass


@dataclass(frozen=True)
class DataCompleteness:
    start_date: date
    end_date: date
    expected_sessions: tuple[date, ...]
    available_sessions: tuple[date, ...]
    missing_sessions: tuple[date, ...]
    unexpected_sessions: tuple[date, ...]

    @property
    def is_complete(self) -> bool:
        return not self.missing_sessions and not self.unexpected_sessions


class MarketDataService:
    def __init__(
        self,
        provider: MarketDataProvider,
        store: MarketBarStore,
        calendar: TradingCalendar | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._calendar = calendar or NYSETradingCalendar()

    async def get_or_ingest_daily_bars(
        self, ticker: str, start_date: date, end_date: date
    ) -> list[MarketBar]:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        normalized_ticker = ticker.strip().upper()
        stored = await self._store.list_daily_bars(
            normalized_ticker,
            start_date,
            end_date,
            provider=self._provider.name,
        )
        completeness = self.assess_daily_completeness(stored, start_date, end_date)
        if completeness.unexpected_sessions:
            raise MarketSessionError(
                "stored daily bars contain non-trading sessions: "
                + ", ".join(map(str, completeness.unexpected_sessions))
            )
        if completeness.is_complete:
            logger.info(
                "market_data_cache_hit",
                extra={
                    "ticker": normalized_ticker,
                    "provider": self._provider.name,
                    "bar_count": len(stored),
                },
            )
            return stored

        expected = list(completeness.expected_sessions)
        for missing_start, missing_end in group_consecutive_sessions(
            completeness.missing_sessions, expected
        ):
            fetched = await self._provider.get_daily_bars(
                normalized_ticker, missing_start, missing_end
            )
            normalized = self._normalize_and_validate(fetched, normalized_ticker)
            self._reject_non_trading_bars(normalized)
            await self._store.upsert_daily_bars(normalized, provider=self._provider.name)
        return await self._store.list_daily_bars(
            normalized_ticker,
            start_date,
            end_date,
            provider=self._provider.name,
        )

    def assess_daily_completeness(
        self, bars: list[MarketBar], start_date: date, end_date: date
    ) -> DataCompleteness:
        expected = tuple(self._calendar.trading_days_between(start_date, end_date))
        available = tuple(sorted({bar.timestamp.date() for bar in bars}))
        expected_set = set(expected)
        available_set = set(available)
        return DataCompleteness(
            start_date=start_date,
            end_date=end_date,
            expected_sessions=expected,
            available_sessions=available,
            missing_sessions=tuple(day for day in expected if day not in available_set),
            unexpected_sessions=tuple(day for day in available if day not in expected_set),
        )

    def _reject_non_trading_bars(self, bars: list[MarketBar]) -> None:
        invalid = [bar.timestamp.date() for bar in bars if not self._calendar.is_trading_day(bar.timestamp.date())]
        if invalid:
            raise MarketSessionError(
                "provider returned bars for non-trading sessions: "
                + ", ".join(map(str, invalid))
            )

    @staticmethod
    def _normalize_and_validate(
        bars: list[MarketBar], expected_ticker: str
    ) -> list[MarketBar]:
        normalized: list[MarketBar] = []
        seen: set[object] = set()
        previous_timestamp = None
        for bar in bars:
            if bar.ticker != expected_ticker:
                raise ValueError("provider returned an unexpected ticker")
            timestamp = bar.timestamp.astimezone(UTC)
            if timestamp in seen:
                raise ValueError("provider returned duplicate timestamps")
            if previous_timestamp and timestamp < previous_timestamp:
                raise ValueError("provider returned bars out of chronological order")
            seen.add(timestamp)
            previous_timestamp = timestamp
            normalized.append(bar.model_copy(update={"timestamp": timestamp}))
        return normalized
