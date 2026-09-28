# EODHD POC — point-in-time S&P 500 data audit

Audit date: 2026-09-28

Scope: bounded data-quality POC only; no point-in-time backtest and no production import.
Assessment: **NOT READY FOR PIT IMPLEMENTATION**.

## 1. Connection/API status

`EODHD_API_KEY` was read through `SecretStr` from the environment. It was not
printed, logged, cached, persisted in PostgreSQL, or added to Git. The client
uses timeouts, exponential retry, explicit 401/403/429/5xx handling, sanitized
errors, and an optional cache under ignored `backend/data/eodhd_poc/`.

The POC made 34 distinct successful API requests. The final reproducibility run
served all 34 from cache and produced no rate-limit event. Failed requests are
not cached; no HTTP/provider failure was observed.

## 2. Subscription/endpoints available

The configured subscription allowed:

- `v1.1/fundamentals/GSPC.INDX?filter=HistoricalTickerComponents`
- `v1.1/fundamentals/GSPC.INDX?historical=1&from=...&to=...&filter=HistoricalComponents`
- `v1.1/fundamentals/{symbol}.US`
- `eod/{symbol}.US`
- `exchange-symbol-list/US?delisted=1&type=common_stock`
- `symbol-change-history`
- `splits/{symbol}.US`
- `div/{symbol}.US`

EODHD documents historical membership in the Fundamentals API and states that
the flat S&P history starts in April 2012, while some surviving entries have
older join dates. [Official Fundamentals documentation](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)

## 3. Historical S&P 500 membership findings

`HistoricalTickerComponents` returned 822 records:

- 176 are currently flagged `IsDelisted`;
- 145 have no `StartDate`;
- no duplicate `Code` occurred in the flat response;
- membership rows contain `Code`, `Name`, `StartDate`, `EndDate`,
  `IsActiveNow`, and `IsDelisted`, but no exchange or stable identifier.

Derived snapshots, assuming `EndDate` is inclusive:

| Date | Members | Missing StartDate among members | Duplicate code |
|---|---:|---:|---:|
| 2013-06-28 | 478 | 124 | 0 |
| 2016-06-30 | 493 | 77 | 0 |
| 2020-06-30 | 504 | 26 | 0 |
| 2022-06-30 | 502 | 8 | 0 |
| 2026-06-30 | 504 | 2 | 0 |

Counts below 500 are not silently repaired. They demonstrate that the flat log
alone cannot reconstruct early snapshots when `StartDate` is null.

Provider `HistoricalComponents` snapshot results:

| Requested date | Provider rows |
|---|---:|
| 2013-06-28 | 0 |
| 2016-06-30 | 0 |
| 2020-06-30 | 0 |
| 2022-06-30 | 0 |
| 2026-06-30 | 503 |

The 2026 response contained 503 unique codes, no missing code and no duplicate.
The four empty historical responses are a blocker until EODHD confirms whether
this is subscription scope, retained snapshot depth, or request semantics.

## 4. Membership date semantics

