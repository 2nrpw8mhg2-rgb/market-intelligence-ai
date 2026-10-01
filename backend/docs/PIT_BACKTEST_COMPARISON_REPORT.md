# Phase 1 — ORIGINAL_FIXED vs FIXED_REBUILT

**Decision:** **READY_FOR_PHASE_2**

**Scope:** fixed/current S&P 500 universe only; no PIT financial result and no portfolio simulation were run.

**Research window:** 2021-09-27 through 2026-09-22, inclusive (1,252 XNYS sessions).

## 1. Experimental design

This phase isolates the data/identity-infrastructure effect by comparing the
persisted ticker-based `ORIGINAL_FIXED` event study with `FIXED_REBUILT`, which
uses the same fixed/current 503-security S&P 500 snapshot, strategy, score,
`NEXT_OPEN` execution model, benchmark and horizons on the validated
`security_id`-native identity and logical-price infrastructure.

`FIXED_REBUILT` is not a PIT universe. Historical membership was not applied.
No financial PIT event study, portfolio backtest, CAGR, optimization or Phase 2
calculation was performed.

## 2. Pre-registered primary metrics

- Event-study primary metric for the eventual `FIXED_REBUILT` vs PIT experiment:
  **20-session mean excess return versus SPY**.
- Portfolio primary metric for the eventual full experiment: **CAGR**.

CAGR is recorded here only as a pre-registration; it was not calculated in
Phase 1. All other metrics below are secondary or diagnostic.

## 3. ORIGINAL_FIXED authoritative source

| Field | Authoritative value |
|---|---|
| Run ID | `cd4da596-8380-5b5c-9b55-252c601be6f6` |
| Config hash | `9fdee279f178447301a837656340c823e5e2a300656b65c9ada69607c702aa22` |
| Persisted tables | `backtest_runs`, `backtest_events`, `backtest_forward_returns` |
| Strategy | `BREAKOUT_20D_VOLUME` v1.0.0 |
| Universe | `FIXED_UNIVERSE_RESEARCH`, `SP500`, 503 current-snapshot symbols |
| Entry | `NEXT_OPEN`, implemented by `BacktestEngine._entry` as next XNYS-session open |
| Benchmark | SPY |
| Equity provider | Massive |
| Adjustment convention | Massive aggregate request persisted by the client with `adjusted=true` |
| Events | 4,831 |

The persisted run metadata and normalized event/forward-return rows are the
authoritative source; no result was reconstructed from copied summary figures.

## 4. Original research-window verification

The stored configuration is exactly 2021-09-27 through 2026-09-22. These are
the first and last eligible signal-generation sessions, covering 1,252 XNYS
sessions. The first actual accepted signal is 2022-07-20 and the last is
2026-09-22. The later first event is explained by the original data starting at
the research-window boundary and therefore needing 200 observations of feature
warm-up; it is not a different configured window.

## 5. ORIGINAL_FIXED to security_id mapping

Each event was resolved through the validated fixed-snapshot identity and then
through the dated temporal alias chain. The current ticker was never accepted
as identity by itself. Outer alias-ledger bounds were extended only for the
same independently proven `security_id`, because those bounds describe index
membership while this experiment deliberately holds the current universe fixed.
Internal alias gaps were not bridged.

| Mapping result | Events | Share |
|---|---:|---:|
| MAPPED | 4,831 | 100.0000% |
| UNMAPPED | 0 | 0.0000% |

## 6. UNMAPPED audit

There are no unmapped events. Consequently, the UNMAPPED 20-session N is zero
and its mean return and mean excess return are not applicable. No event was
forced into a mapped or event-difference category.

## 7. FIXED_REBUILT methodology

- Exact same 503-security fixed/current snapshot and exact same configured
  research window.
- Existing `BREAKOUT_20D_VOLUME` v1.0.0 implementation and thresholds unchanged.
- Existing deterministic score unchanged: breakout 30, relative volume 25,
  momentum 20, distance from SMA50 15, liquidity 10.
- Exact bucket semantics retained: 20→`20-40`, 40→`40-60`, 60→`60-80`,
  80→`80-100` (lower bound inclusive; upper bound exclusive except score 100).
- Existing `NEXT_OPEN` and 1/5/10/20/60-session outcome definitions unchanged.
- Equity histories: 502 `eodhd_adjusted_derived`; one validated logical LUV
  history uses EODHD plus one absent session supplied by Massive without
  overwriting the primary observation. SPY remains Massive.
- A 260-session pre-window load supplies feature warm-up. No PIT membership
  filter was used.
- The two reruns were in memory and read-only; no new backtest run was persisted.

## 8. FIXED_REBUILT data integrity

**FIXED_REBUILT_DATA_INTEGRITY = PASS**

| Check | Result |
|---|---|
| All 503 fixed securities resolved by security_id | PASS |
| Ticker-only fallback | 0 |
| Ticker-reuse leakage | 0 |
| Duplicate logical bars | 0 |
| Invalid OHLCV bars | 0 |
| Fabricated / forward-filled / interpolated prices | 0 / 0 / 0 |
| Look-ahead detected | 0 |
| Genuine missing observations affecting a rebuilt signal horizon | 0 |

Every rebuilt incomplete horizon is research-window truncation. The audit did
not silently fill holidays, pre-IPO history, lifecycle gaps or provider gaps.
No temporary halt was treated as terminal. In the original run only, two
60-session BIIB outcomes contain a missing Massive observation on 2023-06-09;
because a validated alternate history has an observation that day, these remain
`GENUINE_MISSING_DATA`, not an asserted halt. One other original 60-session gap
is FISV→FI `ALIAS_CONTINUITY`, not lifecycle termination.

## 9. Event-set consistency

| Set | Events |
|---|---:|
| ORIGINAL_FIXED | 4,831 |
| Mapped ORIGINAL_FIXED | 4,831 |
| Unmapped ORIGINAL_FIXED | 0 |
| FIXED_REBUILT | 5,896 |
| Matched `(security_id, signal_date)` | 4,804 |
| ORIGINAL_FIXED-only mapped | 27 |
| FIXED_REBUILT-only | 1,092 |

The 1,119 exclusive event identities were classified without changing either
event set:

| Supported cause | Events |
|---|---:|
| WARMUP_DIFFERENCE | 710 |
| ADJUSTMENT_DIFFERENCE | 288 |
| VOLUME_DIFFERENCE | 47 |
| ALIAS_CONTINUITY | 43 |
| SOURCE_COVERAGE_DIFFERENCE | 31 |
| UNKNOWN | 0 |

The large rebuilt-only early block is chiefly the intended pre-window warm-up
made possible by the logical histories. The remaining changes occur where the
two providers' adjusted price/volume histories cross a strategy threshold, or
where a modern ticker did not carry its predecessor history in the original
ticker-keyed dataset.

## 10. Data-source consistency

Matched events were compared strictly on `(security_id, signal_date)`. A
deterministic tolerance of `1e-12` defines identical values. For returns, one
basis point is `0.0001`; entry price and relative volume use relative basis
points; a score basis point is 0.01 score points.

