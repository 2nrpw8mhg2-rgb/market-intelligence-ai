from datetime import UTC

import numpy as np
import pandas as pd
import pytest

from app.features import FeatureEngine, MarketDataQualityError


def make_frame(length: int = 240) -> pd.DataFrame:
    close = np.arange(1, length + 1, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=length, freq="D", tz=UTC),
            "open": close,
            "high": close + 1,
            "low": np.maximum(close - 1, 0.5),
            "close": close,
            "volume": np.arange(100, 100 + length),
        }
    )


def test_moving_averages_ema_rsi_macd_and_atr() -> None:
    result = FeatureEngine().calculate(make_frame())
    last = result.iloc[-1]

    assert last["SMA_20"] == pytest.approx(230.5)
    assert last["SMA_50"] == pytest.approx(215.5)
    assert last["SMA_200"] == pytest.approx(140.5)
    assert last["EMA_20"] == pytest.approx(230.5, rel=1e-9)
    assert last["RSI_14"] == pytest.approx(100.0)
    assert last["MACD"] == pytest.approx(7.0, rel=1e-7)
    assert last["MACD_SIGNAL"] == pytest.approx(7.0, rel=1e-6)
    assert last["MACD_HISTOGRAM"] == pytest.approx(0.0, abs=1e-6)
    assert last["ATR_14"] == pytest.approx(2.0)


def test_returns_volume_levels_volatility_and_momentum() -> None:
    result = FeatureEngine().calculate(make_frame())
    last = result.iloc[-1]

    assert last["RETURN_1D"] == pytest.approx(240 / 239 - 1)
    assert last["RETURN_5D"] == pytest.approx(240 / 235 - 1)
    assert last["RETURN_20D"] == pytest.approx(240 / 220 - 1)
    assert last["AVG_VOLUME_20D"] == pytest.approx(329.5)
    assert last["RELATIVE_VOLUME"] == pytest.approx(339 / 329.5)
    assert last["PREVIOUS_HIGH_20D"] == pytest.approx(240.0)
    assert last["PREVIOUS_HIGH_50D"] == pytest.approx(240.0)
    assert last["PREVIOUS_LOW_20D"] == pytest.approx(219.0)
    expected_volatility = result["RETURN_1D"].iloc[-20:].std(ddof=1)
    assert last["VOLATILITY_20D"] == pytest.approx(expected_volatility)
    assert last["MOMENTUM_20D"] == pytest.approx(240 / 220 - 1)


def test_warm_up_periods_are_not_shortened() -> None:
    result = FeatureEngine().calculate(make_frame(50))

    assert result["SMA_20"].iloc[:19].isna().all()
    assert result["SMA_20"].iloc[19] == pytest.approx(10.5)
    assert result["SMA_50"].iloc[:49].isna().all()
    assert result["SMA_50"].iloc[49] == pytest.approx(25.5)
    assert result["SMA_200"].isna().all()
    assert result["PREVIOUS_HIGH_20D"].iloc[:20].isna().all()
    assert result["PREVIOUS_HIGH_20D"].iloc[20] == pytest.approx(21.0)


def test_future_changes_do_not_modify_historical_features() -> None:
    engine = FeatureEngine()
    original = make_frame(80)
    mutated = original.copy()
    mutated.loc[79, ["open", "high", "low", "close", "volume"]] = [500, 510, 490, 505, 9999]

    before = engine.calculate(original).iloc[:79]
    after = engine.calculate(mutated).iloc[:79]

    pd.testing.assert_frame_equal(before, after)
    assert engine.calculate(mutated).iloc[79]["PREVIOUS_HIGH_20D"] == pytest.approx(80.0)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda df: df.drop(columns=["close"]), "missing required columns"),
        (lambda df: pd.concat([df, df.iloc[[-1]]], ignore_index=True), "timestamps must be unique"),
        (lambda df: df.iloc[::-1].reset_index(drop=True), "ordered chronologically"),
        (lambda df: df.assign(open=-1), "open must be greater than zero"),
        (lambda df: df.assign(volume=-1), "volume must not be negative"),
        (lambda df: df.assign(high=df["low"] * 0.5), "high must not be lower"),
        (lambda df: df.assign(close=np.nan), "close must not contain NaN"),
    ],
)
def test_invalid_market_data_is_rejected(mutation, message) -> None:
    with pytest.raises(MarketDataQualityError, match=message):
        FeatureEngine().calculate(mutation(make_frame(30)))


def test_empty_frame_preserves_feature_schema() -> None:
    empty = make_frame(1).iloc[:0]

    result = FeatureEngine().calculate(empty)

    assert result.empty
    assert set(FeatureEngine.FEATURE_COLUMNS).issubset(result.columns)
