from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.market_data import MarketBar


def make_bar(**overrides) -> MarketBar:
    values = {
        "ticker": "AAPL",
        "timestamp": datetime(2024, 1, 1, tzinfo=UTC),
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 100,
    }
    values.update(overrides)
    return MarketBar(**values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"low": 13.0}, "low cannot exceed high"),
        ({"open": 13.0}, "open must be within"),
        ({"close": 13.0}, "close must be within"),
    ],
)
def test_market_bar_rejects_impossible_ohlc(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        make_bar(**overrides)
