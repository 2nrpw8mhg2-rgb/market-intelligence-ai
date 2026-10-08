# Phase 4A — Pre-Registered Controls, Prospective Holdout & Robustness Protocol

## 1. Document status and scope

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

This document defines the Phase 4A research protocol. It is a design artifact only. No new financial backtest, randomized portfolio simulation, portfolio metric, market-data ingestion, database mutation, scheduler activation, strategy change, score change, or production deployment was performed while preparing it.

The protocol is not final until it receives explicit human approval. Until then, Phase 4B execution is prohibited.

Research question: **Does the frozen PIT breakout strategy outperform a distribution of PIT-valid simple-trend portfolios under comparable economic constraints, exposure, and risk?**

Proposed terminal status for this design stage:

`PHASE_4A_DESIGN_READY_FOR_REVIEW`

### Required deliverable map

The required review topics are covered as follows: research question (Sections 1 and 3); frozen PIT baseline (Sections 2 and 7); Phase 3 universe-bias interpretation (Section 4); parameter provenance (Section 6); prospective holdout and daily registration (Section 23); primary trend and random-entry controls (Sections 9–12); candidate diagnostics (Section 8); SPY, exposure, and beta (Sections 14 and 16); fairness matrix (Section 13); endpoint and statistical evidence (Section 15); power (Section 21); decision matrix and REVIEW escalation (Section 24); concentration, path, and costs (Sections 17–20); historical OOS (Section 22); reproducibility and holdout integrity (Sections 12 and 23); engineering feasibility, Phase 4B sequence, and limitations (Sections 24.6–24.8); and approval decisions (Section 25).

## 2. Frozen recovery point and prerequisites

**Decision status: FROZEN**

Phase 4A starts from the published Phase 3C recovery point:

| Item | Frozen value |
|---|---|
| Branch | `main` |
| Commit | `a88a5e4ebe67fb220012c90ed3a5f25bfb30f4c7` |
| Tag | `v0.9.3-pit-portfolio-attribution` |
| Alembic repository head | `20261001_0010` |
| PIT research window | 2021-09-27 through 2026-09-22 |
| Universe | identity-native S&P 500 point-in-time universe |
| Strategy | `BREAKOUT_20D_VOLUME` |
| Entry | next session open |
| Holding period | 20 sessions |
| Position size | 10% of equity |
| Maximum concurrent positions | 10 |
| Slippage | 5 basis points per side |
| Initial capital | USD 100,000 |
| Final equity | USD 243,797.07 |
| CAGR | 19.571826% |
| Annualized volatility | 18.3534% |
| Maximum drawdown | −21.0174% |
| Sharpe | 1.070165 |
| Average invested exposure | 89.3999% |
| Accepted positions / closed trades | 602 / 593 |
| Frozen PIT digest | `5c6a0e5edf2d51f56ba2f456f978aadd8dcf550061a15cb970da90fbc2026792` |

The published ancestry from Phase 2 through Phase 3A, Phase 3B, and Phase 3C was verified before this protocol was drafted. The working tree was clean at the start of Phase 4A.

No Phase 4 experiment may begin unless the published checkpoint, migration head, PIT-universe hash, portfolio-engine invariants, and Phase 3 artifacts pass their existing integrity checks unchanged.

## 3. Questions addressed by Phase 4

**Decision status: FROZEN**

Phase 4 is limited to the following questions:

1. Does the frozen breakout strategy outperform a fair, contemporaneous trend-following control under identical portfolio mechanics?
2. Does it outperform a generic random-entry control with the same opportunity timing and portfolio constraints?
3. Is any advantage economically material, statistically distinguishable, and robust to costs, start dates, ties, concentration, and market beta?
4. Can a genuinely prospective and sealed signal record be established after the historical analysis?

Phase 4 must not tune the breakout strategy, score weights, thresholds, holding period, sizing, capacity, execution assumptions, or lifecycle rules.

## 4. Existing evidence and interpretation boundary

**Decision status: FROZEN**

The Phase 3 findings are already known and therefore cannot be treated as prospectively independent evidence. In particular, `FIXED_REBUILT` retrospectively uses later-known S&P 500 membership and therefore contains retrospective universe-selection bias, including a survivorship-related mechanism. It is not a valid causal control for the PIT strategy.

The frozen dollar P&L identity is:

| Component | Difference |
|---|---:|
| BOTH | −USD 34,254.770316 |
| FIXED_ONLY | −USD 132,235.709385 |
| PIT_ONLY | −USD 5,140.644938 |
| Total | −USD 171,631.124639 |

