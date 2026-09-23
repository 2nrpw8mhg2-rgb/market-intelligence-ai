from datetime import UTC, date

from app.core.logging import get_logger
from app.database.repositories import MarketBarStore
from app.market_data.base import MarketDataProvider
from app.schemas.market_data import MarketBar

logger = get_logger(__name__)


class MarketDataService:
    def __init__(self, provider: MarketDataProvider, store: MarketBarStore) -> None:
        self._provider = provider
        self._store = store

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
        if self._covers_range(stored, start_date, end_date):
            logger.info(
                "market_data_cache_hit",
                extra={
                    "ticker": normalized_ticker,
                    "provider": self._provider.name,
                    "bar_count": len(stored),
                },
            )
            return stored

        fetched = await self._provider.get_daily_bars(
            normalized_ticker, start_date, end_date
        )
        normalized = self._normalize_and_validate(fetched, normalized_ticker)
        await self._store.upsert_daily_bars(normalized, provider=self._provider.name)
        return await self._store.list_daily_bars(
            normalized_ticker,
            start_date,
            end_date,
            provider=self._provider.name,
        )

    @staticmethod
    def _covers_range(bars: list[MarketBar], start_date: date, end_date: date) -> bool:
        if not bars:
            return False
        return bars[0].timestamp.date() <= start_date and bars[-1].timestamp.date() >= end_date

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