| Field | Comparable | Identical | >1 bp | >1 bp share | Maximum absolute difference | Median absolute difference |
|---|---:|---:|---:|---:|---:|---:|
| Entry price | 4,802 | 1,143 | 3,629 | 75.5727% | 166.469423 | 1.955561 |
| Relative volume | 4,804 | 247 | 1,771 | 36.8651% | 0.485681 | 0.00007294 |
| Score | 4,804 | 640 | 2,630 | 54.7460% | 7.526500 | 0.019500 |
| 20-session return | 4,758 | 1,105 | 1,285 | 27.0071% | 0.314017 | 0.000000249 |
| 60-session return | 4,629 | 1,044 | 3,225 | 69.6695% | 0.397009 | 0.002500157 |

The differences are broad rather than driven by one security: >1 bp
20-session-return discrepancies span 343 securities and the largest security
contributes only 24/1,285 (1.87%). For entry prices, 403 securities are affected
and the largest contributes 32/3,629 (0.88%). This supports a systematic
provider/adjustment-convention explanation rather than a localized identity
failure. The largest individual return differences cluster in FLEX; large price
scale differences also appear in BDX, FDX and WDC.

## 11. Top 20 discrepancies

Provider abbreviations: `Massive adj.` = Massive `adjusted=true`; `EODHD adj.` =
validated `eodhd_adjusted_derived` logical series.

| security_id | Original ticker | Rebuilt alias | Signal date | Field | Original | Rebuilt | Absolute diff. | Original provider | Rebuilt provider | Probable reason |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-12-14 | 60d return | 0.00069614 | 0.39770493 | 0.39700879 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-12-19 | 60d return | -0.08700000 | 0.27521430 | 0.36221430 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-12-14 | 20d return | -0.20849286 | 0.10552383 | 0.31401669 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-12-19 | 20d return | -0.23400000 | 0.06989502 | 0.30389502 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-12-14 | entry price | 28.730000 | 20.569435 | 8.160565 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-05-12 | entry price | 23.610000 | 16.903760 | 6.706240 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-12-19 | entry price | 30.000000 | 21.478743 | 8.521257 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2022-10-27 | entry price | 19.080000 | 13.660487 | 5.419513 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-05-11 | entry price | 23.130000 | 16.560140 | 6.569860 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2023-01-13 | entry price | 25.030000 | 17.920475 | 7.109525 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `dcbb96bc-470c-5d68-8325-ca4869588cae` | FLEX | FLEX | 2022-11-01 | entry price | 19.630000 | 14.054335 | 5.575665 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `37a5417c-9d37-58aa-a285-26c6afbae668` | BDX | BDX | 2023-07-24 | entry price | 277.410000 | 204.365326 | 73.044674 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `80147f52-a034-5697-bf45-0c59b2c201a7` | FDX | FDX | 2023-03-17 | entry price | 219.990000 | 165.176130 | 54.813870 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `80147f52-a034-5697-bf45-0c59b2c201a7` | FDX | FDX | 2023-04-05 | entry price | 231.010000 | 173.450390 | 57.559610 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `d1e56104-3d99-518e-88ce-a9be6b90213f` | WDC | WDC | 2023-07-27 | entry price | 42.310000 | 31.824534 | 10.485466 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `d1e56104-3d99-518e-88ce-a9be6b90213f` | WDC | WDC | 2023-08-31 | entry price | 45.310000 | 34.081086 | 11.228914 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `d1e56104-3d99-518e-88ce-a9be6b90213f` | WDC | WDC | 2024-01-25 | entry price | 58.860000 | 44.273071 | 14.586929 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `d1e56104-3d99-518e-88ce-a9be6b90213f` | WDC | WDC | 2023-08-01 | entry price | 42.300000 | 31.817039 | 10.482961 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `d1e56104-3d99-518e-88ce-a9be6b90213f` | WDC | WDC | 2024-03-26 | entry price | 68.980000 | 51.885116 | 17.094884 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |
| `d1e56104-3d99-518e-88ce-a9be6b90213f` | WDC | WDC | 2024-04-01 | entry price | 69.500000 | 52.276258 | 17.223742 | Massive adj. | EODHD adj. | ADJUSTMENT_DIFFERENCE |

## 12. Horizon completeness

| Run | Horizon | Signals | Complete / metric N | Incomplete | Classified reasons |
|---|---:|---:|---:|---:|---|
| ORIGINAL_FIXED | 1 | 4,831 | 4,829 | 2 | 2 research-window truncation |
| ORIGINAL_FIXED | 5 | 4,831 | 4,815 | 16 | 16 research-window truncation |
| ORIGINAL_FIXED | 10 | 4,831 | 4,806 | 25 | 25 research-window truncation |
| ORIGINAL_FIXED | 20 | 4,831 | 4,785 | 46 | 46 research-window truncation |
| ORIGINAL_FIXED | 60 | 4,831 | 4,656 | 175 | 172 truncation; 2 genuine Massive missing; 1 alias continuity |
| FIXED_REBUILT | 1 | 5,896 | 5,896 | 0 | none |
| FIXED_REBUILT | 5 | 5,896 | 5,882 | 14 | 14 research-window truncation |
| FIXED_REBUILT | 10 | 5,896 | 5,870 | 26 | 26 research-window truncation |
| FIXED_REBUILT | 20 | 5,896 | 5,849 | 47 | 47 research-window truncation |
| FIXED_REBUILT | 60 | 5,896 | 5,713 | 183 | 183 research-window truncation |

Research-window truncation was determined from the target XNYS session and was
never relabelled as a delisting. No incomplete rebuilt horizon was caused by a
security lifecycle termination.

## 13. ORIGINAL_FIXED vs FIXED_REBUILT metrics

Full event-set metrics quantify the total observed data/identity/infrastructure
effect, including additional warm-up-supported signals.

| Horizon/run | N | Mean return | Median return | Positive rate | Mean excess vs SPY | Median excess vs SPY |
|---|---:|---:|---:|---:|---:|---:|
| 20d ORIGINAL_FIXED | 4,785 | 1.847989% | 0.918868% | 55.464995% | 0.671604% | -0.214041% |
| 20d FIXED_REBUILT | 5,849 | 1.694411% | 0.956689% | 55.291503% | 0.722058% | -0.118909% |
| 20d difference | +1,064 | -0.153578 pp | +0.037821 pp | -0.173492 pp | **+0.050454 pp (+5.0454 bp)** | +0.095132 pp |
| 60d ORIGINAL_FIXED | 4,656 | 5.287829% | 2.694885% | 58.891753% | 1.918437% | -0.927401% |
| 60d FIXED_REBUILT | 5,713 | 4.382569% | 2.349370% | 57.360406% | 2.046079% | -0.502001% |
| 60d difference | +1,057 | -0.905259 pp | -0.345514 pp | -1.531346 pp | +0.127642 pp | +0.425400 pp |