The fixed-only component explains approximately 77.05% of the magnitude of the reported fixed-minus-PIT dollar difference. This is labeled `ACCOUNTING_IDENTITY — NOT CAUSAL_ATTRIBUTION`: it is not proof of causation or strategy quality.

The Phase 4 controls are designed because the prior fixed-universe comparison changed both constituent eligibility and opportunity availability. Phase 4 must instead hold the PIT universe and portfolio engine constant while changing only the signal-selection rule.

## 5. Historical in-sample classification

**Decision status: FROZEN**

The 2021-09-27 through 2026-09-22 research window is classified as:

`IN_SAMPLE_REUSED / PROVENANCE_UNKNOWN`

The window has been repeatedly inspected during Phases 1–3. It is not an out-of-sample test. Repository history shows when the parameters first appeared in this repository, but does not establish when or how the human researcher selected them. Consequently, Phase 4 results from this window must be described as robustness evidence on reused historical data, never as a fresh holdout result.

## 6. Parameter-provenance audit

**Decision status: FROZEN**

The earliest repository evidence for the scanner thresholds and score construction is commit `00db8d9050fcd8ce1d8a0cd13a0fbd317ce16c57`, dated 2026-09-24. The earliest repository evidence for the 20-session portfolio holding period, 10% sizing, 10-position capacity, and 5-basis-point slippage defaults is commit `6483f521465e68c3657e2f163b88474cb0caaea9`, also dated 2026-09-24. Both dates are after the research window ended.

| Parameter | Frozen value | Earliest repository evidence | Classification | Evidence boundary |
|---|---:|---|---|---|
| Breakout lookback | 20 sessions | `00db8d9` | `PROVENANCE_UNKNOWN` | Trading-range break rules are established in the literature, but the exact value and adoption date are not proven. |
| Relative-volume threshold | 1.5× | `00db8d9` | `PROVENANCE_UNKNOWN` | No pre-window source for the exact threshold was found. |
| Fast trend average | SMA 50 | `00db8d9` | `PROVENANCE_UNKNOWN` | Moving-average rules are conventional; the exact value and adoption date are not proven. |
| Slow trend average | SMA 200 | `00db8d9` | `PROVENANCE_UNKNOWN` | Moving-average rules are conventional; the exact value and adoption date are not proven. |
| Minimum prior ADV | USD 10 million | `00db8d9` | `PROVENANCE_UNKNOWN` | No pre-window source for the exact threshold was found. |
| Minimum price | USD 5 | `00db8d9` | `PROVENANCE_UNKNOWN` | No pre-window source for the exact threshold was found. |
| Score weights | 30/25/20/15/10 | `00db8d9` | `PROVENANCE_UNKNOWN` | No independent pre-window specification was found. |
| Score normalizers | 0.10/2.5/0.30/0.20/log liquidity | `00db8d9` | `PROVENANCE_UNKNOWN` | No independent pre-window specification was found. |
| Holding period | 20 sessions | `6483f52` | `PROVENANCE_UNKNOWN` | No pre-window specification was found. |
| Position size | 10% | `6483f52` | `PROVENANCE_UNKNOWN` | No pre-window specification was found. |
| Position capacity | 10 | `6483f52` | `PROVENANCE_UNKNOWN` | No pre-window specification was found. |
| Slippage | 5 bps per side | `6483f52` | `PROVENANCE_UNKNOWN` | No pre-window specification was found. |

The broad use of moving-average and trading-range-break rules is supported by Brock, Lakonishok, and LeBaron, [“Simple Technical Trading Rules and the Stochastic Properties of Stock Returns”](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x). That evidence does not prove that this project's exact thresholds were specified independently of the analyzed data.

No parameter is classified as independently pre-specified. Absence of provenance is not evidence that a parameter was data-mined; it means temporal independence is unknown.

## 7. Frozen breakout portfolio

**Decision status: FROZEN**

The treatment portfolio is the exact published PIT portfolio from Phase 3. Its signal, score, ordering, execution, lifecycle, and portfolio rules must remain byte-for-byte or configuration-hash equivalent to the checkpoint.

The following may not change:

- point-in-time universe and identity resolution;
- 20-session breakout rule;
- 1.5× relative-volume rule;
- 50/200-session trend filters;
- USD 10 million prior-ADV filter;
- USD 5 minimum price;
- score inputs, normalization, and weights;
- next-open entry;
- 20-session holding period;
- 10% sizing and 10-position capacity;
- 5-basis-point per-side slippage;
- missing-open, exit, removal, delisting, and terminal-event handling;
- cash treatment and mark-to-market conventions.

Any implementation mismatch blocks Phase 4B rather than being repaired during the experiment.

## 8. Feasibility census using contemporaneous inputs

**Decision status: FROZEN OBSERVATION**

