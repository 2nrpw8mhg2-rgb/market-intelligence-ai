# EODHD POC 2 — Historical Identity & Membership Resolution

**Run date:** 2026-09-28

**Scope:** data-quality research only; no point-in-time backtest, strategy return, score, or portfolio metric was calculated.
**Decision:** **NOT_READY_FOR_PROTOCOL_FREEZE**

## 1. Executive summary

The POC proves that the largest POC 1 price gap was an identity error, not absent market data: the S&P membership ticker `MON` refers to Monsanto, while the present `MON` refers to Monument Circle Acquisition Corp. EODHD exposes Monsanto as `MON_old`, with ISIN `US61166W1018`. Mapping only this evidenced alias raises the 10-security sample from 93.4102% to 99.9515% coverage under the old inclusive-boundary calculation. With the empirically supported exclusive `EndDate` policy, coverage is 99.9717% (24,707/24,714 security-days); the remaining seven sessions are adjacent to terminal events.

This is not enough to freeze a PIT research protocol. All 822 membership records were screened, but only the 145 null-`StartDate` rows received independent fundamentals/identifier/price enrichment. The feed does not disclose their exact index-entry dates, the early snapshots remain incomplete, the terminal economic-value policy is not implementable from EOD prices alone, and full-universe price coverage by exit type was deliberately not downloaded. The experimental layer is useful and testable, but not yet a production-grade survivorship-bias-free history.

## 2. POC 1 blockers revisited

| Blocker | POC 2 result |
|---|---|
| 145 absent `StartDate` values | Classified, but none resolved to an exact or bounded entry date |
| Early snapshots below expected size | Explained as provider-history incompleteness; not repaired or forced to 500 |
| Unknown `EndDate` semantics | Strong evidence for exclusive `EndDate` |
| Ticker treated as identity | Experimental internal security/temporal-alias model added |
| Monsanto 1,618 missing days | Safely resolved through `MON_old` |
| Terminal values | Event types classified; economic terminal values remain unresolved |
| Raw OHLC around splits | Deterministic split-only signal-series algorithm validated |

## 3. StartDate NULL audit

All 145 records were queried through cached/retriable EODHD clients for fundamentals, identifiers, symbol changes, and full available EOD bounds. All 145 had fundamentals, at least one identifier, and a price series; 142 had HIGH identity-metadata confidence and three (EMC, NVLS, PGN) had MEDIUM confidence because only one identifier was present.

Classification: 145 `PRE_HISTORY_MEMBER`, 0 `RESOLVED_EXACT`, 0 `RESOLVED_BOUNDED`, 0 `UNRESOLVED`. This label means only that EODHD provides an open lower membership bound; it does **not** set `StartDate=2012-04-01`. Of these records, 142 end on/after the historical-components coverage boundary, two remain open, and one ended before it. The evidence supports that the missing values are predominantly legacy/open-left records, but it cannot establish the exact entry session. First price, IPO, or fundamentals dates were never substituted for membership entry.

## 4. Historical snapshot reconstruction

| Session | Raw | After safe resolution | Added | Null-start rows in snapshot | Duplicates |
|---|---:|---:|---:|---:|---:|
| 2013-06-28 | 478 | 478 | 0 | 124 | 0 |
| 2016-06-30 | 493 | 493 | 0 | 77 | 0 |
| 2020-06-30 | 504 | 504 | 0 | 26 | 0 |
| 2022-06-30 | 502 | 502 | 0 | 8 | 0 |
| 2026-06-30 | 504 | 504 | 0 | 2 | 0 |

Null `StartDate` was already interpreted as an open lower bound by the source model, so the safe classification correctly adds no securities. The early deficits therefore remain source-history gaps, not an arithmetic bug. Multiple share classes explain why a defensible count need not equal exactly 500. The machine-readable audit preserves all records and boundary samples.

## 5. EndDate semantics

The evidence supports **ENDDATE_EXCLUSIVE_CONFIRMED** for membership eligibility: `StartDate <= session < EndDate`. On multiple co-dated replacements, applying exclusivity removes the outgoing constituent on the same date the replacements enter:

| Removed | EndDate | Same-date entrants | Inclusive count | Exclusive count |
|---|---|---|---:|---:|
| AAL | 2024-09-23 | DELL, ERIE, PLTR | 506 | 503 |
| ATVI | 2023-10-18 | HUBB, LULU | 504 | 502 |
| CELG | 2019-11-21 | NOW | 506 | 505 |
| SIVB | 2023-03-15 | BG, PODD | 504 | 502 |
| TWTR | 2022-11-01 | ACGL | 503 | 502 |