The pre-registered Phase 1 diagnostic, 20-session mean excess return
`FIXED_REBUILT − ORIGINAL_FIXED`, is exactly `+0.0005045418723258147`, or
**+5.0454 bp**. This is a small positive directional change; it is descriptive,
not a claim of statistical or economic significance.

As a matched-pair sensitivity check, the 4,758 events complete at 20 sessions
in both runs have mean excess returns of 0.656013% original and 0.802174%
rebuilt, a difference of +14.6161 bp. At 60 sessions, 4,629 matched complete
events have 1.902099% original versus 2.265419% rebuilt mean excess, a
difference of +36.3320 bp. This paired result is diagnostic and does not replace
the pre-registered full-run comparison.

## 14. Determinism

**FIXED_REBUILT_DETERMINISM = PASS**

Both independent in-memory executions produced 5,896 events with identical
identifiers, scores, entry values and outcomes. Both canonical event digests are:

`7fae705c084ec82c332681578b37d76e1f010472abbb866dfa49e9d39355d1b6`

## 15. Phase 1 conclusion

The new security-id-native infrastructure materially changes many individual
price scales, features and outcomes because its adjusted logical histories are
not numerically identical to the old Massive histories. The change is fully
quantified and broad across securities/providers, while identity integrity and
determinism pass. The full-run 20-session mean excess metric moves +5.0454 bp;
the rebuilt run adds 1,065 signals net, predominantly because it has valid
pre-window warm-up.

Complete test suite: **184 passed, 0 failed** (one third-party deprecation
warning). No strategy, score, portfolio logic, production data or PIT result was
changed.

## 16. Phase 2 readiness

**READY_FOR_PHASE_2**

Reasons:

1. The original window and authoritative persisted source are verified.
2. All 4,831 original events map unambiguously to `security_id`.
3. `FIXED_REBUILT_DATA_INTEGRITY = PASS`.
4. `FIXED_REBUILT_DETERMINISM = PASS`.
5. Event-set and numeric discrepancies are fully quantified with no UNKNOWN
   exclusive-event cause and no unexplained critical integrity issue.

This is only a readiness decision. Phase 2 was not started.

## 17. Phase 2 research question

Phase 2 was opened to measure the event-study effect of replacing the approved
`FIXED_REBUILT` current-constituent universe with the validated historical PIT
universe while holding the security-id-native data and calculation pipeline
constant. No portfolio simulation was in scope.

The mandatory PIT integrity gate found a new outcome-coverage failure. In
accordance with the pre-registered protocol, Phase 2 stopped at that gate. The
PIT event-study results and universe-effect conclusion are therefore not
published.

## 18. Pre-registered primary metric

The unchanged pre-registered primary metric is PIT minus `FIXED_REBUILT`
20-XNYS-session mean excess return versus SPY. It was selected before observing
PIT financial results. It was not calculated or published because the integrity
gate failed. No secondary metric was substituted.

## 19. PIT integrity pre-flight

**PIT_DATA_INTEGRITY = FAIL**

| Check | Result |
|---|---:|
| Canonical PIT hash | `74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d` |
| XNYS sessions | 1,252 |
| IDENTITY_BLOCKED | 0 |
| Membership-window MATERIAL_DATA_GAP | 0 |
| Newly detected required outcome gaps | 222 unique security-sessions |
| Affected event-horizon pairs | 24 |
| Affected securities | 6 |
| Duplicate logical bars / invalid OHLCV | 0 / 0 |
| Ticker-only fallback / ticker-reuse leakage | 0 / 0 |
| Fabricated / synthetic / forward-filled / interpolated prices | 0 / 0 / 0 / 0 |
| Look-ahead | 0 |
| Temporal alias continuity | PASS |
| `security_id` authoritative | PASS |
| `MRP_OLD` audit-only/non-tradable | PASS |
| Natural lifecycle sessions preserved | 30 |

The prior readiness result covered membership-session eligibility and feature
history. This stricter Phase 2 gate also checks the forward observations needed
by signals emitted before a constituent leaves the index. Six histories are
complete during membership but do not contain enough validated post-removal or
post-alias observations to complete all required horizons. The existing
evidence does not support relabelling these observations as research-window
truncation, a proven temporary halt, or a supported terminal lifecycle event.
They therefore remain `GENUINE_MISSING_DATA` under the experiment's definition.

| Ticker | security_id | Membership exit | Last validated price | Existing event evidence | Affected signals and horizons | Unique missing sessions |
|---|---|---|---|---|---|---:|
| CERN | `7556317a-8d08-5a8f-aa95-76973fb31777` | 2022-06-08 | 2022-06-08 | `INDEX_REMOVAL_STILL_TRADING`, HIGH | 2022-05-04: 60d; 2022-05-31: 10d, 20d, 60d | 54 (2022-06-09–2022-08-25) |
| NLSN | `9b2793b9-27ef-515e-9f54-49f341f7ed56` | 2022-10-12 | 2022-10-12 | `INDEX_REMOVAL_STILL_TRADING`, HIGH | 2022-08-09: 60d | 15 (2022-10-13–2022-11-02) |
| WBA | `18726de7-5f34-5d86-a886-dcfc331b0c36` | 2025-08-28 | 2025-08-28 | `INDEX_REMOVAL_STILL_TRADING`, HIGH | 2025-08-06: 20d, 60d; 2025-08-14: 20d, 60d; 2025-08-20: 10d, 20d, 60d | 54 (2025-08-29–2025-11-13) |
| DAY | `51f5567e-647b-5136-a9d1-9bd0ddc9d01b` | 2026-02-09 | 2026-02-04 | `TICKER_CHANGE`, MEDIUM | 2025-11-12: 60d; 2026-02-03: 5d, 10d, 20d, 60d | 59 (2026-02-05–2026-04-30) |
| CTRA | `d47ba1df-c0d0-5767-b105-569310d659b2` | 2026-05-07 | 2026-05-07 | `INDEX_REMOVAL_STILL_TRADING`, HIGH | 2026-03-19: 60d | 26 (2026-05-08–2026-06-15) |
| EA | `ea064420-88f9-5a08-982c-28a3459de19b` | 2026-08-05 | 2026-08-10 | `INDEX_REMOVAL_STILL_TRADING`, HIGH | 2026-07-15: 20d; 2026-07-17: 20d; 2026-07-30: 10d, 20d; 2026-07-31: 10d, 20d | 14 (2026-08-11–2026-08-28) |

The 24 pairs overlap in time within each security; their union is exactly 222
missing `(security_id, XNYS session)` observations. No value was invented,
filled, interpolated, or replaced with a modern ticker's history.

## 20. PIT event-study results

**NOT PUBLISHED — STOP CONDITION.** A preliminary security-id-native signal
eligibility pass was required to identify which forward observations the
experiment needs. Once the 222 genuine gaps were detected, no PIT financial
summary was accepted or published.

## 21. BOTH invariance

