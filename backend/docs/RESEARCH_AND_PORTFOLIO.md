# Phase 6: score, regimes and long portfolio research

Phase 6 consumes an existing `NEXT_OPEN` backtest. It never downloads market data,
changes `BREAKOUT_20D_VOLUME`, or changes its score weights. Studies based on the
current S&P 500 snapshot remain labelled `FIXED_UNIVERSE_RESEARCH` and therefore
contain survivorship bias.

## Score research

The engine reports 0–20, 20–40, 40–60, 60–80 and 80–100 score buckets at 5, 10,
20 and 60 sessions, by year, and correlations/retrospective quintiles for each
score component. Mean confidence intervals use the normal approximation
`mean ± 1.96 × sample standard deviation / sqrt(n)`. Overlapping events are not
claimed to be independent. Dependency variants retain all events or retain the
first signal followed by a 20/60 XNYS-session exclusion window; a signal exactly
on the boundary is allowed.

## Market regimes

SPY SMA50, SMA200 and 20-session annualized realized volatility use information
through the signal close only. Volatility tercile thresholds are expanding and
use only earlier SPY sessions. They advance once per session, so multiple signals
on the same date receive the same classification. Insufficient history is
reported as `REGIME_UNAVAILABLE`.

## Portfolio convention

The simulator is generic, long-only and permits fractional shares. A signal at
the close of T enters at the open of T+1. Candidate order is score descending,
ticker ascending; the comparison baseline uses ticker ascending. Entries happen
using cash carried from the previous close. Timed exits happen at the current
close, so their proceeds cannot finance that morning's entries. A missing close
carries the last valid mark; a timed exit with no bar waits for the next valid
close. No price is replaced by zero.

Slippage is adverse at both ends and commissions are applied to both ends.
SPY is a split-adjusted price benchmark, not a dividend total-return index.
Sharpe uses annualized mean daily return over sample standard deviation; Sortino
uses downside deviation; CAGR is omitted for periods shorter than one year.

## Commands

```bash
python -m app.cli.run_score_research --backtest-run-id UUID --output reports/score.json
python -m app.cli.run_market_regime_research --backtest-run-id UUID --output reports/regimes.json
python -m app.cli.run_portfolio_simulation --backtest-run-id UUID --maximum-positions 10 --target-allocation .1 --holding-period 20 --slippage-bps 5 --output reports/portfolio.json
```

All commands accept `--dry-run`. Portfolio selection can be changed with
`--selection-policy DETERMINISTIC_UNRANKED_BASELINE`. Results are exposed under
`/api/v1/research`, including portfolio trades, equity, metrics and skipped signals.
