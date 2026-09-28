# EODHD POC 3 — Full Historical Data Coverage Audit

**Audit date:** 2026-09-28

**Coverage window:** 2012-04-02 through 2026-09-22

**Scope:** membership, identity, price availability, tradeability and terminal-event data quality only. No strategy signal, return, benchmark comparison or backtest was calculated.
**Final decision:** **EODHD_REQUIRES_SECOND_SOURCE**

## 1. Executive summary

The audit built an experimental Historical Security Master v0 for all 822 EODHD S&P 500 membership records and checked 1,806,904 membership-security-days. It found 1,785,866 valid price observations and 21,038 missing sessions: **98.8357% global coverage**. Identity confidence is HIGH for 795, MEDIUM for three, LOW for three and UNRESOLVED for 21. Twenty-two reused tickers were confirmed by temporal incompatibility or prior identifier evidence.

The aggregate percentage hides a strong time gradient. Membership × price coverage rises from 95.56% in 2012 to more than 99.99% from 2020 onward. Nevertheless, no year passes the predeclared complete PIT reliability criteria: terminal-event resolution and post-removal availability remain materially below the required levels. The correct conclusion is not that recent EODHD prices are poor; it is that EODHD alone does not provide a complete historical identity/terminal-value layer for unbiased economic outcomes. No `EARLIEST_RELIABLE_PIT_DATE` is assigned.

## 2. Historical Security Master methodology

The machine-readable master is stored in ignored `backend/data/eodhd_poc3/audit.json`. Each row contains an internal `security_id`, canonical name, source membership interval, left-censoring and exclusive-end semantics, provider symbol, identifiers, identity confidence/evidence, symbol changes, full EOD bounds, expected/available/missing sessions, missing reasons, event classification/confidence, post-removal availability and unresolved flags. No production migration or table was created.

## 3. Security identity methodology

Ticker is only a candidate lookup key. A mapping requires compatible fundamentals and identifiers or a separately verified historical alias. Fuzzy company-name matching between instruments was rejected after it produced false links to preferred/alternate securities. Candidate series beginning on or after the historical membership end are classified as confirmed ticker reuse and cannot supply historical prices. Internal UUIDs prefer OpenFIGI, ISIN, CUSIP, CIK and LEI; fallback UUIDs remain LOW/UNRESOLVED rather than being promoted.

## 4. 145 left-censored memberships

All 145 POC 2 `PRE_HISTORY_MEMBER` classifications are preserved as `LEFT_CENSORED_MEMBERSHIP`; no original entry date was invented. The earliest provider-history assertion used is 2012-04-02. Of the 145, 144 are present on that first observed trading session; the remaining row ended in 2008 and is retained as a legacy record outside the audit window. Left-censoring decreases from 144 securities on 2012-04-02 to two from 2024 onward. This supports research beginning after the observation boundary only if identity and membership are otherwise resolved; it does not recover pre-boundary entry dates.

## 5. Full 822 identity audit

| Confidence | Records | Percent |
|---|---:|---:|
| HIGH | 795 | 96.72% |
| MEDIUM | 3 | 0.36% |
| LOW | 3 | 0.36% |
| UNRESOLVED | 21 | 2.55% |

There are 798 HIGH/MEDIUM resolutions (97.08%). LOW records are temporary/provider placeholders without stable identifiers: IILGV, LEN-N and MRP_OLD. The 21 unresolved identities are ADT plus 20 temporally incompatible reused-series cases. All 822 rows have an internal audit ID, but only confidence-qualified rows should become production securities automatically.

## 6. Ticker reuse

The audit confirms 22 dangerous reused tickers: ADT, ALTR, BEAM, BTU, DEN, DNB, DO, DTV, EMC, FRX, HSH, LLL, MMI, MNK, MON, NE, PGN, PLL, S, SE, STI and VAL. Their candidate series starts on/after the historical membership end or has independent crosswalk evidence. `MON` is forced to verified `MON_old` using Monsanto's ISIN/CUSIP/CIK/LEI; it is never joined to the modern `MON`. FB→META remains a regression case: the modern FB instrument cannot represent historical Facebook.

## 7. Symbol changes

The POC 2 graph remains authoritative for this audit: 1,213 US edges, 83 multi-hop chains and 34 cycles; 33 edges and two cycles intersect membership tickers. Twelve master rows are classified as ticker-change cases. Graph edges are candidate aliases only and need identifier corroboration. Their membership-price coverage is 68.50%, demonstrating that ticker changes remain a major missing-not-at-random source.