**BOTH_INVARIANCE = NOT RUN.** Events checked, mismatches, and maximum numeric
difference are not applicable because the data-integrity gate precedes this
test.

## 22. FIXED_REBUILT vs PIT primary comparison

Not run. The approved `FIXED_REBUILT` baseline remains 5,896 events, with 5,849
completed 20-session outcomes, 1.694411% mean return, 0.956689% median return,
55.291503% positive rate, 0.722058% mean excess and -0.118909% median excess.
There is no publishable PIT counterpart and no universe-effect estimate.

## 23. Date-clustered bootstrap uncertainty

**DATE_CLUSTERED_BOOTSTRAP = NOT RUN.** No 10,000-resample interval, paired
interval, LOWER interval, or UPPER interval was calculated after the stop.

## 24. BOTH / PIT_ONLY / FIXED_ONLY decomposition

Not run or published. The event sets cannot be used for a universe-effect
conclusion while required forward observations are missing.

## 25. Arithmetic universe-effect bridge

**ARITHMETIC_BRIDGE = NOT RUN.** Removal effect, addition effect, total bridge,
and reconciliation error are not applicable.

## 26. Horizon completeness

The outcome preflight found 24 affected event-horizon pairs: five at 10 days,
nine at 20 days, nine at 60 days, and one at 5 days, with overlap across
horizons/signals. The complete PIT horizon table and metric Ns are not
published because the integrity gate failed.

## 27. Research-window truncation

Not tabulated for Phase 2. The 24 flagged pairs are not research-window
truncations: every target session is on or before 2026-09-22.

## 28. Security lifecycle truncation

The full lifecycle audit was not completed after the stop. The existing source
evidence does not prove that the six gaps may be treated as `ACQUISITION`,
`MERGER`, `BANKRUPTCY`, `DELISTING_OTHER`, or terminal `UNKNOWN` for this
experiment. A separate preliminary case for TWTR has no `NEXT_OPEN` after its
signal; it remains audit-only and was not assigned a synthetic signal-close
entry. It is not the cause of the 222-session integrity failure.

## 29. LOWER / PRIMARY / UPPER diagnostics

Not run. Diagnostic terminal-value bounds apply only to supported lifecycle
truncations; they cannot be used to mask genuine missing data. Consequently,
the direction of the primary 20-day effect under LOWER or UPPER is unknown.

## 30. Secondary horizons

Not run or published.

## 31. Score buckets

Not run for the Phase 2 comparison. Existing semantics remain unchanged:
20 belongs to `20-40`, 40 to `40-60`, 60 to `60-80`, and 80 to `80-100`.

## 32. Feature correlations

Not run for the Phase 2 comparison. No feature, weight, or methodology changed.

## 33. Market regimes

Not run for the Phase 2 comparison. No regime definition changed.

## 34. FIXED_REBUILT signal-expansion diagnostic

Not rerun after the integrity stop. The approved Phase 1 counts remain 4,831
`ORIGINAL_FIXED` events and 5,896 `FIXED_REBUILT` events. No Phase 1 result was
modified or reinterpreted.

## 35. SPY consistency diagnostic

Not run after the integrity stop. The approved Phase 1 metrics remain
unchanged; no unsupported explanation for their 60-session pattern is offered.

## 36. PIT determinism

**PIT_EVENT_DETERMINISM = NOT RUN.** The protocol requires a complete second
event-study execution, which was intentionally not started after the first pass
identified genuine missing data.

## 37. Phase 2 limitations

This experiment evaluates the historical behavior of `BREAKOUT_20D_VOLUME`
after replacing a fixed/current S&P 500 universe with a validated historical
Point-in-Time S&P 500 universe while holding the rebuilt security_id-native
data/infrastructure constant.

It does **not** establish that `BREAKOUT_20D_VOLUME` adds incremental value
relative to:

- a generic trend-following strategy;
- random eligible signals; or
- another appropriate control strategy.

That question remains untested and requires a separate experiment. Historical
research performance is not a statement about future expected returns. In this
run, even historical PIT performance remains unpublished because the integrity
precondition failed.

## 38. Phase 3 readiness

**NOT_READY_FOR_PHASE_3**

Exact reasons:

1. `PIT_DATA_INTEGRITY = FAIL`.
2. `GENUINE_MISSING_DATA = 222` required security-sessions, not zero.
3. `PIT_EVENT_DETERMINISM`, `BOTH_INVARIANCE`, `ARITHMETIC_BRIDGE`, and
   `DATE_CLUSTERED_BOOTSTRAP` were not run after the mandatory stop.
4. The complete truncated-event audit, LOWER/PRIMARY/UPPER diagnostics,
   feature/regime comparison, signal-expansion diagnostic, and SPY consistency
   diagnostic remain incomplete.

No portfolio simulation was run, no CAGR was calculated, no optimization was
performed, and no strategy, score, portfolio, membership, or market-data record
was changed. No commit or tag was created.

## 39. PHASE 2A — FORWARD-HORIZON AND SYSTEMIC LIFECYCLE INTEGRITY RESOLUTION

### A. Original Phase 2 integrity failure

This section preserves the Phase 2 stop condition and adds evidence; it does not
rewrite the state known when Phase 2 stopped. The immutable audit universe was
222 unique `(security_id, XNYS session)` observations, 24 event-horizon pairs
and six securities. The canonical PIT hash remains
`74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d`.
No financial Phase 2 analysis was resumed.

### B. Exact blocker inventory

All 24 original pairs are preserved below. `Next open` is based only on a
legitimate bar after applying the authoritative last-trading boundary. Every
signal close was present. All membership and alias intervals use half-open
semantics `[valid_from, valid_to)`.