A read-only feasibility census was performed over the 1,252 XNYS sessions in the existing PIT window. It used contemporaneous membership, price, trend, volume, and liquidity inputs through 2026-09-22 only. It did not calculate forward returns, portfolio returns, equity curves, or any post-boundary outcome.

| Daily quantity | Total | Mean | Median | P25 | P75 | Min | Max | Zero-candidate sessions | Sessions above 10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PIT members | — | 502.7268 | 503 | 502 | 503 | 502 | 505 | 0 | 1,252 |
| Native trend-eligible state | 222,291 | 177.5487 | 181.5 | 127 | 222 | 1 | 344 | 0 | 1,247 |
| Trend-state arrivals | 14,438 | 11.5319 | 9 | 5 | 15 | 0 | 195 | 23 | 558 |
| Breakout candidates | 5,398 | 4.3115 | 2 | 1 | 6 | 0 | 89 | 261 | 112 |

All 5,398 breakout candidates also met the native trend state on their signal date. The native trend process nevertheless creates materially more candidate arrivals than the breakout process. This confirms that a naïve trend control would change both signal definition and opportunity frequency.

These counts are feasibility evidence only and must not be interpreted as performance evidence.

## 9. Primary simple-trend control definition

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The primary control is the **opportunity-matched simple-trend control**.

### 9.1 Trend state

A security is trend eligible on session `t` only when all of the following are known using data available by the close of `t`:

- it is an eligible identity-native PIT constituent on `t`;
- `close_t > SMA50_t > SMA200_t`;
- `close_t >= USD 5`;
- prior average dollar volume meets the frozen USD 10 million liquidity floor;
- the required market-data identity is resolved and safe for execution;
- all standard lifecycle and data-integrity gates pass.

### 9.2 Trend-state arrival

A native trend signal occurs only on a false-to-true transition of the complete trend-eligibility state. Daily repeated eligibility is not a new signal. If a security enters the PIT universe while the complete state is already true, its first eligible membership session is a trend-state arrival. A new signal after a previous arrival requires a later false-to-true transition and remains subject to the frozen duplicate-position and re-entry rules.

### 9.3 Opportunity matching

For every session, the number of control candidate tickets equals the number of frozen breakout candidates on that same session. The control samples without replacement from the complete same-session trend-eligible pool, including securities that may also satisfy the breakout rule. It uses neither the breakout score nor any forward outcome.

If the trend pool contains fewer names than the breakout ticket count, all available trend names are selected and the shortfall is recorded before portfolio constraints are applied. The implementation must not borrow candidates from another date, relax eligibility, or manufacture candidates.

The selected tickets are then passed through the exact frozen portfolio engine. Capacity, existing positions, duplicate restrictions, missing opens, and lifecycle rules may reduce accepted positions in either portfolio.

## 10. Native simple-trend control

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The native simple-trend control uses every trend-state arrival described in Section 9.2 without matching its daily opportunity count to breakout candidates.

It is a secondary descriptive control because its opportunity frequency is structurally different. It answers whether the full native rule performs under the frozen portfolio engine; it does not by itself isolate signal quality from opportunity frequency.

Results from the native control may not override or replace the primary opportunity-matched comparison.

## 11. Generic random-entry control

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The generic random-entry control is a separate secondary control.

On each breakout opportunity date, it receives the same number of candidate tickets as the frozen breakout candidate count. Candidates are sampled without replacement from that session's identity-native PIT members that pass the same price, prior-ADV, market-data-identity, and lifecycle gates. It does not require a breakout or trend state and uses no forward data.

The selected names enter the same frozen portfolio engine with the same execution, holding, sizing, capacity, cost, and exit rules. Its random-number stream must be independent of both trend controls.

This control measures performance relative to generic eligible entry timing. It is not interchangeable with the simple-trend control.

## 12. Randomization, seed registry, and determinism

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The experiment will use exactly 1,000 registered seeds for each randomized control.

Before any control return is calculated, Phase 4B must persist a signed experiment manifest containing:

- recovery-point commit and tag;
- code and container digests;
- dependency lock and NumPy version;
- input-artifact hashes;
- PIT-universe hash;
- control definitions and exposure gates;
- seed indices `0` through `999`;
- random generator and derivation algorithm;
- all decision thresholds in this protocol.

The random generator is NumPy `Generator(PCG64DXSM)`, with the exact compatible NumPy version pinned. For seed index `i`, the generator seed is the first 128 bits of:

`SHA-256(manifest_hash || control_id || stream_id || i)`

Candidate inputs are sorted by stable `security_id` before random permutation. Separate `control_id` and `stream_id` values are mandatory for matched-trend, native-trend tie handling, generic-random, and bootstrap streams. No random stream may be reused across purposes.

