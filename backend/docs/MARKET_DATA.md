# Market data assumptions and provenance

This document fixes the data semantics used by Market Intelligence AI. Any future scanner or backtest must preserve these assumptions or explicitly version a change.

## S&P 500 universe

Current snapshots and historical membership are deliberately separate:

- `universe_snapshots` + `universe_snapshot_members` contain a dated, sourced observation of the constituents known at import time and power `LATEST` scans;
- `universe_memberships` contains genuine `valid_from`/`valid_to` history and is the only source permitted for `HISTORICAL` scans.

Importing a current CSV never manufactures historical intervals or changes the historical table.

The database supports point-in-time membership through:

- `universe`
- `ticker`
- inclusive `valid_from`
- inclusive optional `valid_to`
- `source`
- database-generated `loaded_at`

`UniverseImporter.import_sp500` validates tickers, dates and overlapping intervals before performing an idempotent upsert. `SP500Universe.members(as_of)` returns only memberships for which `valid_from <= as_of` and `valid_to IS NULL OR valid_to >= as_of`. Future additions are therefore excluded from past queries.

No production historical constituent dataset is bundled in this repository. The automated tests use clearly fictional fixtures to verify the infrastructure. We do not infer or invent inclusion/removal dates. Before research use, load a licensed or authoritative point-in-time source and preserve its original source identifier.

A list of today's constituents is only a current snapshot. Applying it historically creates survivorship bias and is prohibited unless the result is explicitly labelled with that limitation.

## Trading calendar

Daily U.S. equity sessions use the `XNYS` calendar from [`exchange_calendars`](https://github.com/gerrymanoim/exchange_calendars). The library provides maintained exchange holidays, ad-hoc closures and session schedules for more than 50 exchanges. XNYS is used as the common U.S. equities session calendar in this phase.

`NYSETradingCalendar` exposes:

- `is_trading_day(date)`
- `previous_trading_day(date)`
- `next_trading_day(date)`
- `trading_days_between(start, end)` (inclusive)
- `latest_complete_session(now, delay)` based on the actual XNYS close plus provider delay
- `sessions_ending_on(end, count)` for exact session lookbacks

Calendar dates are session labels. Stored timestamps are timezone-aware UTC. The Massive aggregates endpoint describes daily aggregates in Eastern Time, so provider timestamps are normalized to UTC and mapped to their session date before completeness checks.

The library models early closes in its schedule. Daily completeness requires one bar for an early-close session just as for a regular session; it does not require a full-length intraday session.

## Daily completeness and missing data

For a requested interval, `MarketDataService`:

1. asks XNYS for the expected sessions;
2. reads stored daily bars for the ticker and provider;
3. rejects stored bars labelled with non-session dates;
4. computes expected, available, missing and unexpected session sets;
5. groups adjacent missing market sessions;
6. requests only those date ranges from the provider;
7. rejects provider bars on non-session dates;
8. upserts returned bars without forward-filling gaps.

Weekends and exchange holidays are never considered missing. A session can still remain absent after a provider request—for example because no qualifying trade produced an aggregate, the security was suspended, or provider coverage is incomplete. The gap remains explicit; it is never filled or converted into a zero-volume synthetic bar.

## Massive aggregates and corporate actions

The current provider calls Massive aggregate bars with `adjusted=true`.

According to [Massive's official adjustment guidance](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends), REST historical aggregates are split-adjusted by default but are **not dividend-adjusted**. `adjusted=false` returns prices as quoted without split adjustment. Massive also documents that [flat files are unadjusted](https://massive.com/docs/flat-files/stocks/overview); those files must not be mixed with the current REST series without an explicit transformation and provenance change.

Consequences:

- forward splits and reverse splits are reflected in the adjusted REST series;
- cash dividends are not incorporated into OHLCV total returns;
- price-return features are not total-shareholder-return features;
- dividing already adjusted bars by split ratios would double-adjust them;
- future backtests involving dividends must ingest corporate-action data separately;
- adjusted and unadjusted series must use distinct provider/mode identity before both modes are supported.

Massive's current [Stocks REST overview](https://massive.com/docs/rest/stocks/overview) exposes dedicated splits and dividends endpoints. A full corporate-actions engine remains outside this phase.

## Security identity and ticker changes

A ticker is not treated as an eternal company identity. Migration `20260923_0003` adds a stable `securities` table and an optional `symbols.security_id` foreign key. This is deliberately minimal:

- market bars and universe memberships continue to reference the historical symbol row;
- multiple symbol records can later map to the same security (for example `FB` and `META`);
- no historical ticker mapping is fabricated in this phase;
- future work can add explicit symbol validity intervals and provider-specific identifiers after an authoritative source is selected.

The existing unique ticker constraint remains for compatibility. It must be revisited if research requires ticker reuse across different securities or exchanges.

## Known limitations

- No authoritative S&P 500 history is shipped or loaded automatically.
- XNYS is a market-level calendar; a security may have listing, suspension or halt-specific gaps.
- Completeness proves presence of one daily bar per expected session, not correctness of every trade inside the bar.
- Daily aggregate timestamps must continue to be audited against provider session semantics.
- Dividend-adjusted total-return data is not available through the current bar mode.