## 8. Snapshot reconstruction

Counts are not forced to 500. Values below are first / mid-year / last trading-session snapshots, followed by unresolved identities at those snapshots.

| Year | Securities | Unresolved identities |
|---|---:|---:|
| 2012 | 475 / 475 / 477 | 18 / 16 / 17 |
| 2013 | 477 / 478 / 481 | 17 / 17 / 16 |
| 2014 | 481 / 483 / 486 | 16 / 14 / 14 |
| 2015 | 486 / 489 / 491 | 14 / 13 / 9 |
| 2016 | 491 / 494 / 496 | 9 / 7 / 5 |
| 2017 | 497 / 498 / 500 | 5 / 3 / 2 |
| 2018 | 500 / 502 / 503 | 2 / 2 / 2 |
| 2019 | 503 / 504 / 505 | 2 / 1 / 0 |
| 2020 | 505 / 504 / 504 | 0 / 0 / 0 |
| 2021 | 504 / 504 / 504 | 0 / 0 / 0 |
| 2022 | 504 / 502 / 502 | 0 / 0 / 0 |
| 2023 | 502 / 504 / 502 | 0 / 0 / 0 |
| 2024 | 502 / 503 / 503 | 0 / 0 / 0 |
| 2025 | 503 / 503 / 503 | 0 / 0 / 0 |
| 2026 | 503 / 503 / 503 | 0 / 0 / 0 |

No duplicate alias occurs within these snapshots. Exact-name company counts are normally equal to securities, except known share-class/name cases.

## 9. Annual membership quality

The early flat history is incomplete: first-session counts are 475 in 2012, 477 in 2013 and 481 in 2014. It reaches 500 securities only at the end of 2017. Continuous snapshot counts become structurally plausible from 2018, and unresolved identities disappear from sampled snapshots during 2019. These are observed facts, not corrections to a target count.

## 10. Price coverage

All price comparisons use NYSE sessions and exclusive membership `EndDate`. No forward fill, backward fill, zero return or artificial bar is used. Price evidence is retained by provider symbol with first/last dates. A current series that begins after a former membership interval is rejected as ticker reuse rather than called a provider price gap.

## 11. Membership × price coverage

- Membership-security-days: **1,806,904**
- With valid price: **1,785,866**
- Missing: **21,038**
- Global coverage: **98.835688%**

## 12. Coverage by year

“Constituents” below means distinct records active at any time during the year, not a single-day snapshot.

| Year | Constituents | H/M/L/U identity | Priced / expected | Missing | Coverage |
|---|---:|---:|---:|---:|---:|
| 2012 | 493 | 471/2/0/20 | 85,406 / 89,376 | 3,970 | 95.5581% |
| 2013 | 495 | 478/0/0/17 | 115,349 / 120,520 | 5,171 | 95.7094% |
| 2014 | 498 | 481/0/0/17 | 117,221 / 121,749 | 4,528 | 96.2809% |
| 2015 | 515 | 501/0/0/14 | 119,595 / 123,136 | 3,541 | 97.1243% |
| 2016 | 529 | 519/0/1/9 | 122,287 / 124,321 | 2,034 | 98.3639% |
| 2017 | 533 | 527/0/1/5 | 124,264 / 125,122 | 858 | 99.3143% |
| 2018 | 528 | 526/0/0/2 | 125,350 / 125,862 | 512 | 99.5932% |
| 2019 | 528 | 525/1/0/2 | 126,719 / 127,088 | 369 | 99.7097% |
| 2020 | 522 | 521/1/0/0 | 127,557 / 127,563 | 6 | 99.9953% |
| 2021 | 528 | 527/1/0/0 | 127,010 / 127,014 | 4 | 99.9969% |
| 2022 | 522 | 521/1/0/0 | 126,186 / 126,191 | 5 | 99.9960% |
| 2023 | 520 | 519/1/0/0 | 125,498 / 125,506 | 8 | 99.9936% |
| 2024 | 519 | 519/0/0/0 | 126,634 / 126,641 | 7 | 99.9945% |
| 2025 | 524 | 523/0/1/0 | 125,747 / 125,767 | 20 | 99.9841% |
| 2026* | 522 | 522/0/0/0 | 91,043 / 91,048 | 5 | 99.9945% |

`*` Through 2026-09-22.

## 13. Coverage by event type