Re-running the same manifest must reproduce candidate selections, accepted positions, daily returns, metrics, and artifact hashes exactly. Any mismatch sets `DETERMINISM = FAIL` and blocks interpretation.

## 13. Fairness and comparability matrix

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

| Dimension | Frozen breakout | Matched trend | Native trend | Generic random | SPY context |
|---|---|---|---|---|---|
| Identity-native PIT universe | Same | Same | Same | Same | Not applicable |
| Research dates | Same | Same | Same | Same | Same where available |
| Opportunity dates/count | Observed breakout | Exact daily match | Native arrivals | Exact daily match | Continuous holding |
| Candidate rule | Breakout + volume + trend | Trend state | Trend-state arrival | Eligible member | Index ETF |
| Score/order | Frozen score | Random permutation | Arrival then deterministic identity order; exact-tie sensitivity | Random permutation | Not applicable |
| Entry | Next open | Next open | Next open | Next open | Context series only |
| Hold | 20 sessions | 20 sessions | 20 sessions | 20 sessions | Continuous holding |
| Size/capacity | 10% / 10 | Same | Same | Same | Not comparable |
| Slippage | 5 bps/side | Same | Same | Same | Reported separately |
| Lifecycle rules | Same | Same | Same | Same | Not comparable |
| Cash mechanics | Same | Same | Same | Same | Not comparable |
| Exposure gate | Reference | Mandatory | Descriptive | Mandatory | Not comparable |

Classification key: `IDENTICAL`, `MATCHED_BY_DESIGN`, `MEASURED_DIFFERENCE`, and `NOT_DIRECTLY_COMPARABLE`.

| Comparison dimension | Matched trend vs breakout | Native trend vs breakout | Generic random vs breakout | SPY vs breakout |
|---|---|---|---|---|
| PIT universe / data coverage | `IDENTICAL` | `IDENTICAL` | `IDENTICAL` | `NOT_DIRECTLY_COMPARABLE` |
| Research period / initial capital | `IDENTICAL` | `IDENTICAL` | `IDENTICAL` | `MATCHED_BY_DESIGN` / `NOT_DIRECTLY_COMPARABLE` |
| Position count / size / cash | `IDENTICAL` | `IDENTICAL` | `IDENTICAL` | `NOT_DIRECTLY_COMPARABLE` |
| Signal and candidate arrivals | `MATCHED_BY_DESIGN` | `MEASURED_DIFFERENCE` | `MATCHED_BY_DESIGN` | `NOT_DIRECTLY_COMPARABLE` |
| Entry / hold / exit / slippage | `IDENTICAL` | `IDENTICAL` | `IDENTICAL` | `NOT_DIRECTLY_COMPARABLE` |
| Lifecycle treatment | `IDENTICAL` | `IDENTICAL` | `IDENTICAL` | `NOT_DIRECTLY_COMPARABLE` |
| Candidate ranking | `MEASURED_DIFFERENCE` | `MEASURED_DIFFERENCE` | `MEASURED_DIFFERENCE` | `NOT_DIRECTLY_COMPARABLE` |
| Average exposure | `MATCHED_BY_DESIGN` | `MEASURED_DIFFERENCE` | `MATCHED_BY_DESIGN` | `NOT_DIRECTLY_COMPARABLE` |
| Market beta | `MEASURED_DIFFERENCE` | `MEASURED_DIFFERENCE` | `MEASURED_DIFFERENCE` | `NOT_DIRECTLY_COMPARABLE` |

Only the opportunity-matched trend comparison is the primary fairness test. SPY is context, not a mechanically matched portfolio control.

## 14. Exposure-comparability gate

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

Exposure eligibility is determined without reference to control returns.

A randomized seed is valid for the primary distribution only if all of these conditions hold:

1. its mean invested exposure is within ±2.0 percentage points of the frozen PIT portfolio mean exposure of 89.3999%;
2. its accepted-position count is within ±5% of the frozen PIT portfolio's 602 accepted positions;
3. its mean absolute daily exposure difference from the frozen PIT portfolio is no more than 5.0 percentage points;
4. it passes all engine, identity, lifecycle, and determinism invariants.

At least 800 of the 1,000 registered matched-trend seeds must pass. Otherwise, the primary matched-control design is invalid and the outcome is `REVIEW`; thresholds must not be altered after returns are observed. Invalid seeds and exact exclusion reasons remain in the artifact.

The generic random-entry control uses the same exposure gate. The native trend control is reported with its observed exposure difference and is not forced through opportunity matching.

## 15. Primary endpoint and statistical test

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

