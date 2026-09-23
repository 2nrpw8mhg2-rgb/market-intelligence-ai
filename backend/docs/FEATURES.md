# Quantitative feature definitions

All features are calculated on daily OHLCV bars sorted in ascending UTC timestamp order. No missing values are filled. A feature remains `NaN` until its full warm-up period is available.

| Feature | Definition | Lookback / warm-up | Interpretation |
| --- | --- | --- | --- |
| `SMA_20` | Arithmetic mean of the current close and previous 19 closes | 20 bars | Short-term price level |
| `SMA_50` | Arithmetic mean of 50 closes | 50 bars | Medium-term price level |
| `SMA_200` | Arithmetic mean of 200 closes | 200 bars | Long-term price level |
| `EMA_20` | `close.ewm(span=20, adjust=False)` | 20 bars | Exponentially weighted short-term price level |
| `RSI_14` | Wilder-smoothed gains and losses: `RS=EWMA(gain, alpha=1/14) / EWMA(loss, alpha=1/14)`; `RSI=100-100/(1+RS)` | 14 price changes (15 bars) | Bounded momentum oscillator. All gains = 100; flat series = 50 |
| `MACD` | `EMA_12(close) - EMA_26(close)`, both with `adjust=False` | 26 bars | Difference between fast and slow trend |
| `MACD_SIGNAL` | 9-period EMA of MACD with `adjust=False` | 34 bars | Smoothed MACD |
| `MACD_HISTOGRAM` | `MACD - MACD_SIGNAL` | 34 bars | Distance between MACD and signal |
| `ATR_14` | Wilder EWMA (`alpha=1/14`) of true range. `TR=max(high-low, abs(high-prev_close), abs(low-prev_close))` | 14 bars | Absolute price volatility |
| `RETURN_1D` | `close / close.shift(1) - 1` | 2 bars | One-session simple return |
| `RETURN_5D` | `close / close.shift(5) - 1` | 6 bars | Five-session simple return |
| `RETURN_20D` | `close / close.shift(20) - 1` | 21 bars | Twenty-session simple return |
| `AVG_VOLUME_20D` | Arithmetic mean of volume including the current session | 20 bars | Recent baseline volume |
| `RELATIVE_VOLUME` | `volume / AVG_VOLUME_20D`; zero denominator yields `NaN` | 20 bars | Current volume versus recent baseline |
| `PREVIOUS_HIGH_20D` | `high.shift(1).rolling(20).max()` | 21 bars | Highest high in the 20 completed sessions before the current one |
| `PREVIOUS_HIGH_50D` | `high.shift(1).rolling(50).max()` | 51 bars | Highest high in the 50 completed sessions before the current one |
| `PREVIOUS_LOW_20D` | `low.shift(1).rolling(20).min()` | 21 bars | Lowest low in the 20 completed sessions before the current one |
| `VOLATILITY_20D` | Sample standard deviation (`ddof=1`) of 1-day simple returns | 20 returns (21 bars) | Unannualized realized daily volatility |
| `MOMENTUM_20D` | `close / close.shift(20) - 1` | 21 bars | Twenty-session price momentum; numerically equal to `RETURN_20D` |

## Look-ahead policy

All rolling and exponential indicators at timestamp `t` depend only on observations at or before `t`. Previous-high/low features explicitly shift by one bar, so they use only bars strictly before `t`. Future rows cannot change already calculated historical features.

Signals based on the closing bar are outside this phase. A later strategy engine must not execute at the same close that generated a signal unless an explicit, realistic execution model proves that price was available.

## Data quality policy

The engine rejects the complete batch with `MarketDataQualityError` when:

- a required column is absent;
- a timestamp is invalid, duplicated, or out of chronological order;
- OHLCV contains non-numeric values, `NaN`, or infinity;
- any OHLC price is non-positive;
- volume is negative;
- `high < low`;
- open or close lies outside the low/high interval.

Timestamps are parsed and normalized to UTC. Numeric types may be normalized by Pandas, but financially invalid values are never corrected silently. Feature warm-up `NaN` values are expected output and are serialized as JSON `null` by the API.

## Universe limitation

Universe memberships store `valid_from`, optional `valid_to`, and `source`, enabling point-in-time queries. A current-only S&P 500 import does **not** reconstruct historical membership and therefore does not eliminate survivorship bias. Backtests must label that limitation until an authoritative historical constituent source is loaded.
