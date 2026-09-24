# BREAKOUT_20D_VOLUME scanner

The scanner identifies quantitative conditions; it does not recommend trades or estimate success probabilities.

## Required conditions

All conditions must be true on a completed daily session:

1. `close > PREVIOUS_HIGH_20D`, where `PREVIOUS_HIGH_20D = high.shift(1).rolling(20).max()`.
2. `RELATIVE_VOLUME >= min_relative_volume` (default 1.5), where `RELATIVE_VOLUME = current volume / mean(volume.shift(1), 20)`.
3. `close > SMA_50`.
4. `SMA_50 > SMA_200`.
5. `AVG_DOLLAR_VOLUME_20D >= 10,000,000`, where the average is `mean((close × volume).shift(1), 20)`.
6. `close >= 5`.

The supported lookbacks are deliberately fixed at 20/50/200. Requests containing unsupported periods are rejected rather than silently ignored.

## Score

Only opportunities that pass every filter are ranked. Each input is clipped to `[0, 1]` before weighting:

- Breakout (30): `clip(breakout_fraction / 0.10)`.
- Relative volume (25): `clip((relative_volume - threshold) / 2.5)`.
- Momentum (20): `clip(momentum_20d / 0.30)`.
- Trend (15): `clip(((close / SMA50) - 1) / 0.20)`.
- Liquidity (10): `clip(log10(avg_dollar_volume / minimum))`.

The weighted points sum to a deterministic score from 0 to 100. It is an ordering measure, not probability, AI confidence or investment advice.

## Sessions and universe

`LATEST` uses the most recent XNYS session whose actual close plus `PROVIDER_DATA_DELAY_MINUTES` has elapsed. This handles weekends, holidays and early closes. It reads the latest sourced current-universe snapshot. `HISTORICAL` uses the requested session (or the immediately preceding session for a non-trading date) and queries genuine point-in-time membership. An empty historical universe returns `UNIVERSE_DATA_UNAVAILABLE`; current constituents are never substituted.

For every symbol the scanner reads stored Massive bars only up to the target session. It rejects fewer than 200 observations, absent target-session data and missing required features. One ticker failure does not stop the batch.

## Idempotency

The configuration is serialized canonically and SHA-256 hashed. Opportunity identity is:

```text
symbol + session + strategy version + configuration hash
```

Re-running the same configuration updates the record. Different configurations remain separate. Provider revisions update the matching opportunity rather than creating a duplicate.

## API

```http
POST /api/v1/scan
Content-Type: application/json

{
  "mode": "HISTORICAL",
  "strategy": "BREAKOUT_20D_VOLUME",
  "universe": "SP500",
  "as_of_date": "2026-09-23",
  "parameters": {
    "breakout_lookback": 20,
    "min_relative_volume": 1.5,
    "trend_sma_short": 50,
    "trend_sma_long": 200,
    "min_avg_dollar_volume": 10000000,
    "min_price": 5
  }
}
```

Results are queried with `GET /api/v1/opportunities` or `GET /api/v1/opportunities/{ticker}`. The list endpoint supports `date`, `ticker`, `strategy`, `universe`, `min_score`, `limit`, and `offset`.

Each persisted opportunity includes a deterministic structured explanation of breakout, volume, trend, liquidity and score. The text is generated exclusively from the stored numerical inputs and contains no probabilistic or generative claims.

## Limitations

- No real S&P 500 scan is possible until authoritative memberships and sufficient OHLCV are loaded.
- Results do not model corporate actions beyond Massive's split-adjusted bars and do not include dividends.
- There is no backtesting, portfolio logic, ML or order execution.