### 15.1 Economic endpoint

The primary economic endpoint is:

`frozen PIT CAGR − median valid matched-trend CAGR`

The pre-registered economic-materiality threshold is +2.00 percentage points per year.

### 15.2 Randomization percentile

The frozen PIT CAGR percentile within the complete valid matched-trend seed distribution is reported using the registered empirical distribution. A percentile at or above 95 is required for `GO`.

This percentile is an empirical randomization rank. It must not be described as a conventional independent-sample p-value because all paths share the same historical market realization.

### 15.3 Date-clustered uncertainty

The primary uncertainty calculation uses a paired stationary block bootstrap across the common XNYS date vector. Each bootstrap replicate resamples the same date blocks for the frozen portfolio and every valid matched control, recomputes geometric growth, and then calculates frozen annualized growth minus the median control annualized growth.

The primary expected block length is 20 sessions. Fixed block-length sensitivity checks at 10 and 40 sessions are secondary and cannot replace the primary result. The two-sided 95% interval must have a lower bound above zero for `GO`.

This choice follows the dependence-preserving motivation of Politis and Romano's [stationary bootstrap](https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870). It does not eliminate model-selection risk.

### 15.4 Multiple testing boundary

Only the matched-trend endpoint is primary. Native trend, generic random entry, cost grid, start-date paths, tie handling, beta, and SPY comparisons are secondary safeguards. No secondary result may be promoted to primary after results are known.

The protocol addresses data-snooping concerns in the spirit of White's [Reality Check](https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152) and the Probability of Backtest Overfitting framework described by Bailey et al., [“The Probability of Backtest Overfitting”](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253). It does not claim to implement either paper's complete procedure.

## 16. Beta and benchmark safeguards

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The primary result remains the matched-control test, not a market-model alpha.

As a secondary safeguard, regress daily portfolio excess returns on same-day SPY total returns over the full common 2021-09-27 through 2026-09-22 daily window and report intercept, beta, and a Newey-West/HAC 95% interval with lag 20. Returns are close-to-close and aligned to the same XNYS session. Cash earns the frozen zero return. A date missing from either portfolio or benchmark is not imputed: the run fails its data-alignment invariant and the missing date is reported. No rolling beta window or result-dependent window selection is allowed. For `GO`, the annualized alpha point estimate must be positive and the lower confidence bound must not be below −2.00 percentage points per year. Failure of this safeguard produces `REVIEW`, not automatic proof of no signal.

The risk-free rate is zero for the primary continuity calculation because that matches the frozen baseline. A point-in-time three-month Treasury-bill series may be added only as a pre-approved secondary sensitivity with its own source, vintage, and availability audit.

### SPY total-return limitation

**Decision status: BLOCKED**

The currently persisted SPY benchmark is split-adjusted price only and excludes dividends. Existing provider documentation indicates that an adjusted-close field may include dividends retrospectively, which is unsuitable for causal signal formation and has not been validated here as a point-in-time total-return series.

A dividend-aware SPY context requires a separately validated series with ex-date, amount, correction, and availability provenance. Until that exists, the existing SPY price-return series must be labeled `PRICE_RETURN_ONLY`; a total-return comparison must not be fabricated. Acquiring or constructing the dividend-aware series requires human approval and must occur without changing the primary portfolio experiment.

## 17. Cost robustness

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The frozen 5-basis-point per-side assumption is primary. The pre-registered secondary grid is:

- 5 bps per side;
- 10 bps per side;
- 20 bps per side.

Only transaction-cost arithmetic changes. Candidate selection, ordering, entry prices before cost, holding period, exits, and all portfolio constraints remain fixed. Cost sensitivity is reported for the breakout and matched controls using the same seed registry.

`GO` requires the primary matched-control advantage to remain positive at 10 bps. A negative advantage at 10 bps is `REVIEW`; a non-positive advantage already at the frozen 5-bps assumption is `NO-GO` unless caused by a protocol-invalid run.

## 18. Start-date and path robustness

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The path analysis uses quarterly start points: the original 2021-09-27 start and the first XNYS session of each January, April, July, and October thereafter. A start point is eligible only if at least 504 XNYS sessions remain through the frozen 2026-09-22 end date.

These windows overlap and are descriptive robustness checks, not independent samples.

For each eligible start, compare the frozen breakout path with the same-seed matched-trend distribution from that start onward. All windows have a fixed 2026-09-22 end and therefore overlap. Report:

- breakout-minus-median matched CAGR;
- the matched-control percentile;
- exposure difference;
- accepted-position count;
- terminal-event and capacity diagnostics;
- median, interquartile range, minimum, maximum, and 10th/90th percentiles of start-specific CAGR differences.

