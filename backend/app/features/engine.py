from collections.abc import Iterable

import numpy as np
import pandas as pd


class MarketDataQualityError(ValueError):
    """Raised when OHLCV data is unsafe for quantitative calculations."""


class FeatureEngine:
    REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
    FEATURE_COLUMNS = (
        "SMA_20",
        "SMA_50",
        "SMA_200",
        "EMA_20",
        "RSI_14",
        "MACD",
        "MACD_SIGNAL",
        "MACD_HISTOGRAM",
        "ATR_14",
        "RETURN_1D",
        "RETURN_5D",
        "RETURN_20D",
        "AVG_VOLUME_20D",
        "RELATIVE_VOLUME",
        "AVG_DOLLAR_VOLUME_20D",
        "PREVIOUS_HIGH_20D",
        "PREVIOUS_HIGH_50D",
        "PREVIOUS_LOW_20D",
        "VOLATILITY_20D",
        "MOMENTUM_20D",
    )

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        data = self._validate_and_copy(frame)
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        volume = data["volume"].astype(float)

        data["SMA_20"] = close.rolling(20, min_periods=20).mean()
        data["SMA_50"] = close.rolling(50, min_periods=50).mean()
        data["SMA_200"] = close.rolling(200, min_periods=200).mean()
        data["EMA_20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        average_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        average_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        relative_strength = average_gain / average_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + relative_strength))
        rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100.0)
        rsi = rsi.mask((average_loss == 0) & (average_gain == 0), 50.0)
        data["RSI_14"] = rsi

        ema_12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema_26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        data["MACD"] = ema_12 - ema_26
        data["MACD_SIGNAL"] = data["MACD"].ewm(
            span=9, adjust=False, min_periods=9
        ).mean()
        data["MACD_HISTOGRAM"] = data["MACD"] - data["MACD_SIGNAL"]

        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1, skipna=True)
        data["ATR_14"] = true_range.ewm(
            alpha=1 / 14, adjust=False, min_periods=14
        ).mean()

        returns_1d = close.pct_change(fill_method=None)
        data["RETURN_1D"] = returns_1d
        data["RETURN_5D"] = close.pct_change(5, fill_method=None)
        data["RETURN_20D"] = close.pct_change(20, fill_method=None)
        data["AVG_VOLUME_20D"] = volume.shift(1).rolling(20, min_periods=20).mean()
        data["RELATIVE_VOLUME"] = volume / data["AVG_VOLUME_20D"].replace(0, np.nan)
        data["AVG_DOLLAR_VOLUME_20D"] = (
            (close * volume).shift(1).rolling(20, min_periods=20).mean()
        )
        data["PREVIOUS_HIGH_20D"] = high.shift(1).rolling(20, min_periods=20).max()
        data["PREVIOUS_HIGH_50D"] = high.shift(1).rolling(50, min_periods=50).max()
        data["PREVIOUS_LOW_20D"] = low.shift(1).rolling(20, min_periods=20).min()
        data["VOLATILITY_20D"] = returns_1d.rolling(20, min_periods=20).std(ddof=1)
        data["MOMENTUM_20D"] = close / close.shift(20) - 1
        return data

    def _validate_and_copy(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = sorted(set(self.REQUIRED_COLUMNS) - set(frame.columns))
        if missing:
            raise MarketDataQualityError(f"missing required columns: {', '.join(missing)}")
        data = frame.copy(deep=True)
        if data.empty:
            for column in self.FEATURE_COLUMNS:
                data[column] = pd.Series(dtype=float)
            return data

        try:
            data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True, errors="raise")
        except (ValueError, TypeError) as exc:
            raise MarketDataQualityError("timestamps must be valid datetimes") from exc

        if data["timestamp"].duplicated().any():
            raise MarketDataQualityError("timestamps must be unique")
        if not data["timestamp"].is_monotonic_increasing:
            raise MarketDataQualityError("data must be ordered chronologically")

        numeric_columns: Iterable[str] = ("open", "high", "low", "close", "volume")
        for column in numeric_columns:
            try:
                data[column] = pd.to_numeric(data[column], errors="raise")
            except (ValueError, TypeError) as exc:
                raise MarketDataQualityError(f"{column} must be numeric") from exc
            if not np.isfinite(data[column].to_numpy(dtype=float)).all():
                raise MarketDataQualityError(f"{column} must not contain NaN or infinity")

        for column in ("open", "high", "low", "close"):
            if (data[column] <= 0).any():
                raise MarketDataQualityError(f"{column} must be greater than zero")
        if (data["volume"] < 0).any():
            raise MarketDataQualityError("volume must not be negative")
        if (data["high"] < data["low"]).any():
            raise MarketDataQualityError("high must not be lower than low")
        if ((data["open"] > data["high"]) | (data["open"] < data["low"])).any():
            raise MarketDataQualityError("open must be within the low/high range")
        if ((data["close"] > data["high"]) | (data["close"] < data["low"])).any():
            raise MarketDataQualityError("close must be within the low/high range")
        return data