| Security | signal | close | next expected | Next open | horizon | target | legitimate last | first missing | missing |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| WBA | 2025-08-06 | 11.83 | 2025-08-07 | YES | 20 | 2025-09-04 | 2025-08-27 | 2025-08-29 | 4 |
| WBA | 2025-08-06 | 11.83 | 2025-08-07 | YES | 60 | 2025-10-30 | 2025-08-27 | 2025-08-29 | 44 |
| WBA | 2025-08-14 | 12.04 | 2025-08-15 | YES | 20 | 2025-09-12 | 2025-08-27 | 2025-08-29 | 10 |
| WBA | 2025-08-14 | 12.04 | 2025-08-15 | YES | 60 | 2025-11-07 | 2025-08-27 | 2025-08-29 | 50 |
| WBA | 2025-08-20 | 12.20 | 2025-08-21 | YES | 10 | 2025-09-04 | 2025-08-27 | 2025-08-29 | 4 |
| WBA | 2025-08-20 | 12.20 | 2025-08-21 | YES | 20 | 2025-09-18 | 2025-08-27 | 2025-08-29 | 14 |
| WBA | 2025-08-20 | 12.20 | 2025-08-21 | YES | 60 | 2025-11-13 | 2025-08-27 | 2025-08-29 | 54 |
| DAY | 2025-11-12 | 68.99 | 2025-11-13 | YES | 60 | 2026-02-10 | 2026-02-03 | 2026-02-05 | 4 |
| DAY | 2026-02-03 | 69.86 | 2026-02-04 | NO — lifecycle | 5 | 2026-02-10 | 2026-02-03 | 2026-02-05 | 4 |
| DAY | 2026-02-03 | 69.86 | 2026-02-04 | NO — lifecycle | 10 | 2026-02-18 | 2026-02-03 | 2026-02-05 | 9 |
| DAY | 2026-02-03 | 69.86 | 2026-02-04 | NO — lifecycle | 20 | 2026-03-04 | 2026-02-03 | 2026-02-05 | 19 |
| DAY | 2026-02-03 | 69.86 | 2026-02-04 | NO — lifecycle | 60 | 2026-04-30 | 2026-02-03 | 2026-02-05 | 59 |
| CERN | 2022-05-04 | 94.37 | 2022-05-05 | YES | 60 | 2022-08-01 | 2022-06-07 | 2022-06-09 | 36 |
| CERN | 2022-05-31 | 94.85 | 2022-06-01 | YES | 10 | 2022-06-14 | 2022-06-07 | 2022-06-09 | 4 |
| CERN | 2022-05-31 | 94.85 | 2022-06-01 | YES | 20 | 2022-06-29 | 2022-06-07 | 2022-06-09 | 14 |
| CERN | 2022-05-31 | 94.85 | 2022-06-01 | YES | 60 | 2022-08-25 | 2022-06-07 | 2022-06-09 | 54 |
| NLSN | 2022-08-09 | 27.4601 | 2022-08-10 | YES | 60 | 2022-11-02 | 2022-10-11 | 2022-10-13 | 15 |
| CTRA | 2026-03-19 | 33.90 | 2026-03-20 | YES | 60 | 2026-06-15 | 2026-05-06 | 2026-05-08 | 26 |
| EA | 2026-07-15 | 207.27 | 2026-07-16 | YES | 20 | 2026-08-12 | 2026-08-04 | 2026-08-11 | 2 |
| EA | 2026-07-17 | 208.90 | 2026-07-20 | YES | 20 | 2026-08-14 | 2026-08-04 | 2026-08-11 | 4 |
| EA | 2026-07-30 | 209.59 | 2026-07-31 | YES | 10 | 2026-08-13 | 2026-08-04 | 2026-08-11 | 3 |
| EA | 2026-07-30 | 209.59 | 2026-07-31 | YES | 20 | 2026-08-27 | 2026-08-04 | 2026-08-11 | 13 |
| EA | 2026-07-31 | 209.86 | 2026-08-03 | YES | 10 | 2026-08-14 | 2026-08-04 | 2026-08-11 | 4 |
| EA | 2026-07-31 | 209.86 | 2026-08-03 | YES | 20 | 2026-08-28 | 2026-08-04 | 2026-08-11 | 14 |

The exact machine-readable inventory additionally records company name,
`security_id`, dated ticker/alias, membership and alias intervals, both
providers, prior lifecycle metadata and full provenance in ignored
`data/phase2a_lifecycle/blocker_inventory.csv`.

### C. CERN forensic audit