Path gate:

- `GO`: breakout is at or above the matched median in at least 70% of eligible starts and the 25th percentile of start-specific CAGR differences is above −2.00 percentage points;
- `REVIEW`: the success share is 50%–70%, or the 25th percentile is between −5.00 and −2.00 percentage points;
- `NO-GO`: success share is below 50% with a non-positive median difference, or the 25th percentile is below −5.00 percentage points.

## 19. Score ties and ordering robustness

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

The primary breakout ordering remains the frozen score followed by stable `security_id`. No “near-tie” tolerance is introduced because that would create a new parameter after observing the score distribution.

A secondary exact-tie test permutes only candidates whose stored scores are exactly equal at the persisted precision. It uses a dedicated registered random stream and leaves all non-tied rankings unchanged.

Control portfolios use their registered random permutations; they must never reuse breakout score ordering.

If exact-tie permutations materially change the sign of the primary economic endpoint, the decision is at most `REVIEW`.

## 20. Concentration safeguards

**Decision status: PROPOSED AFTER OBSERVING PHASE 3 CONCENTRATION — REQUIRES HUMAN APPROVAL**

The known Phase 3 attribution showed material concentration, so these thresholds are not independent of prior evidence and must be disclosed as such.

Report top-1, top-5, top-10, bottom-1, bottom-5, and bottom-10 contribution shares; issuer, sector, entry-date, exit-date, and terminal-event concentrations; and the contribution distribution across accepted positions.

Decision bands:

- `GO`: top-10 contribution share is no more than 60% and no single position contributes more than 25% of total net profit;
- `REVIEW`: top-10 share is above 60% but no more than 80%, or top-1 is above 25% but no more than 50%;
- `NO-GO`: top-10 share exceeds 80%, top-1 exceeds 50%, or a single unresolved lifecycle treatment determines the sign of the result.

Leave-one-out contributor diagnostics are explanatory only. They must not be used to delete trades or redefine the portfolio.

## 21. Minimum-detectable-effect and power scenarios

**Decision status: PROPOSED / HYPOTHETICAL — REQUIRES HUMAN APPROVAL**

With 1,252 common sessions, a rough two-sided 5% significance, 80% power approximation for annualized mean differential is:

`MDE ≈ 2.80 × daily differential volatility × 252 / sqrt(effective independent sessions)`

| Daily differential volatility | Effective N = 1,252 | Effective N = 626 | Effective N = 313 |
|---:|---:|---:|---:|
| 0.25% | 4.99 pp/year | 7.05 pp/year | 9.97 pp/year |
| 0.50% | 9.97 pp/year | 14.10 pp/year | 19.95 pp/year |
| 1.00% | 19.95 pp/year | 28.20 pp/year | 39.90 pp/year |

These are scenario calculations, not measurements from a new performance run. Dependence reduces effective sample size; common-market pairing may reduce differential volatility. One thousand seeds improve characterization of the control randomization distribution but do not create one thousand independent market histories.

The +2.00-percentage-point economic threshold may therefore be statistically underpowered over a single five-year realization. A statistically inconclusive result must not be converted into evidence of equivalence.

## 22. Historical out-of-sample extension

**Decision status: BLOCKED**

The proposed historical extension would cover 2015-01-01 through 2021-09-24. It is currently classified:

`HISTORICAL_OOS_BLOCKED`

Reasons:

- earlier EODHD work showed missing-not-at-random identities and terminal events in the older period;
- all 79 previously critical cases exited before the current 2021-09-27 window, so their non-relevance to the current window does not resolve them for the extension;
- Massive was only partially sufficient as a second source: unresolved identities, ticker reuses, and low-confidence terminal events remained, with endpoint-entitlement limitations;
- the repository does not prove that the proposed 2015–2021 period was unavailable when parameters were chosen.

Therefore, the extension cannot be described as clean out-of-sample evidence. It may proceed only after identity-native membership, prices, corporate actions, and terminal treatments meet the same strict PIT standards for every relevant security, and after human approval of its temporal classification. No synthetic membership or silent terminal-value repair is allowed.

## 23. Prospective holdout and signal-registration protocol

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

### 23.1 Exposure classification

The prospective period is classified:

`EXPOSURE_UNKNOWN`

No post-2026-09-22 market outcome was inspected while drafting this protocol. Repository evidence alone cannot prove that no human or external system has viewed post-boundary outcomes. The historical holdout cannot be declared pristine.

### 23.2 Boundary and earliest valid registration

`HOLDOUT_RESERVED_START = 2026-09-23`