| Event class | Securities | Missing | Coverage |
|---|---:|---:|---:|
| Active/no terminal event | 503 | 1,295 | 99.9088% |
| Index removal, still trading | 219 | 14,273 | 94.4832% |
| Ticker change | 12 | 4,703 | 68.4976% |
| Delisting | 82 | 760 | 99.2822% |
| Cash acquisition | 3 | 4 | 99.9151% |
| Mixed acquisition | 1 | 0 | 100.0000% |
| Receivership | 1 | 3 | 99.7611% |
| Bankruptcy | 1 | no in-window denominator | n/a |

## 14. Missing-not-at-random analysis

Missing reasons: 17,454 identity-mapping failures, 3,479 provider gaps, 104 terminal-event boundary sessions and one symbol-change boundary session. The concentration in reused tickers, ticker changes, delistings and former constituents is missing-not-at-random. Dropping these rows would reintroduce survivorship bias. The strong post-2020 daily coverage does not solve terminal economic value.

## 15. Membership vs tradeability

Eligibility ends at exclusive `EndDate`; tradeability may continue. The master therefore never closes a hypothetical position merely because membership ended. `INDEX_REMOVAL_STILL_TRADING` is assigned only when the same validated series continues through the removal boundary. This audit checks availability only and calculates no forward return.

## 16. Post-removal coverage 1/5/10/20/60

| Horizon | Eligible former securities | Complete | Coverage |
|---|---:|---:|---:|
| 1 session | 319 | 206 | 64.58% |
| 5 sessions | 316 | 185 | 58.54% |
| 10 sessions | 316 | 183 | 57.91% |
| 20 sessions | 316 | 182 | 57.59% |
| 60 sessions | 312 | 179 | 57.37% |

Low availability partly represents real acquisitions/delistings rather than ordinary data failure. It still means a future economic-return engine requires terminal consideration/successor data, not just EOD prices.

## 17. Terminal-event classification

Of 319 former records, 225 event classifications are HIGH, 12 MEDIUM and 82 LOW. The latter are classified only generically as delistings and count as unresolved for economic terminal handling. Specific verified cases remain: ATVI/TWTR/MON cash acquisitions, CELG mixed acquisition, SIVB receivership and LEH bankruptcy. The audit intentionally does not convert generic delisting into an acquisition or zero value.

## 18. Acquisition data availability

EOD prices identify last-trading boundaries but do not consistently normalize cash, stock, CVR, conversion ratio and successor identifiers. Monsanto and selected critical cases have authoritative external terms from POC 2; this is not a complete 822-record corporate-consideration ledger. Acquisition price coverage is high, but economic settlement remains a separate requirement.

## 19. Bankruptcy/delisting data availability

SIVB has a verified receivership boundary and LEH is outside the coverage window. Eighty-two other rows have only LOW-confidence generic delisting classification. OTC successors, cancellation dates and shareholder recoveries are not uniformly available. This is a material adverse-outcome data gap.

## 20. Terminal-value policy proposal

This proposal is not applied:

- `INDEX_REMOVAL_STILL_TRADING`: retain the validated listing and use the normal future exit rule.
- `ACQUISITION_CASH`: settle on effective date at verified cash consideration plus entitled distributions.
- `ACQUISITION_STOCK`: transform shares by verified ratio into a dated successor security.
- `ACQUISITION_MIXED`: ledger cash, successor shares and CVRs separately.
- `MERGER`: apply verified legal conversion terms and fractional-share cash treatment.
- `BANKRUPTCY`/`RECEIVERSHIP`: use cancellation/recovery ledger; never assume last close or zero silently.
- `DELISTING`: follow a verified OTC/successor alias if tradeable; otherwise require terminal evidence.
- `UNKNOWN`: publish a predefined LOWER_BOUND and UPPER_BOUND sensitivity range, retain the observation, and prohibit a single-valued result until resolved.

## 21. Split-adjusted signal-series specification

Preserve POC 2's split-only algorithm: for a raw OHLC bar at `t`, divide by the product of split factors effective after `t`; keep EODHD volume unchanged because it is already split-adjusted. Never use dividend-adjusted close for breakout/SMA signals. Regression evidence remains AAPL (7:1, 4:1), NVDA (4:1, 10:1) and GE (1:8 reverse plus non-integer actions). Mechanical crashes/breakouts disappear; no synthetic volume adjustment is added.

## 22. Economic-return-series specification

Build a separate event ledger from executable prices, dividends known by ex-date, share transformations, cash/stock acquisition consideration, CVRs, successor securities and terminal recoveries. EODHD `adjusted_close` is a cross-check only because later dividends can revise prior history. No economic returns were calculated in this POC.

