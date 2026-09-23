from abc import ABC, abstractmethod
from datetime import date

from app.schemas.market_data import MarketBar


class MarketDataProvider(ABC):
    """Provider-independent contract for historical market data."""

    name: str

    @abstractmethod
    async def get_daily_bars(
        self, ticker: str, start_date: date, end_date: date
    ) -> list[MarketBar]:
        """Return ascending, completed daily OHLCV bars for one ticker."""
        raise NotImplementedError