Registration cannot be backdated. The earliest feasible live signal-registration session is 2026-10-09, conditional on explicit protocol approval and completion of the append-only infrastructure before that session's data cutoff. If that condition is not met, registration starts on the next completed XNYS session after activation.

### 23.3 Required daily record

For every scheduled XNYS session, the system must preserve an immutable record containing at least:

- session date and exchange-calendar version;
- generation timestamp and trusted-clock source;
- code commit, container image digest, dependency lock hash, and configuration hash;
- PIT-universe artifact hash and complete identity/provenance manifest;
- input-provider identifiers, as-of timestamps, file hashes, and correction versions;
- every evaluated security, historical ticker, `security_id`, membership interval, and eligibility decision;
- raw causal feature values, strategy classification, score, rank, and exclusion reason;
- proposed next-open order, size, capacity status, and lifecycle state;
- missing or late data status;
- previous-record digest and current canonical-record digest;
- supersession link for any later correction.

The ledger must record all decisions, including “no signal,” unavailable input, and failed run states. It must not contain API keys or provider credentials.

### 23.4 Append-only and tamper evidence

The implementation must use immutable/WORM-capable object storage or an equivalently access-controlled append-only store. Canonical JSON records are hash chained. Daily manifests are sealed with a managed signing key, independently timestamped, and copied to a separately administered location.

Production write access and later research-read access should be separated. Corrections create new linked records; they never overwrite the original. Provider restatements must preserve both the originally available version and the corrected version.

### 23.5 Timing and data availability

Signals use only data available after the relevant session close and before the registered calculation cutoff. Proposed orders target the next session open. A late provider file produces a registered late/missing status; it does not authorize retroactive signals. Holidays and unexpected closures are resolved using the frozen exchange-calendar version and recorded in the manifest.

### 23.6 Sealing and unsealing

No prospective P&L, equity curve, CAGR, Sharpe, drawdown, hit rate, or outcome-conditioned diagnostic may be calculated or viewed before unsealing.

Proposed unseal date: 2031-10-15 or later, and only after at least 1,250 registered XNYS sessions plus a 20-session outcome-maturation buffer, whichever condition is later. The unseal condition and authorized reviewers must be approved before registration begins.

No scheduler is activated by this document. Infrastructure implementation, security review, operational ownership, provider licensing, cost, and activation all require separate human approval.

Signal registration, execution simulation, and outcome evaluation are separate stages. Registration records the frozen ex-ante decision. Execution simulation may occur only under a separately approved, frozen implementation and must remain sealed. Outcome evaluation occurs only at the approved unseal condition. Registration alone is not a paper trade and does not authorize either later stage.

## 24. GO / REVIEW / NO-GO decision policy

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

### 24.1 Preconditions

Any integrity, identity, PIT, lifecycle, determinism, arithmetic, manifest, or exposure-eligibility failure invalidates the experiment. It produces `REVIEW/BLOCKED`, not a financial conclusion.

### 24.2 GO

All of the following are required:

1. primary CAGR advantage versus the matched-control median is at least +2.00 percentage points per year;
2. frozen breakout CAGR is at or above the 95th percentile of the valid matched-control distribution;
3. paired stationary-bootstrap 95% lower bound is above zero;
4. at least 800 matched seeds pass the pre-registered exposure gate;
5. beta safeguard passes;
6. advantage remains positive at 10-bps cost;
7. start-date path gate passes `GO`;
8. concentration gate passes `GO`;
9. exact-tie sensitivity does not reverse the primary conclusion;
10. all outputs are deterministic and independently auditable.

### 24.3 REVIEW

`REVIEW` applies when execution is valid but one or more safeguards are inconclusive, statistical power is inadequate, the result is economically positive but below threshold, a secondary robustness gate falls in its review band, or a data/provenance dependency remains unresolved.

`REVIEW` does not authorize parameter tuning. The next action must be selected from the pre-approved options: continue sealed prospective collection, resolve source/provenance defects without viewing outcomes, or terminate the claim as inconclusive.

### 24.4 NO-GO

`NO-GO` applies when the valid primary result is non-positive, the result fails the stated economic/statistical requirements without an integrity defect, it fails an explicit no-go concentration/path/cost rule, or the prospective validation later fails its frozen decision criteria.

`NO-GO` does not authorize searching for new thresholds on the same data.

### 24.5 Review expiry

If historical-source remediation is selected, a go/no-go decision on acquiring the necessary licensed evidence should be made by 2027-04-01. If it is not acquired, the historical extension is abandoned.

Any unresolved research claim expires at the proposed prospective unseal date, 2031-10-15 or the later session-count/maturation date. At that point the frozen prospective evaluation yields `GO`, `NO-GO`, or `INCONCLUSIVE—RESEARCH CLAIM TERMINATED`; repeated unregistered testing is not allowed.