The conclusion is temporal, not chosen merely to get closer to 500: former-security trading ends before the supplied `EndDate`, and entrants begin on that date. Production should retain the source dates and an explicit boundary-policy field rather than silently subtracting a day.

## 6. Identity model

The isolated experimental model separates `ExperimentalSecurity` (internal UUID, canonical name, identifiers and evidence) from `SecurityAlias` (ticker, exchange, validity interval, source and confidence). UUIDs are deterministic from the strongest available identifier in the order OpenFIGI, ISIN, CUSIP, CIK, LEI; when none exists, the ID is explicitly unresolved-derived and must not be promoted. Alias interval validity is tested. No production schema or scanner was changed.

## 7. Identifier availability

The enriched 145/145 null-start records contained at least one of CIK, CUSIP, ISIN, OpenFIGI or LEI. 142 contained enough compatible evidence for HIGH identity-metadata confidence and three had a single identifier (MEDIUM). Availability is not equivalence: identifiers can refer to issuer versus issue and still require exchange/name/action corroboration.

## 8. Identity crosswalk results

All 822 membership rows were screened against current/delisted directories. Independent API enrichment was performed for 145 rows (17.64%): 142 HIGH (17.27% of all records), three MEDIUM (0.36%), zero LOW. The remaining 677 rows were **not** declared identity-resolved merely because a directory name looked compatible. The separate batch reuse screen produced 673 rows with no reuse evidence, 148 unresolved and one confirmed reuse (Monsanto). These dimensions deliberately overlap and differ: “no reuse evidence” is not “identity proven.”

## 9. FB/META case

The symbol-change feed gives `FB -> META`, effective 2022-06-09, with Meta Platforms as the company. A current `FB` lookup now refers to a different ETF, so an unrestricted ticker join would corrupt the history. The future production alias must close FB at 2022-06-08 and open META at 2022-06-09 only after identifier corroboration. This offline identity fact may link prices; it must not retroactively change membership eligibility.

## 10. MON/Monsanto ticker-reuse case