EODHD describes `StartDate` as the date a ticker joined and `EndDate` as the date
it left. It does not establish, with sufficient precision for this POC, whether
an `EndDate` security is eligible at that day's signal close. The implementation
therefore exposes inclusive/exclusive behavior and labels the POC calculation as
an inclusive assumption. [Official historical-constituents description](https://eodhd.com/financial-apis-blog/reworked-sp-500-historical-constituents)

Observed last-price dates frequently precede membership end: ATVI by three XNYS
sessions, SIVB by four, TWTR by three, and CELG by one. Membership end cannot be
used as a synthetic price or terminal value.

## 5. Identifier findings

Security Fundamentals can supply CIK, CUSIP, ISIN, OpenFIGI, LEI and
`PrimaryTicker`, but availability varies. Examples:

| Code | ISIN | CUSIP | CIK | OpenFIGI | Status |
|---|---|---|---|---|---|
| AAPL | US0378331005 | 037833100 | 0000320193 | BBG000B9XRY4 | active |
| META | US30303M1027 | 30303M102 | 0001326801 | BBG000MM2P62 | active |
| ATVI | US00507V1098 | 00507V109 | 0000718877 | available | delisted |
| SIVB | US78486Q1013 | null | 0000719739 | null | delisted |
| LEH | null | 524908100 | 0001568495 | available | delisted |

No single identifier is complete. A production `security_id` needs a versioned
crosswalk using multiple identifiers, issuer/security distinction, effective
dates, provenance and manual exceptions. Membership cannot be joined directly
to Fundamentals by ticker without temporal validation.

## 6. Ticker-change findings

The symbol-change feed returned 1,213 US changes and correctly included
FB → META with effective date 2022-06-09. However, it contains no stable security
identifier. Querying `FB.US` today returns a different BATS-listed ETF named
“ProShares S&P 500 Dynamic Buffer ETF”, with a different OpenFIGI and no Facebook
identifiers. This is direct evidence of ticker reuse.

The old ticker therefore cannot be resolved by asking for its current
Fundamentals record. Symbol changes must be captured with identifiers valid at
the effective date. The EODHD symbol-change endpoint is US-only according to
the [official delisted/symbol-change documentation](https://eodhd.com/financial-apis/delisted-stock-companies-data-2).

## 7. Former constituent tests

| Code | Case | Membership end | Last EOD | Finding |
|---|---|---|---|---|
| AAL | removed, still listed | 2024-09-23 | 2024-09-23 | complete in interval |
| ATVI | acquired | 2023-10-18 | 2023-10-13 | 3 missing sessions |
| TWTR | acquired | 2022-11-01 | 2022-10-27 | 3 missing sessions |
| CELG | acquired | 2019-11-21 | 2019-11-20 | 1 missing session |
| SIVB | bank failure/delisted | 2023-03-15 | 2023-03-09 | 4 missing sessions |
| LEH | bankruptcy before audit window | 2008-09-16 | none in 2012+ request | no terminal observation |
| MON | ticker reuse/mapping collision | 2018-06-07 | none | 1,618 missing sample days |

## 8. Delisted security tests

The delisted directory identified ATVI, TWTR, CELG, SIVB, LEH and MON. EODHD
states that pre-2018 delistings may have EOD only, while richer fundamental and
corporate-action coverage is generally available only for later delistings.
That limitation prevents uniform identity enrichment. [Official delisted-data coverage](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)

## 9. OHLCV coverage

The bounded sample covered 11 membership records and 24,720 expected XNYS
security-days from 2012 through 2026:

- with price: 23,091;
- missing: 1,629;
- aggregate coverage: 93.4102%;
- incomplete securities: 5 of 11.

The percentage is dominated by MON's 1,618 missing days. Removing it would hide
the exact identity failure the POC is intended to detect, so it remains included.

Missing classification:

- acquisition/merger boundary: ATVI 3, TWTR 3, CELG 1;
- failure/delisting boundary: SIVB 4;
- ticker reuse/identity mismatch: MON 1,618;
- provider missing/unknown: not silently reclassified.

This is a representative sample audit, not a claim of full-universe coverage.

## 10. Corporate-action semantics

The POC observed forward splits (AAPL 7:1 and 4:1; NVDA 4:1 and 10:1), GE's
1:8 reverse split, and non-integer GE reorganization factors. Split ratios are
parsed as `new shares / old shares`; arbitrary decimal ratios must be supported.

Dividend JSON includes ex-date, declaration, record and payment dates,
split-adjusted `value`, historical `unadjustedValue`, and currency. Signal logic
must use only information known by the relevant cutoff; current adjusted series
cannot be mistaken for a historically frozen dataset.

## 11. Split adjustment findings

EODHD documents and the POC confirms:

- OHLC fields are raw/unadjusted;
- `adjusted_close` is split- and dividend-adjusted;
- volume is split-adjusted;
- historical `adjusted_close` is recomputed after later dividends.

[Official EOD historical-data semantics](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)

## 12. Volume adjustment findings

EODHD volume is already split-adjusted, while OHLC remains raw. This combination
cannot be fed directly into the current breakout/SMA/RVOL pipeline alongside
Massive adjusted OHLC without a provider-specific normalization contract.

## 13. Dividend findings

`adjusted_close` represents a total-return-style adjustment for both splits and
dividends; it is not a split-only signal series. Explicit dividend events expose
announcement/declaration, ex, record and payment dates. The economic-return
series should use dividends, while the signal series needs split-consistent OHLC
and volume without dividend back-adjustment. [Official dividends and splits documentation](https://eodhd.com/financial-apis/api-splits-dividends)

## 14. EODHD vs Massive comparison

Overlap was 1,252 sessions for AAPL/NVDA and 1,162 for META.

- AAPL raw close aligned almost exactly: mean absolute difference 0.0000043%,
  maximum 0.0029%. Volume mean absolute difference was 0.0772%.
- NVDA raw EODHD close was approximately 10× Massive before the 2024 10:1
  split, then approximately 1×. This is the expected raw-vs-split-adjusted
  incompatibility.
- META was not comparable before FB→META. In 2021 the median EODHD/Massive raw
  close ratio was 21.71×, then 1× from 2022 onward. Before 2022, the `META`
  ticker represented a different instrument in the market, while EODHD's current
  META history follows Facebook/Meta. This is ticker-reuse contamination, not a
  price rounding difference.

Provider series must remain separately identified and normalized. They cannot be
merged by `ticker + date`.

## 15. Membership × price coverage

The sample's 93.4102% coverage is **not** accepted as “good enough.” The missing
6.5898% identifies a full-history identity collision plus economically important
terminal gaps. A full-universe audit must run only after stable identity mapping
is available; otherwise its denominator and missing classifications are unsafe.

## 16. Missing-data classification

Every missing membership-day should persist a reason and provenance. Proposed
values: `ACQUISITION_BOUNDARY`, `MERGER_BOUNDARY`, `BANKRUPTCY_OR_FAILURE`,
`DELISTING_BOUNDARY`, `TICKER_CHANGE`, `TICKER_REUSE`, `PROVIDER_MISSING`, and
`UNKNOWN`. Classification must not manufacture a bar.

## 17. Terminal-value problems

ATVI, TWTR, CELG, SIVB, LEH and MON remain `UNKNOWN_TERMINAL_VALUE` in this POC.
The last quoted close is not assumed to be merger consideration, recovery value,
zero, or -100%. Corporate-action/cash consideration data or a documented terminal
value policy is required before economic-return backtesting.

## 18. Lookahead risks

- `IsDelisted`, `IsActiveNow`, current Fundamentals and `UpdatedAt` describe
  present/provider state, not necessarily knowledge available on the event date.
- `adjusted_close` is recomputed using later dividends.
- symbol-change `effective` is not an announcement date;
- membership Start/End dates do not expose announcement/publication timestamps;
- querying an old ticker today may return a reused security;
- current ISIN/CUSIP/OpenFIGI must not be retroactively attached without an
  effective interval.

Production data must preserve `effective_date`, `announcement_date` when
available, `provider_updated_at`, `observed_at`, and ingestion version separately.

## 19. API/rate-limit observations

No 429 was observed. The client honors `Retry-After`, retries transport/5xx with
backoff, and counts requests/cache hits. EODHD documents one API call per EOD,
split or dividend request. The POC deliberately avoided a 2012–2026 bulk import.

## 20. Recommended production architecture

1. Raw immutable EODHD landing tables/files, versioned by observation time.
2. Stable internal `security_id`, distinct from issuer and listing identifiers.
3. Effective-dated aliases for ticker, exchange, ISIN, CUSIP, FIGI, LEI and CIK.
4. Membership intervals referencing `security_id`, with source and date semantics.
5. Separate raw, split-adjusted signal and economic-return series.
6. Corporate-action ledger and explicit terminal-value status.
7. Provider-specific quality checks and reconciliation; never overwrite Massive.
8. PIT eligibility materialized only from causally available records.

## 21. Required DB/schema changes

No production schema was changed in this POC. Before implementation, isolated
new structures are needed for security aliases/effective periods, raw provider
payload lineage, membership observations, corporate actions, terminal values and
data-quality exceptions. Existing `symbols.ticker` cannot be the historical key.

## 22. Blockers

1. Confirm why historical snapshot requests for 2013/2016/2020/2022 are empty.
2. Obtain authoritative inclusive/exclusive membership date semantics.
3. Resolve the 145 null `StartDate` records for early reconstruction.
4. Build and validate an effective-dated identity crosswalk, including FB/META
   and MON/Monsanto versus the reused MON ticker.
5. Determine terminal consideration/recovery policy for acquisitions, mergers,
   bankruptcies and delistings.
6. Define reproducible split-only signal adjustment and dividend-aware economic
   return series.
7. Run a full 822-record identity audit before any full historical import.

## 23. Final assessment

**NOT READY FOR PIT IMPLEMENTATION.**

EODHD provides valuable historical membership, delisted directories, identifiers,
EOD prices and corporate actions. However, the observed ticker reuse, null join
dates, empty older snapshot responses, membership/price boundary gaps and unknown
terminal values are sufficient to reintroduce survivorship or identity bias if a
PIT backtest is started now. The blockers above must be resolved with evidence
before importing the full history or changing the backtesting universe.