`7556317a-8d08-5a8f-aa95-76973fb31777`, membership
`[2010-04-29, 2022-06-08)`. Oracle announced the $95 cash acquisition on
2021-12-20; the merger closed 2022-06-08 and Nasdaq trading was suspended
before that day's open. Therefore 2022-06-07 is the last legitimate regular
session. EODHD's 2022-06-08 bar is a post-termination provider artefact;
Massive ends on 2022-06-07. The 54 unique affected sessions are all later than
legitimate termination. Final classification: `ACQUISITION`, transaction
`CASH`, `SECURITY_LIFECYCLE_TRUNCATION` ([SEC 8-K](https://www.sec.gov/Archives/edgar/data/804753/000119312522169841/d223229d8k.htm)).

### D. NLSN forensic audit

`9b2793b9-27ef-515e-9f54-49f341f7ed56`, membership
`[2013-07-09, 2022-10-12)`. The $28 cash transaction was announced 2022-03-29,
closed 2022-10-11, and NYSE suspension occurred before the 2022-10-12 open.
Massive ends 2022-10-11; EODHD's 2022-10-12 bar is not legitimate regular
trading. All 15 affected sessions are post-history. Final classification:
`ACQUISITION`, `CASH`, `SECURITY_LIFECYCLE_TRUNCATION`
([SEC 8-K](https://www.sec.gov/Archives/edgar/data/1492633/000119312522260583/d407513d8k.htm)).

### E. WBA forensic audit

`18726de7-5f34-5d86-a886-dcfc331b0c36`, membership
`[1979-12-31, 2025-08-28)`. Announced 2025-03-06, closed 2025-08-28, with
trading ceased before that open; 2025-08-27 is the last legitimate session and
Massive ends there. Consideration is $11.45 cash plus one **non-transferable**
right per share to receive up to $3.00 cash from 70% of future net VillageMD
monetization proceeds. Transaction type is therefore conservatively `OTHER`,
not pure cash. All 54 affected sessions are post-history. Final classification:
`ACQUISITION`, `SECURITY_LIFECYCLE_TRUNCATION`
([SEC closing release](https://www.sec.gov/Archives/edgar/data/1618921/000119312525190603/d87240dex991.htm)). No terminal value was assigned.

### F. DAY forensic audit

`51f5567e-647b-5136-a9d1-9bd0ddc9d01b`, membership
`[2021-09-20, 2026-02-09)`. Stable CIK `0001725057`, CUSIP `15677J108`, ISIN
`US15677J1088` and OpenFIGI `BBG005D7PF34` prove that CDAY and DAY are the same
security. The temporal chain is CDAY `[2021-09-20, 2024-02-01)`, DAY
`[2024-02-01, 2026-02-09)`. The $70 cash acquisition was announced 2025-08-21,
closed 2026-02-04, and NYSE suspended trading on 2026-02-04; last regular
session is 2026-02-03. Massive ends there. The EODHD closing-day bar is an
artefact. All 59 affected sessions are post-history. The 2026-02-03 signal has
no legitimate 2026-02-04 `NEXT_OPEN`; its four affected horizon rows are
non-executable lifecycle cases, not fabricated entries. Final classification:
`ACQUISITION`, `CASH`, `SECURITY_LIFECYCLE_TRUNCATION`
([NYSE/SEC notice](https://www.sec.gov/Archives/edgar/data/1725057/000087666126000087/ruleprovisionnotice.htm)).

### G. EA forensic audit

`ea064420-88f9-5a08-982c-28a3459de19b`, membership
`[2002-07-22, 2026-08-05)`. The $210 cash transaction was announced 2025-09-29
(agreement 2025-09-28), closed after trading on 2026-08-04, and Nasdaq
suspension was effective 2026-08-05. Massive ends 2026-08-04. EODHD bars dated
2026-08-05 through 2026-08-10 are provider artefacts and are not legitimate
regular sessions. All 14 affected sessions are post-history. Final
classification: `ACQUISITION`, `CASH`, `SECURITY_LIFECYCLE_TRUNCATION`
([Nasdaq alert](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-545)).

### H. CTRA identity/history audit

`d47ba1df-c0d0-5767-b105-569310d659b2`. Cabot Oil & Gas, not Cimarex, was the
surviving public issuer in the 2021 combination; the issuer retained CIK
`0000858470`, changed its legal name to Coterra, and changed its ticker from COG
to CTRA at the 2021-10-04 open. The corrected temporal chain is COG
`[2008-06-23, 2021-10-04)` and CTRA `[2021-10-04, 2026-05-07)` under one
`security_id`. No ticker/name-only join is used
([SEC issuer release](https://www.sec.gov/Archives/edgar/data/858470/000110465921122041/tm2129019d1_ex99-1.htm)).

The current gap is unrelated to that alias transition. The Devon agreement was
dated 2026-02-01, announced 2026-02-02 and closed 2026-05-07. CTRA trading was
suspended on 2026-05-07; 2026-05-06 was the last regular session. Consideration
was 0.70 DVN share per CTRA share, plus cash only for fractional shares. Massive
ends 2026-05-06; the EODHD 2026-05-07 bar is an artefact. The 26 affected
sessions are post-history. Final classification: `MERGER`, `STOCK`,
`SECURITY_LIFECYCLE_TRUNCATION`
([NYSE/SEC notice](https://www.sec.gov/Archives/edgar/data/858470/000087666126000399/ruleprovisionnotice.htm)).

### I. TWTR NEXT_OPEN executability audit

`ae13e1b5-7a16-59c1-95ce-2bfa52b340d7` emitted the causal signal on
2022-10-27 at a 53.70 close. The next XNYS session was 2022-10-28. The merger
closed 2022-10-27, trading was suspended before the 2022-10-28 open, and both
EODHD and Massive end 2022-10-27. No legitimate `NEXT_OPEN` or entry price
existed. Exact classification: `NON_EXECUTABLE_LIFECYCLE_TERMINATION`
([SEC 8-K](https://www.sec.gov/Archives/edgar/data/1418091/000119312522272772/d411753d8k.htm)).

### J. Systemic lifecycle inventory

The audit examined every one of the 603 PIT securities, not only signal
blockers. Exactly 39 validated logical price histories end before 2026-09-22:

| Classification | Count | Securities |
|---|---:|---|
| `EVIDENCED_LIFECYCLE_TERMINATION` | 9 | CERN, NLSN, TWTR, SIVB, ATVI, WBA, DAY, CTRA, EA |
| `RECORDED_BUT_NOT_EVIDENCED` | 18 | INFO_OLD1, RAL_OLD, DISCA, CTXS, FRC, PXD, WRK, GPS, MRO, CTLT, DFS, JNPR, ANSS, HES, IPG, K, HOLX, AVB |
| `UNCLASSIFIED_EARLY_PRICE_TERMINATION` | 12 | KSU, XLNX, PBCT, DRE, ABMD, DISH, KLG, ZIMV, HBI, CMA, SEE, LEG |
| `NATURAL_DATASET_BOUNDARY` | 0 | — |
| `OTHER_EXPLAINED` | 0 | — |

The evidenced reasons reconcile to acquisition 7, merger 1, bankruptcy 1 and
other delisting 0. For every row the operational inventory records membership,
logical and legitimate endpoints, evidence status, PIT-signal presence,
signals within 60 XNYS sessions of termination, and whether the security caused
the Phase 2 gate. `SYSTEMIC_LIFECYCLE_AUDIT = FAIL` because 30 early endings
remain insufficiently evidenced.

### K. Lifecycle cases by termination year

| Year | Total | Evidenced | Recorded, not evidenced | Unclassified |
|---:|---:|---:|---:|---:|
| 2021 | 1 | 0 | 0 | 1 |
| 2022 | 11 | 3 | 4 | 4 |
| 2023 | 3 | 2 | 1 | 0 |
| 2024 | 6 | 0 | 5 | 1 |
| 2025 | 10 | 1 | 6 | 3 |
| 2026 | 8 | 3 | 2 | 3 |

The 2025–2026 group has 14 unresolved of 18 (77.8%); 2021–2024 has 16 of 21
(76.2%). Recent years contain four of the six event-horizon blockers, but the
systemic unresolved rate is not materially disproportionate. No causal claim is
made from this distribution.

### L. Why the six escaped prior validation

- CERN, NLSN, WBA and EA were labelled `INDEX_REMOVAL_STILL_TRADING` by the
  POC3 boundary heuristic. Closing/suspension evidence was absent; in three
  cases an EODHD closing-or-post-close artefact reinforced the stale label.
- DAY's existing `TICKER_CHANGE` metadata correctly described CDAY→DAY but did
  not contain the later acquisition or the no-NEXT_OPEN boundary.
- CTRA lacked the documentary COG→CTRA temporal split and the later Devon
  lifecycle event; the current gap is the later merger, not the alias change.
- The earlier execution-readiness pass tested identity and coverage during
  membership. It was not event-aware and did not inspect every signal's
  required post-membership forward horizon. Phase 2 was the first such gate.

The same general failure mode exists in the other 30 early histories listed in
section J. Their resolution is deliberately **pending authoritative lifecycle
evidence**; none was silently promoted to an evidenced event.

### M. Provider/source currency analysis

The affected lifecycle taxonomy came from the EODHD POC3 validated security
master generated 2026-09-28, whose declared price coverage ends 2026-09-22.
Thus price coverage was current to the research end, while the event taxonomy
was generic or stale for these corporate actions. Massive spot checks, using
the already-authorized integration, independently end on CERN 2022-06-07,
NLSN 2022-10-11, WBA 2025-08-27, DAY 2026-02-03, CTRA 2026-05-06, EA
2026-08-04 and TWTR 2022-10-27. No missing case reflects continued legitimate
trading available only from Massive.

### N. M&A signal diagnostic ledger

A causal, signal-only pass used unchanged `BREAKOUT_20D_VOLUME` rules and did
not read forward outcomes. Across eight evidenced acquisition/merger securities
it found 49 diagnostic signals: 20 `PRE_ANNOUNCEMENT`, 1
`ON_ANNOUNCEMENT_DATE`, 28 `POST_ANNOUNCEMENT_PRE_CLOSE`, and 0
`POST_CLOSE_INVALID`. The eight transactions comprise six `CASH`, one `STOCK`,
zero `MIXED`, and one `OTHER`; one contains contingent/non-tradable
consideration. No signal was excluded and no performance was computed.

### O. Before/after reconciliation of 222 security-sessions

| Reconciliation class | Unique security-sessions |
|---|---:|
| `SECURITY_LIFECYCLE_TRUNCATION` | 222 |
| `PROVIDER_GAP_RESOLVED` | 0 |
| `ALIAS_CONTINUITY_RESOLVED` | 0 |
| `TEMPORARY_HALT` | 0 |
| `GENUINE_MISSING_DATA` | 0 |
| `UNKNOWN` | 0 |
| **Total** | **222** |

All original observations reconcile. Remaining affected securities: 0;
remaining affected event-horizon pairs: 0; remaining genuine missing
security-sessions: 0; `IDENTITY_BLOCKED = 0`; `MATERIAL_DATA_GAP = 0`.
The reconciliation classifies facts only. It does not assign consideration as
a terminal value and does not compute a return.

### P. Final integrity decision

**NOT_READY_TO_RESUME_PHASE_2**

The six blockers, TWTR executability and CTRA identity/history are resolved,
but the strict readiness rule still fails because
`RECORDED_BUT_NOT_EVIDENCED = 18`,
`UNCLASSIFIED_EARLY_PRICE_TERMINATION = 12`, and
`SYSTEMIC_LIFECYCLE_AUDIT = FAIL`. The M&A diagnostic ledger is complete, but
lifecycle metadata is not yet sufficiently auditable across the whole PIT
universe. No exception was silently accepted.

Data safety: no synthetic bar, forward-fill, interpolation, ticker-only
fallback, successor-price substitution, fabricated `NEXT_OPEN`, or fabricated
terminal value was used. The operational JSON/CSV artifacts remain under the
ignored `backend/data/phase2a_lifecycle/` directory.

## 40. PHASE 2B — SYMMETRIC MEMBERSHIP-BOUNDARY AND WARM-UP AUDIT

This section resolves the mandatory pre-membership warm-up check and completes
the symmetric lifecycle review. It is a **signal-only/data-boundary audit**. It
does not calculate a return, financial metric, portfolio result or replacement
Phase 2 result. The approved Phase 1 numbers are unchanged.

### 40.1 Exact production warm-up

The binding production requirement is `SMA_200` in `FeatureEngine`:
`close.rolling(200, min_periods=200)`. The evaluation-session close is the 200th
observation, so the exact requirement is **199 legitimate prior observations**
plus the evaluation session itself. It is not 220 sessions. The other strategy
inputs are no more restrictive: `SMA_50` needs 50 observations; momentum needs
the current close and lag 20; previous high, previous average volume and
previous average dollar volume each use `shift(1).rolling(20)`.

Membership remains half-open, `valid_from <= session < valid_to`, and controls
only signal eligibility. Feature calculation receives legitimate same-security
bars before entry. Forward evaluation may receive legitimate same-security bars
after removal. Neither side permits predecessor prices, successor prices,
ticker-only joins, interpolation or synthetic observations.

### 40.2 Pre-membership warm-up audit

All 99 eligible securities whose `valid_from` is inside 2021-09-27 through
2026-09-22 were checked against their complete logical history:

| Classification | Securities |
|---|---:|
| `SUFFICIENT_PRE_MEMBERSHIP_HISTORY` | 75 |
| `NATURAL_SHORT_PREHISTORY_EVIDENCED` | 24 |
| `INSUFFICIENT_PRE_MEMBERSHIP_HISTORY` | 0 |
| `UNKNOWN_PREHISTORY` | 0 |

`SNDK` is the exact boundary case: it has 199 legitimate observations before
its 2025-11-28 entry and is fully evaluable on that session. The complete
99-row inventory, including `security_id`, entry ticker, `valid_from`, first
legitimate date, first stored logical bar, prior-observation count and earliest
causally evaluable session, is written to the ignored operational file
`data/phase2b_symmetric/pre_membership_warmup.csv`.

The 24 naturally short histories are:

| Ticker | Entry | First legitimate market | Prior observations | Earliest fully evaluable |
|---|---:|---:|---:|---:|
| `MBC` | `2022-12-15` | `2022-12-09` | 4 | `2023-09-27` |
| `EMBC` | `2022-04-01` | `2022-03-21` | 9 | `2023-01-04` |
| `CEG` | `2022-02-02` | `2022-01-19` | 10 | `2022-11-02` |
| `VGNT` | `2026-04-01` | `2026-03-27` | 3 | not reached by research end |
| `KLG` | `2023-10-02` | `2023-09-27` | 3 | `2024-07-15` |
| `AMTM` | `2024-09-30` | `2024-09-24` | 4 | `2025-07-14` |
| `FTRE` | `2023-07-03` | `2023-06-16` | 10 | `2024-04-03` |
| `SOLS` | `2025-10-30` | `2025-10-30` | 0 | `2026-08-18` |
| `HONA` | `2026-06-29` | `2026-06-15` | 9 | not reached by research end |
| `FDXF` | `2026-06-01` | `2026-05-26` | 4 | not reached by research end |
| `GEHC` | `2023-01-04` | `2022-12-15` | 12 | `2023-10-03` |
| `SLVM` | `2021-10-01` | `2021-09-23` | 6 | `2022-07-11` |
| `Q` | `2025-11-03` | `2025-11-03` | 0 | `2026-08-20` |
| `VSNT` | `2026-01-05` | `2025-12-15` | 13 | not reached by research end |
| `SOLV` | `2024-04-01` | `2024-03-26` | 3 | `2025-01-10` |
| `ZIMV` | `2022-03-01` | `2022-02-16` | 8 | `2022-12-01` |
| `MBGL` | `2026-07-01` | `2026-06-26` | 3 | not reached by research end |
| `PHIN` | `2023-07-05` | `2023-06-28` | 4 | `2024-04-12` |
| `GEV` | `2024-04-02` | `2024-03-27` | 3 | `2025-01-13` |
| `VLTO` | `2023-10-02` | `2023-09-27` | 3 | `2024-07-15` |
| `ONL` | `2021-11-15` | `2021-11-01` | 5 | `2022-08-24` |
| `KVUE` | `2023-08-25` | `2023-05-04` | 78 | `2024-02-20` |
| `KD` | `2021-11-04` | `2021-10-22` | 9 | `2022-08-09` |
| `RAL_OLD` | `2025-06-30` | `2025-06-30` | 0 | not reached by research end |

Every natural-short classification has high-confidence listing/spin-off evidence
in `PIT_PHASE2B_BOUNDARY_EVIDENCE.json`. Parent-company or predecessor history
was not used. Provider rows before the evidenced first legitimate date for `Q`
and `SOLS` were rejected as pre-listing artefacts rather than counted as warm-up.

### 40.3 Ralliant identity finding

`RAL_OLD` is not a valid logical history for the 2025 Ralliant membership. The
persisted row contains Reynolds American CIK `0000081870`, CUSIP `751277104`
and 1997-2022 prices, whereas Ralliant is CIK `0002041385`, was separated from
Fortive and began regular-way trading on 2025-06-30. The unrelated Reynolds
history is explicitly excluded from features. No automatic repair or ticker
join was made.

The Ralliant membership is one half-open session,
`[2025-06-30, 2025-07-01)`, on its first regular-way trading day. The correct
security necessarily had zero prior observations versus the binding 199. It
therefore could not produce a `BREAKOUT_20D_VOLUME` signal in that interval,
irrespective of the absent correctly identified price row. This remains visible
as a `NON_BLOCKING_DOCUMENTATION_GAP`, not a resolved identity and not a silent
deletion ([SEC separation evidence](https://www.sec.gov/Archives/edgar/data/2041385/000110465925064115/tm2429554d14_ex99-2.htm)).

### 40.4 Phase 1 warm-up diagnostic

The approved 710 `WARMUP_DIFFERENCE` events were reproduced exactly with a
signal-only pass; persisted outcomes were not recomputed:

| Diagnostic | Result |
|---|---:|
| Differences reproduced | 710 / 710 |
| Securities involved | 302 |
| Securities whose PIT membership starts inside the window | 40 |
| Prior input history starting at/near PIT `valid_from` | 1 |
| Securities with legitimate pre-research history | 302 |
| Histories already restored by `FIXED_REBUILT` | 302 |
| Additional legitimate pre-research bars materialized | 78,297 |
| Natural-short listing histories in the 710 | 0 |
| Membership-boundary truncation | 0 events |
| Research-window input truncation | 710 events |
| Other / unresolved | 0 / 0 |

The first approved original event is 2022-07-20. The original Massive inputs
began at the 2021-09-27 research boundary, so they could not warm `SMA_200`
before that point. `FIXED_REBUILT` restored legitimate pre-research history.
This is a research-input boundary effect, not evidence that PIT membership was
incorrectly used as a price boundary.

### 40.5 Post-membership and systemic lifecycle audit

Across all 603 eligible PIT securities, 100 securities are removed during the
window; 69 have legitimate same-security observations after index removal.
There are 37 evidence-backed actual lifecycle terminations. No security with an
eligible PIT signal requires an unresolved price extension for `NEXT_OPEN` or
1/5/10/20/60-session evaluation. No new bar was downloaded or restored in this
audit. All original 222 Phase 2 missing security-sessions remain reconciled as
actual lifecycle truncation, with genuine missing data zero.

The 28 previously undocumented terminal cases now have evidence-backed closing
and last-regular-trading boundaries. Targeted results are:

| Case | Verified result |
|---|---|
| `XLNX` | AMD stock acquisition; last regular session 2022-02-11. |
| `PBCT` | M&T stock merger; last regular session 2022-04-01. |
| `DRE` | Prologis stock merger; last regular session 2022-09-30. |
| `INFO_OLD1` | S&P Global stock merger; last regular session 2022-02-25. |
| `PXD` | ExxonMobil stock acquisition; last regular session 2024-05-02. |
| `MRO` | ConocoPhillips stock acquisition; last regular session 2024-11-22. |
| `HES` | Chevron stock acquisition; last regular session 2025-07-18. |
| `DFS` | Capital One stock merger; last regular session 2025-05-16. |
| `ABMD` | $380 cash plus non-tradable CVR; last regular session 2022-12-21. |
| `HOLX` | $76 cash plus non-tradable CVR; last regular session 2026-04-06. |
| `DISCA` | DISCA ceased after 2022-04-08; WBD began 2022-04-11. No ticker-only continuation was used. |
| `GPS` | Same security changed ticker GPS→GAP on 2024-08-22; cached extension remains incomplete but is research-invariant. |
| `KLG` | Evidenced 2023 spin-off and later cash acquisition; no parent-price backfill. |
| `ZIMV` | Evidenced 2022 spin-off and later cash acquisition; no parent-price backfill. |
| `HBI` | Contrary to the continued-trading hypothesis, acquisition closed 2025-12-01; last regular session 2025-11-28. |
| `LEG` | Contrary to the continued-trading hypothesis, merger closed 2026-08-26; last regular session 2026-08-25. |
| `SEE` | Contrary to the continued-trading hypothesis, cash acquisition closed 2026-04-09; last regular session 2026-04-08. |

For `FRC`, the last regular NYSE session is 2023-04-28 and FDIC receivership
began before the 2023-05-01 market open. No later NYSE session exists in either
validated provider series. The exact effective date of formal exchange
delisting, the first exact OTC session, and a conclusive identifier/legal bridge
to the later `FRCB` quotation were not established by the cached authoritative
material. They remain explicitly unresolved rather than inferred. `FRCB` was
not joined; JPMorgan is not treated as a successor equity. `FRC` had complete
feature history and zero eligible PIT signals, so this unresolved chronology
cannot alter a Phase 2 feature, entry or forward observation. The requested
LOWER/PRIMARY/UPPER economic treatment remains deferred.

### 40.6 Research relevance and residual documentation

| Relevance class | Count |
|---|---:|
| `BLOCKING_RESEARCH_GAP` | 0 |
| `BLOCKING_UNKNOWN` | 0 |
| `NON_BLOCKING_DOCUMENTATION_GAP` | 3 |

The three visible documentation gaps are:

- `FRC`: FRC→FRCB legal/identifier continuity remains unproved. Complete
  prehistory and zero eligible signals prove that no Phase 2 feature, entry or
  horizon can change.
- `GPS`: the proved same-security GPS→GAP series is not materialized after
  2024-10-15. Membership ended 2022-02-03, prehistory is complete and there are
  zero eligible signals, so no Phase 2 observation can reach the missing span.
- `RAL_OLD`: the stored identity/history is another issuer. The correct
  Ralliant security had no public prehistory and was eligible for only its first
  trading session, making a 200-observation feature row mathematically
  impossible. No signal, `NEXT_OPEN` or horizon can change.

The full proof fields — unresolved fact, evidence limitation, signal count and
dates, feature/entry/horizon invariance — are in the ignored
`data/phase2b_symmetric/non_blocking_documentation_gaps.csv`.

### 40.7 Final gates

| Gate | Result |
|---|---|
| `SYSTEMIC_LIFECYCLE_AUDIT` | `PASS` |
| `PRE_MEMBERSHIP_WARMUP_AUDIT` | `PASS` |
| `SYMMETRIC_MEMBERSHIP_BOUNDARY_AUDIT` | `PASS` |
| `PHASE_2B_DETERMINISM` | `PASS` |
| `GENUINE_MISSING_DATA` | `0` |
| `IDENTITY_BLOCKED` | `0` |
| `MATERIAL_DATA_GAP` | `0` |
| `BLOCKING_UNKNOWN` | `0` |
| Original 222 observations reconciled | `YES` |

Full test suite: **217 passed, 0 failed**. The single unchanged external
Starlette/httpx deprecation warning remains informational.

Deterministic Phase 2B digest:
`49c62e9613d08d267509218dc6d4dd01931497908406dd6ff6e53f4ac225ca11`.

**SYMMETRIC_MEMBERSHIP_BOUNDARY_AUDIT = PASS**

**READY_TO_RESUME_PHASE_2**

This status authorizes human review only. Financial Phase 2 was not resumed.