## 23. Lookahead audit

`SAFE_AT_DATE`: effective membership date, contemporaneous price and effective split. `IDENTITY_ONLY_RETROSPECTIVE`: current identifiers, delisted directory and future-discovered symbol changes; these may repair identity but never eligibility. `UNSAFE_FOR_ELIGIBILITY`: future membership, acquisition outcome or terminal value. `UNKNOWN`: provider update/observation timing not evidenced. Production must persist announcement, effective, observed-at and ingestion timestamps separately.

## 24. Annual data-quality scorecard

Criteria were fixed before selection: membership count floor 490, HIGH/MEDIUM identity ≥99%, price coverage ≥99.5%, terminal-event resolution ≥95%, post-removal 20-day availability ≥95%, and no unexplained missing-not-at-random concentration. Years 2012–2016 are `UNRELIABLE`; 2017–2026 are `CONDITIONALLY_RELIABLE`. No year is `RELIABLE`. From 2020, membership identity and price coverage are excellent, but terminal resolution (61.9%–94.4% depending on year) and post-removal 20-day availability (50%–77.8%) fail consistently. Dimensions are reported separately; no financial or blended score is produced.

## 25. Earliest reliable PIT date

**EARLIEST_RELIABLE_PIT_DATE: NOT ESTABLISHED.**

For membership plus daily signal-price availability alone, 2020-01-02 is a strong conditional boundary: sampled snapshots have zero unresolved identities and annual coverage is 99.9953%. It is **not** promoted to a reliable PIT start because terminal economic outcomes and post-removal horizons remain unresolved. Selecting it as fully reliable would ignore exactly the missing-not-at-random risk the audit was designed to detect.

## 26. Remaining unresolved securities

The 21 UNRESOLVED records are: ADT, ALTR, BEAM, BTU, DEN, DNB, DO, DTV, EMC, FRX, HSH, LLL, MMI, MNK, NE, PGN, PLL, S, SE, STI and VAL. Most require a historical alias/identifier source for the pre-reuse series. LOW: IILGV, LEN-N, MRP_OLD. All remain in denominators; none was excluded to improve coverage.

## 27. Required production architecture

Implement immutable raw provider landing, internal security/issuer/listing IDs, effective-dated aliases and identifiers, exclusive membership intervals, separate tradeability state, split-only signal series, corporate-action/consideration ledger, terminal-value status, evidence provenance and point-in-time observation timestamps. Provider data must never be joined on ticker+date alone or overwrite Massive.

## 28. Required DB/schema changes

Future tables should cover `security`, `listing`, `security_identifier`, `security_alias`, `index_membership`, `provider_price_bar`, `corporate_action`, `terminal_event`, `event_consideration`, `data_quality_exception` and `source_observation`. Enforce non-overlapping effective intervals and explicit confidence/review state. No migration was created here.

## 29. API usage

POC 3 added **1,382 successful real API responses** to cache: 1,180 in the first full pass, 188 in the validated-ticker pass and 14 final recoveries. Rate-limit events: **0**. Final replay: 0 network requests and 1,648 cache hits. The combined POC cache contains 1,708 ignored response files. Final technical errors: **0**. Sandbox DNS failures during an intermediate local replay were not provider calls and were eliminated by the authorized final recovery.

## 30. Tests

The normal suite uses mocks/fixtures and makes no EODHD request. It covers security-ID stability, alias intervals, reuse, left-censoring, exclusive `EndDate`, missing-price classification, membership versus tradeability, post-removal horizons, terminal events, split-only adjustment, lookahead classification and secret redaction. Result: **130 passed, 0 failed**, with one existing Starlette/httpx deprecation warning.

## 31. Final EODHD decision

**EODHD_REQUIRES_SECOND_SOURCE.**

EODHD is excellent for recent membership and daily price availability: from 2020 the annual membership-price coverage exceeds 99.99%, and regular snapshots contain no unresolved identities. It is not sufficient alone for a survivorship-bias-free economic study because 21 historical identities remain unresolved, 22 ticker reuses require special handling, ticker-change coverage is 68.50%, 82 former events have only LOW classification, and only 57.59% of eligible former records have complete 20-session post-removal prices. Missing data is concentrated in former, changed, delisted and distressed securities.

A second authoritative identity/corporate-actions source is required for historical aliases, merger consideration, successor securities, cancellations and recoveries. After reconciliation, 2020-01-02 may be reconsidered as a conditional protocol start; it is not frozen by this POC. Stop here: no PIT implementation or backtest is authorized by these findings.
