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