Decision precedence is: (1) an integrity or frozen-baseline mismatch blocks the run without a financial conclusion; (2) a valid explicit `NO-GO` condition overrides otherwise favorable secondary evidence; (3) every `GO` condition must pass for `GO`; and (4) all remaining valid but inconclusive combinations are `REVIEW`. Lack of power is lack of evidence, not evidence of no advantage.

### 24.6 Engineering feasibility

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

Reusable components already present include the identity-native PIT universe, alias resolution, daily-bar access, frozen signal and feature generation, portfolio engine, cash/position accounting, lifecycle treatment, calendar, and deterministic diagnostics.

Missing components include:

- an immutable Phase 4 experiment-manifest schema and validator;
- a seed registry and independent deterministic random streams;
- matched-trend, native-trend, and generic-random candidate generators;
- an exposure-gate evaluator and exclusion ledger;
- stationary-block bootstrap support;
- benchmark alignment and beta/HAC analysis;
- cost, start-date, tie, and concentration diagnostic orchestration;
- a validated dividend-aware SPY context series;
- an append-only prospective-registration store, hash chain, signing, trusted timestamping, corrections, access controls, monitoring, and disaster recovery;
- a holdout access policy that technically prevents performance evaluation before unsealing.

No existing scheduler or append-only signal-registration service was found. Prospective registration is time-sensitive, but implementation and activation require separate, narrowly scoped approval.

### 24.7 Phase 4B implementation sequence

**Decision status: PROPOSED — REQUIRES HUMAN APPROVAL**

1. Record human approval of every open decision without inspecting new outcomes.
2. Implement and test the experiment manifest, seed registry, and post-boundary data guard.
3. Implement candidate generators and reproduce the Phase 4A candidate census exactly.
4. Implement exposure matching and validate it using counts and exposure only, before performance results are exposed.
5. Implement control orchestration, bootstrap, beta, and secondary diagnostic modules with synthetic fixtures and mocks.
6. Seal the manifest and independent audit digest.
7. Run one complete Phase 4B experiment without interactively inspecting partial results.
8. Repeat from the same manifest to prove deterministic outputs.
9. Perform an independent integrity audit before interpreting any financial result.
10. Separately implement and security-review prospective signal registration; activate only after approval and never backdate records.

### 24.8 Limitations

**Decision status: FROZEN**

- The historical window is reused in-sample evidence with unknown parameter provenance.
- Randomized controls share one realized market history and are not independent market samples.
- Exposure matching cannot guarantee equal beta, sector mix, turnover, or latent risk.
- CAGR is path dependent; bootstrap inference depends on the resampling model.
- Five years may be underpowered for a +2-percentage-point annual advantage.
- The current SPY series excludes dividends and cannot be called total return.
- Older PIT data remain incomplete and cannot provide clean independent validation.
- Known concentration makes some robustness thresholds non-independent of prior evidence.
- Prospective observations since 2026-09-23 cannot be proven unseen from repository evidence alone.
- A future prospective result can still be affected by market-regime specificity and execution-model error.
- No backtest establishes investment suitability or guarantees future performance.

## 25. Approval checklist and execution prohibition

**Decision status: REQUIRES HUMAN APPROVAL**

Before Phase 4B, the human reviewer must explicitly approve or reject each of the following:

- the `IN_SAMPLE_REUSED / PROVENANCE_UNKNOWN` classification;
- all parameter-provenance classifications;
- opportunity-matched simple-trend definition;
- native-trend and generic-random secondary controls;
- 1,000-seed registry and deterministic seed derivation;
- exposure-comparability thresholds and minimum 800 valid seeds;
- +2.00-percentage-point economic threshold;
- 95th-percentile randomization requirement;
- stationary-bootstrap method and 20-session expected block length;
- beta safeguard and risk-free-rate treatment;
- SPY total-return data requirement and current block;
- 5/10/20-bps cost grid;
- quarterly start-date rules;
- exact-tie sensitivity;
- concentration thresholds, with acknowledgment that they follow known Phase 3 concentration;
- power-scenario interpretation;
- `HISTORICAL_OOS_BLOCKED` decision;
- prospective exposure classification and non-backdating rule;
- append-only signal-registration specification;
- earliest feasible activation date;
- proposed unseal date and minimum observation/maturation requirements;
- GO/REVIEW/NO-GO rules and review expiry.

Until that approval is recorded, the only authorized status is:

`PHASE_4A_DESIGN_READY_FOR_REVIEW`

No Phase 4B financial calculation, random portfolio generation, scheduler activation, data acquisition, database migration, commit, tag, or push is authorized by this document.
