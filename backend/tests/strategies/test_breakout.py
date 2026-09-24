import pytest

from app.schemas.scanner import BreakoutStrategyParameters
from app.strategies import BreakoutVolumeStrategy


def valid_row(**overrides):
    row = {
        "close": 110, "PREVIOUS_HIGH_20D": 100, "RELATIVE_VOLUME": 2,
        "SMA_50": 90, "SMA_200": 80, "AVG_DOLLAR_VOLUME_20D": 20_000_000,
    }
    row.update(overrides)
    return row


def test_breakout_requires_strictly_higher_close() -> None:
    strategy = BreakoutVolumeStrategy(BreakoutStrategyParameters())
    assert strategy.evaluate(valid_row())[0]
    assert not strategy.evaluate(valid_row(close=100))[0]
    assert not strategy.evaluate(valid_row(close=99))[0]


@pytest.mark.parametrize("overrides", [
    {"RELATIVE_VOLUME": 1.49}, {"close": 89}, {"SMA_50": 79},
    {"AVG_DOLLAR_VOLUME_20D": 9_999_999}, {"close": 4},
])
def test_all_filters_are_mandatory(overrides) -> None:
    assert not BreakoutVolumeStrategy(BreakoutStrategyParameters()).evaluate(valid_row(**overrides))[0]


def test_missing_features_are_rejected() -> None:
    assert not BreakoutVolumeStrategy(BreakoutStrategyParameters()).evaluate({})[0]