The membership row keyed `MON` is name-overwritten as Monument Circle Acquisition Corp and has `EndDate=2018-06-07`. The delisted directory separately exposes `MON_old`, Monsanto, ISIN `US61166W1018`; fundamentals add CIK `0001110783`, CUSIP `60934T101`, and LEI `NONUZEX43GHIPSVDD938`. Its EOD series runs 2000-10-18 through 2018-06-06. Bayer confirms that Monsanto was acquired and ceased NYSE trading on 2018-06-07 ([source](https://www.bayer.com/media/en-us/bayer-closes-monsanto-acquisition/)). This is a confirmed reuse and `MON` joins must be blocked unless the dated security alias is resolved.

## 11. Other critical cases

- ATVI: EOD ends 2023-10-13; Microsoft completed the acquisition that day ([source](https://news.microsoft.com/wp-content/uploads/prod/sites/653/2023/10/Phil-Spencer-email-to-Microsoft-employees.pdf)).
- CELG: EOD ends 2019-11-20; BMS completed the acquisition, with stock/cash/CVR consideration, that day ([source](https://news.bms.com/news/details/2019/Bristol-Myers-Squibb-Completes-Acquisition-of-Celgene-Creating-a-Leading-Biopharma-Company/default.aspx)).
- SIVB: EOD ends 2023-03-09; Silicon Valley Bank was closed and FDIC made receiver on 2023-03-10 ([source](https://www.fdic.gov/resources/resolutions/bank-failures/failed-bank-list/silicon-valley.html)).
- LEH: the SEC filing records Chapter 11 on 2008-09-15, outside this feed's tested price window ([source](https://www.sec.gov/Archives/edgar/data/806085/000110465908059632/a08-22764_48k.htm)).
- TWTR: EOD ends 2022-10-27; classified acquisition, but consideration/event terms still need an authoritative machine-readable action record.
- AAL: index removal, not a terminal security event; prices continue after membership ends.

## 12. Symbol-change graph

The complete US feed produced 1,213 directed edges, 1,179 terminal chains, 83 multi-hop chains and 34 cycles. Intersecting either endpoint with historical membership tickers produced 33 edges, 31 terminal chains, no multi-hop chain and two cycles. Cycles and the FB reuse demonstrate why graph adjacency is only candidate evidence; it does not prove economic identity. Exchange changes, absent fundamentals and price availability require per-edge validation before promotion.

## 13. Ticker-reuse audit

Across 822 membership rows: one confirmed reuse (`MON`), zero suspected, 673 with no reuse evidence, and 148 unresolved. Separately, `FB` is a confirmed reused historical alias but is not a standalone row in the 822-record membership extract. Therefore there are two demonstrated dangerous aliases, one counted in the membership-row audit. Confirmed reuse is a hard failure for ticker-only joins.

## 14. Terminal-event classification

| Security | Classification | Terminal value status |
|---|---|---|
| ATVI | ACQUISITION | UNKNOWN in current data layer |
| TWTR | ACQUISITION | UNKNOWN |
| CELG | ACQUISITION | Terms known externally; not normalized |
| MON | ACQUISITION | Cash consideration known externally; not normalized |
| SIVB | BANKRUPTCY/receivership | UNKNOWN for equity holder |
| LEH | BANKRUPTCY | UNKNOWN |
| AAL | INDEX_REMOVAL_STILL_TRADING | Not applicable |

## 15. Membership vs tradeability

Membership controls whether a new signal is eligible. Tradeability controls whether an existing position can still follow its exit rule. An index removal must not close a position if the security continues trading; AAL demonstrates this. Acquisitions, bankruptcy and delisting require a dated terminal event and economic-value handler. Unit tests keep these concepts separate.

## 16. Terminal-value data availability

Acquisitions/mergers require cash, share conversion, CVRs, successor identifiers and effective dates. Bankruptcy requires cancellation/recovery evidence; delisting requires OTC continuation and price availability. EOD last price alone is not economic value. For unresolved events a future frozen protocol should report a `LOWER_BOUND` (conservative value, explicitly defined per event) and an `UPPER_BOUND` (last verifiable tradable/economic consideration), never silently impute either. No bound was applied here.

## 17. Coverage before identity resolution

The unchanged POC 1 sample contains 24,720 membership-security-days: 23,091 priced, 1,629 missing, **93.4102%** coverage. Monsanto alone contributes 1,618 missing days, showing that aggregate coverage was dominated by identity failure.

## 18. Coverage after identity resolution

Mapping only `MON -> MON_old` yields 24,708/24,720 priced days, 12 missing, **99.9515%** under the legacy inclusive calculation. Applying the separately evidenced exclusive boundary yields 24,707/24,714, seven missing, **99.9717%**. Nothing was synthesized.

Missing classification after the conservative boundary policy: identity failure 0; non-trading-day mismatch 0; provider generic gap 0 demonstrated; terminal-event boundary 7 (ATVI 2, SIVB 3, TWTR 2); unresolved economic terminal value 3 securities. The last category is conceptually distinct from missing daily prices.

## 19. Expanded coverage audit

Metadata/reuse screening covered all 822 records. Price-bound enrichment covered all 145 null-start records, while exact security-day coverage was intentionally restricted to the original 10-security sample to comply with the instruction not to download the full 2012–2026 history. Consequently, a defensible all-822 price-coverage percentage is **not available**. Securities with prices among enriched null-start cases: 145/145; full-period completeness is not implied.

## 20. Coverage by year

After identity and exclusive boundaries, the sample misses zero days in every tested year except 2022 (2) and 2023 (5). Before resolution, missing counts were 250 (2012), 252 each (2013–2016 except 2017), 251 (2017), 109 (2018), 1 (2019), 3 (2022), and 7 (2023); almost all early misses were the incorrect Monsanto ticker.

## 21. Coverage by exit/event type

In the sample: acquisition rows have four missing days after exclusive boundaries (ATVI 2, TWTR 2, CELG 0, MON 0); bankruptcy/receivership has three (SIVB; LEH is outside the audited window); index-removal-still-trading has zero (AAL). These are sample counts, not population estimates.

## 22. Missing-not-at-random risks

All seven residual missing sessions cluster at adverse or terminal events. This is direct evidence of missing-not-at-random risk even though numeric coverage is high. Bankruptcy, suspended trading and deal completion cannot be treated as ordinary provider gaps or dropped observations. This concentration is a principal reason for the negative readiness decision.

## 23. Split-adjusted signal-series design

For each raw OHLC bar at date `t`, compute the product of all split factors with effective date greater than `t`, then divide O/H/L/C by that future factor. Keep EODHD volume unchanged because its base EOD volume is documented as split-adjusted. Do not use dividend-adjusted close for breakout/SMA signals.

Validation removed mechanical price discontinuities: AAPL raw -85.49%/-74.15% became +1.60%/+3.39%; NVDA raw -75.22%/-89.93% became -0.89%/+0.75%; GE's 1:8 reverse-split raw +676.83% became -2.90%. AAPL/NVDA event RVOLs were ordinary. GE's 3.39 RVOL remains because observed volume itself was elevated; the algorithm did not manufacture it. The result demonstrates removal of false price breakouts/crashes, not that genuine split-day activity can never be high.

## 24. Economic-return-series design

Signal and return series must be separate. The signal series is split-only adjusted and stable under future dividends. The economic return ledger starts from executable prices and adds cash dividends known by ex-date, split/share transformations, merger consideration, successor shares, cash, CVRs and terminal recovery. Provider `adjusted_close` can be a cross-check but must not be the sole ledger because future dividends can revise history.

## 25. Lookahead risks

Store announcement, effective and provider-observed/update dates separately. Eligibility at session `t` may use only membership facts effective and knowable under the frozen protocol at `t`. Later information may be used offline to prove that FB and META are the same economic security or to retrieve the correct old price series; it may not retroactively add the security to the index or reveal future acquisition outcomes to the signal.

## 26. Remaining ambiguous cases

Exact entry dates for all 145 null-start rows; 148 directory-screen rows without a reference; both membership-relevant graph cycles; authoritative TWTR consideration normalization; shareholder terminal values for SIVB and LEH; provider observation timestamps; full-universe former-security price coverage; and population-level missingness by exit type remain unresolved.

## 27. Recommended production data model

Use immutable tables for `security`, `security_identifier`, `security_alias`, `index_membership`, `price_bar`, `corporate_action`, `terminal_event`, and `evidence`. Each temporal row needs valid-from/to, source, source key, confidence, observed-at and provenance. Enforce non-overlapping aliases per security/exchange and reject ticker joins lacking date and resolved security ID.

## 28. Required schema changes

Add internal UUID security keys; temporal aliases; explicit exclusive membership boundary semantics; issuer/issue identifier types; event announcement/effective/observed timestamps; tradeability state; terminal consideration components; resolution confidence and review status; source payload hash. These are recommendations only—no production migration was created.

## 29. API calls/cache usage

The original real POC 2 collection made 292 network requests, 15 cache hits and encountered zero rate limits/errors. The final corrected audit replay made zero network requests and 307 cache hits. Together with POC 1, the cache contains 326 distinct response files needed for reproducible local replay; secrets are never serialized. The cache and audit output live under ignored `backend/data/`.

## 30. Tests

Unit tests cover alias validity, ticker reuse/name compatibility, stable identity/status behavior, exclusive/inclusive `EndDate`, graph chains/cycles, terminal/missing-price classification, split-only forward and reverse adjustments, and membership-versus-tradeability. Existing client tests cover sanitized errors and secret redaction. Normal tests use fixtures/mocks and do not call the real API. Result: **128 passed**, with one pre-existing Starlette/httpx deprecation warning.

## 31. Blockers

1. No exact/bounded index-entry date for any of the 145 null-start records.
2. Only 145/822 records (17.64%) independently enriched; name screening is insufficient identity proof.
3. 148 batch rows unresolved and two relevant graph cycles need manual/identifier resolution.
4. Full-universe price/exit-type coverage was not collected; sample missingness is terminal-event concentrated.
5. Terminal economic consideration/recovery is not normalized, so unbiased returns cannot yet be calculated.
6. Historical provider-observation timestamps are not available to prove all point-in-time availability assumptions.

## 32. Final decision

**NOT_READY_FOR_PROTOCOL_FREEZE.**

Positive evidence is substantial: exclusive `EndDate` is defensible, ticker reuse is demonstrably detectable, Monsanto is safely recovered, sample price coverage reaches 99.9717%, signal-series split handling is deterministic, and identity is no longer modeled as ticker. However, readiness requires defensible membership, identity, terminal value and missingness treatment across the research population—not only a high 10-security sample percentage. With 0/145 exact or bounded null starts, 145/822 independently enriched identities, 148 unresolved reuse screens, seven residual terminal-boundary price gaps, and no complete terminal-value/full-universe coverage layer, freezing the PIT protocol would be premature.

The next data-quality step should resolve the membership-source boundary and identifiers for the unresolved/cyclic cases, normalize corporate consideration and terminal events, then execute a staged full-universe coverage audit. It should still precede any PIT backtest.
