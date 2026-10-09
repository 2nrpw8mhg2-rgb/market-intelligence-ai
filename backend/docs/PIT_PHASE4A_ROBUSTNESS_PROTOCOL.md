# Phase 4A — Pre-Registered Controls, Prospective Holdout & Robustness Protocol

## 1. Document status and scope

**Decision status: METHODOLOGY APPROVED — PHASE 4B PREFLIGHT PENDING**

This document is the approved Phase 4A methodological protocol. It is a design
artifact, not approval to execute Phase 4B. Freezing it did not run a financial
backtest, generate a randomized portfolio return, ingest market data, inspect
holdout performance, activate the prospective registry, or change production
state.

Primary research question:

> Conditional on the entry opportunities actually accepted by the frozen PIT
> breakout portfolio, does its security selection outperform uniform random
> selection from a contemporaneously eligible PIT-valid trend universe?

The primary experiment evaluates **security selection conditional on the
observed accepted-entry schedule**. It does not independently establish that
the breakout signal-arrival process creates value. The historical evidence
remains `IN_SAMPLE_REUSED / PROVENANCE_UNKNOWN`.

The explicit methodological decisions in this document are frozen. Phase 4B is
still prohibited until both independent technical preflights pass and a separate
execution authorization is given.

## 2. Recovery point and frozen baseline

**Decision status: FROZEN**

The amendment starts from this verified recovery point:

| Item | Frozen value |
|---|---|
| Branch | `main` |
| Commit and `origin/main` | `f86bb6edc8ca514105ff028167f403a4ac0cd4c8` |
| Tag | `v0.9.4-prospective-registry-inactive` |
| Alembic repository head | `20261001_0010` |
| Published baseline tree | clean before Phase 4A documentation amendments |
| Research window | 2021-09-27 through 2026-09-22 |
| Calendar | XNYS, 1,252 sessions |
| Universe | identity-native S&P 500 point-in-time universe |
| Strategy | `BREAKOUT_20D_VOLUME` |
| Entry / hold | next-session open / 20 sessions |
| Size / capacity | 10% of equity / 10 positions |
| Costs | 5 basis points adverse slippage per side |
| Initial / final equity | USD 100,000 / USD 243,797.07 |
| CAGR / annualized volatility | 19.571826% / 18.3534% |
| Maximum drawdown / Sharpe | -21.0174% / 1.070165 |
| Average invested exposure | 89.3999% |
| Accepted entries / closed trades | 602 / 593 |
| Frozen PIT digest | `5c6a0e5edf2d51f56ba2f456f978aadd8dcf550061a15cb970da90fbc2026792` |

The ignored Phase 3B diagnostic artifact confirms `ACCEPTED = 602`, 593 closed
trades, nine positions open at the research boundary, and the frozen digest.
The engine groups candidates by execution date and can execute more than one
entry at the same open, in deterministic candidate order, subject to slots,
duplicate holdings, prices, and cash.

The published summary does **not** itself preserve the complete 602-row entry
ledger. Therefore Phase 4B must first materialize, from the unchanged frozen
result, a canonical ledger with one row per accepted entry and prove that its
digest and aggregate values reproduce the frozen artifact. This is a mandatory
technical preflight, not permission to reconstruct or optimize the schedule.
If the ledger cannot unambiguously establish every decision session, intended
execution session, same-date multiplicity, frozen ordinal, and identity, the
experiment is `INVALID / BLOCKED` before financial calculation.

No frozen Phase 2 or Phase 3 result may be altered by this protocol.

## 3. Historical interpretation and parameter provenance

**Decision status: FROZEN**

The research window was repeatedly inspected during Phases 1–3 and is not an
independent out-of-sample test. Repository history does not establish when or
how the human researcher selected the exact parameters. A positive Phase 4B
result must not be described as proven alpha or prospective validation.

The earliest repository evidence for scanner thresholds and score construction
is commit `00db8d9050fcd8ce1d8a0cd13a0fbd317ce16c57` (2026-09-24).
The earliest repository evidence for the portfolio defaults is commit
`6483f521465e68c3657e2f163b88474cb0caaea9` (2026-09-24). Both are after the
research window.

| Parameter | Frozen value | Classification |
|---|---:|---|
| Breakout lookback | 20 sessions | `PROVENANCE_UNKNOWN` |
| Relative-volume threshold | 1.5x | `PROVENANCE_UNKNOWN` |
| Trend averages | SMA 50 / SMA 200 | `PROVENANCE_UNKNOWN` |
| Prior ADV / minimum price | USD 10 million / USD 5 | `PROVENANCE_UNKNOWN` |
| Score weights | 30/25/20/15/10 | `PROVENANCE_UNKNOWN` |
| Holding / size / capacity | 20 / 10% / 10 | `PROVENANCE_UNKNOWN` |
| Slippage | 5 bps per side | `PROVENANCE_UNKNOWN` |

Generic literature support for moving-average and trading-range-break rules does
not establish independent provenance for these exact choices. No Phase 4 work
may tune them.

## 4. Frozen treatment and accepted-entry schedule

**Decision status: FROZEN, SUBJECT TO LEDGER PREFLIGHT**

The treatment is the exact published PIT portfolio. The conditional-control
schedule uses only its 602 **accepted** entries. It excludes all generated but
rejected signals and all non-executable signals.

The canonical schedule must preserve for every row:

- stable `security_id`, decision session, intended execution session, and the
  frozen same-session execution ordinal;
- number of accepted entries for that execution session;
- next-open timing, 10% sizing rule, cash and capacity semantics;
- 20-session holding convention and applicable lifecycle policy;
- source run ID, configuration hash, frozen digest, and row/manifest digests.

Rows are ordered by execution session, then by their original frozen engine
ordinal. The ordinal is evidence from the frozen ledger; it must not be inferred
from a new ranking. The control receives one scheduled ticket for each row. It
does not receive the breakout security identity or score as a selection input.

## 5. Contemporaneous eligible trend pool

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

For scheduled row `j` with decision session `t`, a security enters the pool only
if, using information available by the close of `t`:

1. its `security_id` is an eligible identity-native PIT constituent on `t`;
2. `close_t > SMA50_t > SMA200_t`;
3. `close_t >= USD 5`;
4. prior average dollar volume is at least USD 10 million;
5. the historically correct market-data identity and required causal bars are
   available and pass frozen data-integrity rules; and
6. it is not already held by that control portfolio at the decision/execution
   point under the engine's duplicate-position rule.

Membership and identity use `security_id`, never a modern ticker string. Future
membership, future aliases, future prices, and future knowledge of a lifecycle
event may not determine eligibility. Lifecycle evidence is used later only by
the frozen exit policy when the event becomes applicable. Breakout candidates
remain in the pool whenever they satisfy the same trend eligibility.

Exact processing for each `(decision session, execution session)` batch:

1. construct the causal PIT/trend/data-valid pool;
2. remove `security_id` values already held by the simulated control;
3. sort the remaining unique identities lexicographically by `security_id`;
4. generate one registered random permutation;
5. take the first `k` identities without replacement, where `k` is the number
   of scheduled frozen tickets in that batch;
6. map selected identities in permutation order to tickets in frozen ordinal
   order; and
7. submit those tickets once to the unchanged portfolio engine.

Duplicate-held exclusion is ordinary causal candidate filtering. It is not a
failed draw or a reason to reject/retry a seed. Within-batch selection is without
replacement. Exact duplicate `security_id` rows in the candidate pool are an
integrity failure, not a tie.

## 6. Insufficient pools and scarcity reporting

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

If the filtered pool contains `m < k` identities, select all `m` in registered
permutation order. Do not invent replacements, relax eligibility, reuse a held
security, borrow from another date, or silently omit the incident. Record:

- `INSUFFICIENT_POOL`;
- decision and execution dates;
- scheduled `k`, eligible `m`, and shortfall `k-m`;
- pool manifest digest and selected identities;
- seed/control identifiers and downstream unfilled ticket IDs.

The affected simulation continues deterministically so its full path remains
auditable. Legitimate scarcity caused by that seed's randomized portfolio-state
evolution does **not** invalidate or exclude the seed. If its technical, PIT,
identity, accounting, lifecycle, and reproducibility invariants pass, the seed
remains in the primary distribution with the remaining scheduled tickets
unfilled. It is never replaced by another seed.

Phase 4B must distinguish scarcity from missing or corrupt causal market data,
an unresolved `security_id`, and an implementation/invariant failure. Those are
data or technical invalidities; a small valid pool after excluding held
securities is an economic consequence of the randomized path.

The report must show:

- total frozen scheduled tickets: **602**;
- scarcity-unfilled tickets for every seed and
  `scarcity_rate_s = scarcity_unfilled_tickets_s / 602`;
- mean, median, 95th percentile, maximum, and proportion nonzero across all
  1,000 attempted seeds;
- scarcity by execution session and calendar period;
- separate counts for scarcity, cash, capacity, missing execution price, and
  every other engine reason; and
- resulting cash and exposure differences as descriptive diagnostics.

For the `M` invariant-valid registered controls, define the single primary
scarcity statistic:

`mean_scarcity_rate = (1/M) * sum_s(scarcity_rate_s)`

The approved comparability rule is:

- if `mean_scarcity_rate > 0.01`, scarcity caps the overall classification at
  `REVIEW`;
- if `mean_scarcity_rate <= 0.01`, scarcity does not independently restrict
  `GO`; exactly 1% therefore does not trigger the cap;
- scarcity never independently produces financial no-go and never changes a
  valid primary no-go into REVIEW; and
- fewer than 800 invariant-valid controls remains `INVALID / BLOCKED`.

Scarcity can create asymmetric exposure between breakout and randomized
controls and therefore affect economic interpretation even when every seed is
valid. The approved 1% threshold is a comparability safeguard, not an estimate
of financial return bias caused by scarcity.

## 7. Exits, sizing, cash, capacity, and exposure

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

Controls use the unchanged engine. Nominal exits occur after 20 sessions, with
the frozen exceptions for acquisitions, mergers, delistings, bankruptcies, and
other approved lifecycle treatments. A legitimate early exit releases its slot
according to the engine's next-session release convention. It does **not** create
an extra entry outside the frozen schedule.

At an intended open, target notional is 10% of prior-close portfolio equity,
subject to available cash, maximum exposure, and the ten-position cap. Different
returns legitimately create different future equity and cash. The engine's
actual partial allocation or unfilled behavior is preserved. An entry blocked
by cash, capacity, a missing open, or another frozen constraint is recorded once;
there is no leverage, added cash, substitute security, or resampling.

The construction matches **entry opportunities**, not guaranteed realized
positions. Report per seed:

- accepted, partial, and unfilled scheduled entries by reason;
- early lifecycle exits and slot-release dates;
- mean exposure, daily exposure difference, position counts, cash utilization,
  and capacity utilization;
- pool insufficiencies and identity/data-integrity incidents.

No seed may be rejected because of realized average exposure, daily exposure
differences, position counts, cash, returns, terminal equity, or CAGR. These are
economic outcomes/diagnostics. Legitimate engine behavior is not a simulation
failure.

## 8. Randomization, attempted-seed registry, and validity

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

Exactly 1,000 seed indices, `0..999`, are attempted. Before returns are exposed,
seal a canonical **base manifest** containing the checkpoint,
code/container/dependency digests, NumPy version, input hashes, PIT hash,
canonical 602-row schedule hash, definitions, registered stream identifiers,
decision thresholds, and canonicalization version. The base manifest excludes
derived seeds, downstream/generated hashes, randomized selections, and all
randomized outputs, eliminating a hash/seed circular dependency.

- PRNG: NumPy `Generator(PCG64DXSM)`, with the exact NumPy version/container
  pinned in the manifest.
- Canonical serialization: RFC 8785 JSON Canonicalization Scheme, encoded as
  UTF-8 without BOM or trailing newline. Object keys follow RFC 8785 ordering;
  arrays retain protocol order. The SHA-256 of those exact bytes is
  `base_manifest_hash`.
- Seed material for index `i` is the byte concatenation of the ASCII domain tag
  `MIA-PHASE4A-SEED-v1`, one NUL byte, the raw 32-byte base-manifest digest,
  `uint32_be(len(control_id_utf8))`, the UTF-8 `control_id`,
  `uint32_be(len(stream_id_utf8))`, the UTF-8 `stream_id`, and `uint64_be(i)`.
  The seed is the unsigned big-endian integer represented by the first 16 bytes
  of `SHA-256(seed_material)`.
- Candidate ordering: unique, lexicographically sorted stable `security_id`.
- Draw: one PRNG permutation per scheduled batch; take without replacement in
  frozen ticket order.
- Ties: `security_id` ordering only prepares the population; selection priority
  comes exclusively from the registered permutation.
- Streams: distinct identifiers for conditional controls, secondary controls,
  exact-tie sensitivity, and bootstrap. Streams are never reused.

After derivation, the complete seed registry is stored beside the immutable base
manifest and its own digest is recorded downstream; it does not alter the base
manifest hash. A clean implementation must reproduce the base hash, every seed,
selection, and output digest byte-for-byte. Every attempt produces an immutable
audit row. There are no performance-based retries or replacement seeds.

A seed is `PRIMARY_VALID` only if all required inputs and the exact schedule are
available, PIT/identity rules pass, the engine and accounting invariants pass,
no look-ahead is detected, and exact rerun hashes match. A technical crash,
corrupt/missing causal input, unresolved identity, invariant failure, or
nondeterminism makes the attempt invalid. `INSUFFICIENT_POOL` caused by
legitimate path-dependent scarcity does not. Every invariant-valid registered
seed enters the primary control distribution. Legitimate differences in cash,
capacity, exposure, lifecycle exits, accepted positions, scarcity, or
performance do not permit exclusion.

At least 800 of the 1,000 attempts must be invariant-valid to characterize the
registered distribution. Fewer than 800 is `INVALID / BLOCKED`; seeds are not
replaced and the threshold is not relaxed.

## 9. Primary randomization endpoint

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

For the predeclared `PRIMARY_VALID` controls:

`Delta_CAGR = CAGR_breakout - median_s(CAGR_control,s)`

Also report the frozen breakout CAGR's empirical percentile rank in the control
CAGR distribution. For every control-relative diagnostic in this protocol,
sort defined control values ascending, define P95 by nearest rank
`ceil(0.95*M_defined)`, and define the breakout inclusive empirical percentile
as `100 * count(control_value <= breakout_value) / M_defined`; ties therefore
receive the same upper inclusive rank and are also reported separately. The
economic materiality threshold is an absolute
**+2.00 percentage-point annual CAGR difference**.

The distribution conditions on one observed historical market path. Its
dispersion primarily reflects randomized security selection, not independent
market histories. Its percentile is not automatically a conventional sampling
p-value. CAGR differences are not log-growth differences, and the historical
window remains reused in-sample evidence.

## 10. Primary time-series inference estimand

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

Let `r_B,t` be the frozen breakout daily simple return and `r_C,s,t` the daily
simple return for invariant-valid control seed `s`, on the identical XNYS date
vector. Let `M` be the number of those controls. Define the required arithmetic
diagnostic:

`d_t = r_B,t - mean_s(r_C,s,t)`

The frozen primary inferential statistic is:

`g_t = log(1 + r_B,t) - (1/M) * sum_i(log(1 + r_C,i,t))`

`theta_log = 252 * (1/T) * sum_t(g_t)`

`theta_log` compares breakout annualized log growth with the average annualized
log growth of the individual randomized control paths. It is not equivalent to
the arithmetic CAGR gap in Section 9.

The alternatives are not interchangeable:

- A, the primary comparator, is
  `mean_i(log(1 + r_C,i,t))`, the mean individual control log return;
- B is `log(1 + mean_i(r_C,i,t))`, the log return of a hypothetical
  equal-weighted ensemble rebalanced across control paths every day without
  extra cost; and
- the CAGR of equal initial capital left in each control without daily
  rebalancing is a third construction with changing weights.

Because `log` is concave, Jensen's inequality gives
`log(1 + mean_i(r_C,i,t)) >= mean_i(log(1 + r_C,i,t))` whenever every return is
valid. B may be reported separately as a descriptive construction but cannot
replace A or the primary endpoint. All daily returns must exceed `-1`;
missing/nonfinite returns or calendar misalignment invalidate inference. The
arithmetic `d_t` series is descriptive only.

## 11. Paired stationary-block bootstrap

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

Use 10,000 registered bootstrap replicates of the already formed, aligned `g_t`
series. A stationary bootstrap replicate starts each block at a uniformly drawn
date index and continues with probability `19/20`; with probability `1/20` it
starts a new uniformly drawn block. Indices wrap around and are appended until
exactly `T` observations are obtained. Thus expected block length is 20
sessions. A dedicated manifest-derived PRNG stream is mandatory.

For each replicate compute `252 * mean(g_t*)`. Report the 2.5th and 97.5th
empirical percentiles as the two-sided 95% interval. Fixed expected-length
sensitivities of 10 and 40 sessions are secondary and cannot replace the
20-session result.

This paired procedure addresses uncertainty across possible market histories
only under the stationarity/dependence assumptions and preserves some serial
dependence. It does not reconstruct portfolio cash paths, overlapping positions,
or security-level decisions; it is not an exact interval for the original CAGR
gap; it treats the registered set of individual control paths as fixed after
construction; and it does not repair prior strategy selection, multiple
historical inspection, or data snooping.

## 12. Economic thresholds and units

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

Two distinct thresholds are frozen:

1. descriptive randomization materiality: `Delta_CAGR >= 0.0200`, an absolute
   +2.00 percentage-point arithmetic CAGR gap; and
2. inferential log-growth materiality: `m_log = log(1.02) = 0.0198026273` per
   year, meaning a 2% multiplicative annual growth advantage over the average
   individual-control log-growth comparator.

These are intentionally not asserted to be mathematically identical. Their
similar numerical size does not authorize substituting one for the other. No
conversion based on an observed control return is permitted after results.

## 13. Complete decision policy

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

Precedence is strict:

1. Any mandatory integrity/comparability/data/inference failure produces
   `INVALID / BLOCKED`, with no financial conclusion.
2. For a valid experiment, evaluate `NO-GO_NEGATIVE`, then
   `NO-GO_IMMATERIAL`.
3. If neither primary no-go applies, `GO` requires every positive criterion and
   must not be capped by an approved REVIEW-only safeguard.
4. Every other valid combination is `REVIEW`.

Let `L` and `U` denote the lower and upper bounds of the primary two-sided 95%
bootstrap interval for `theta_log`, and let `m_log = log(1.02)`.

### GO

All must pass:

- valid primary conditional-control experiment with at least 800
  invariant-valid attempts;
- `Delta_CAGR >= +2.00` percentage points;
- breakout at or above the 95th control-CAGR percentile;
- primary 95% interval for `theta_log` has lower bound above zero;
- all PIT, identity, lifecycle, accounting, determinism, manifest, and data
  integrity gates;
- `mean_scarcity_rate <= 0.01`;
- breakout `C10` does not exceed control `C10` P95;
- `start_win_rate >= 0.50`;
- breakout beta does not exceed control beta P95;
- `SPY_TOTAL_RETURN_BENCHMARK_VERIFIED_AND_FROZEN`; and
- every mandatory technical preflight passes.

A `GO` remains robustness evidence on reused historical data, not proof of
prospective alpha.

### NO-GO_NEGATIVE

For an otherwise valid experiment, `NO-GO_NEGATIVE` applies when `U < 0`. Under
the specified bootstrap assumptions, the full interval supports negative
annualized relative log growth.

### NO-GO_IMMATERIAL

If `NO-GO_NEGATIVE` does not apply, `NO-GO_IMMATERIAL` applies when
`U < m_log`. The interval excludes the predeclared economically material annual
log-growth advantage even if a smaller positive advantage remains possible.
This is economic futility, not proof of negative relative returns.

### REVIEW

`REVIEW` covers all other valid outcomes, including intervals wide enough to
remain compatible with economically material positive performance but lacking
every required GO criterion. A positive point estimate does not force REVIEW
when `U < m_log`; that is `NO-GO_IMMATERIAL`. The response to insufficient
independent evidence is prospective validation, not repeated historical
threshold searches. A valid but underpowered result is `REVIEW`, not no-go,
unless its interval nevertheless excludes the materiality threshold.

### INVALID / BLOCKED

Broken PIT eligibility, ambiguous schedule, missing causal/benchmark data,
invalid controls, fewer than 800 invariant-valid seeds, failed comparability,
nondeterminism, invalid inference, or unresolved mandatory methodology makes
the experiment `INVALID / BLOCKED`. It must be repaired without inspecting
results and rerun only under a newly sealed, approved manifest.

### GO-cap precedence

Scarcity, relative C10, start-date robustness, and relative beta can cap an
otherwise eligible GO at REVIEW. They cannot convert `NO-GO_NEGATIVE` or
`NO-GO_IMMATERIAL` into REVIEW. If a primary no-go and one or more GO caps occur,
retain the primary no-go and report the secondary flags separately. No secondary
financial no-go category exists.

## 14. Assumption-based power analysis

**Decision status: APPROVED HYPOTHETICAL — DESCRIPTIVE ONLY**

Illustration only: assume independent annual relative log-growth observations,
normality, a two-sided 5% test, five years, no parameter-estimation cost, and
annual tracking error `sigma`. Then `SE = sigma/sqrt(5)`, the 95% half-width is
`1.96*SE`, approximate power at a true +2% annual advantage is
`P[Z > 1.96-0.02/SE] + P[Z < -1.96-0.02/SE]`, and the approximate 80%-power
minimum detectable effect is `(1.96+0.8416)*SE`.

| Annual tracking error | SE | 95% half-width | Power at true +2% | 80%-power MDE |
|---:|---:|---:|---:|---:|
| 6% | 2.683% | 5.259% | 11.6% | 7.518% |
| 8% | 3.578% | 7.012% | 8.6% | 10.023% |
| 10% | 4.472% | 8.765% | 7.3% | 12.529% |
| 12% | 5.367% | 10.518% | 6.6% | 15.035% |
| 14% | 6.261% | 12.272% | 6.2% | 17.541% |

Horizon sensitivity at 10% annual tracking error:

| Years | SE | 95% half-width | Power at true +2% | 80%-power MDE |
|---:|---:|---:|---:|---:|
| 3 | 5.774% | 11.316% | 6.4% | 16.175% |
| 5 | 4.472% | 8.765% | 7.3% | 12.529% |
| 10 | 3.162% | 6.198% | 9.7% | 8.860% |

Serial dependence would generally reduce effective information. Common-market
pairing may reduce tracking error, but no observed Phase 4 result was used here.
Requiring a confidence interval to exclude zero can demand an observed advantage
far larger than two percentage points. More randomized seeds characterize
selection variability; they do not create more independent market histories.

## 15. Cost and start-date robustness

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

The frozen 5-bps-per-side run is primary; 10 and 20 bps are secondary, with
selection and mechanics unchanged. The sensitivities are descriptive only: no
10- or 20-bps outcome creates GO, REVIEW, or financial no-go. The accepted-entry
schedule and nominal holding convention tend to align turnover opportunity, but
cash, capacity, lifecycle exits, position values, and realized turnover can
legitimately differ. Cost sensitivity informs interpretation; it is not a
decisive test of security-selection value and does not change the frozen 5-bps
strategy.

Path analysis starts at the original date and the first XNYS session of each
January, April, July, and October that leaves at least 504 sessions through
2026-09-22. For each eligible window compare breakout CAGR with the median
control CAGR under the frozen window calculation and define:

`start_win_rate = count(CAGR_breakout,window > median_i(CAGR_control,i,window)) / eligible_windows`

Equality is not a win. If `start_win_rate < 0.50`, this safeguard caps GO at
REVIEW. At or above 0.50, including exactly 50%, it does not restrict GO. It
never produces financial no-go and cannot override a primary no-go. Report the
full window distribution and the 25th-percentile CAGR gap descriptively; the
former 70% GO threshold, 50% no-go threshold, and decisive percentile-gap bands
are removed. The overlapping windows are strongly correlated, not independent
replications, and receive no binomial-style significance claim.

## 16. Ordering and concentration safeguards

**Decision status: APPROVED AFTER EXPLICIT POST-OBSERVATION AUDIT**

Breakout ordering remains frozen score then stable `security_id`. A secondary
test may permute only scores exactly equal at stored precision, using its own
registered stream. No near-tie parameter is introduced. A sign reversal limits
the descriptive interpretation but has no automatic decision consequence; the
final GO list contains no tie-based threshold.

Define each position's signed net contribution using the frozen accounting
identity: realized net P&L for a closed position and end-date marked net P&L for
an open position, using the same end mark included in final equity and no
hypothetical exit. The sum of position contributions must reconcile, within the
frozen accounting tolerance, to `P_net = final_equity - initial_capital`.

For each portfolio define:

`A = sum_j(abs(contribution_j))`

When `A > 0`, define:

`C10 = sum(the 10 largest strictly positive contributions) / A`

If fewer than ten positive contributions exist, sum all of them. If none is
positive while `A > 0`, set `C10 = 0`. If `A = 0`, C10 is undefined. Apply the
same definition to breakout and every invariant-valid control. Undefined C10
does not exclude or replace a seed.

Report breakout C10, the complete defined control distribution, median, P95,
breakout inclusive percentile under Section 9's convention, and defined and
undefined counts. If `C10_breakout > P95(C10_controls)`, the diagnostic caps GO
at `REVIEW — INVESTIGATE CONCENTRATION DRIVERS`; equality does not. C10 never
produces financial no-go or overrides a primary no-go. If no reliable relative
comparison can be formed despite valid paths, report `NOT_INTERPRETABLE /
REVIEW`. An accounting reconciliation or unresolved lifecycle integrity failure
is `INVALID / BLOCKED`.

All former absolute top-1/top-10 GO, REVIEW, and no-go bands are removed because
the treatment's historical concentration was known before this revised protocol
was finalized. The previously observed 63.38% top-10 share used a different
denominator and is historical context only; it must not be compared directly
with C10. No minimum-net-profit denominator threshold is used.

Higher breakout C10 can reflect ex-ante risk differences, including prior
volatility, dispersion, sector, entry-date, or lifecycle concentration. Those
causally available diagnostics are exploratory only: they cannot create
post-hoc matching, exclusions, thresholds, or strategy tuning. Leave-one-out
analysis is also explanatory only and cannot delete trades.

## 17. Secondary-safeguard provenance audit and deferrals

**Decision status: AUDITED AND APPROVED**

The treatment path and several close proxies were already known or calculable
from Phase 3. A threshold is not independently pre-registered merely because
the randomized-control distribution is still unknown. The audit is:

| Safeguard | Metric | Exact threshold | Definition | Treatment/proxy known from Phase 3? | Independent threshold provenance | Selected after treatment behavior was observable? | Approved treatment | Final consequence | Remaining decision |
|---|---|---|---|---|---|---|---|---|---|
| Cost sensitivity | Conditional-control results at 10/20 bps; 5 bps remains frozen baseline | None | Absolute cost scenarios | Yes: treatment trades, turnover, and 5-bps result were known | None for decisive 10/20-bps bands | Yes | Descriptive only | No GO cap or financial no-go | None |
| Start-date robustness | `start_win_rate` | REVIEW cap only when `< 0.50`; equality passes | Control-relative strict wins across approved quarterly windows | Yes: treatment path and window outcomes were calculable | No independent provenance for former 70%, no-go, or P25 bands; removed | Yes | Explicit human-approved relative diagnostic | Caps GO at REVIEW only | None |
| Former absolute concentration | Signed top-1/top-10 over aggregate net profit | All 25%/50%/60%/80% bands removed | Absolute | Yes; Phase 3 reported concentration | None independent | Yes | Historical context only | None; integrity failures remain invalid | None |
| Relative C10 | Positive top-ten contribution sum divided by total absolute contribution | REVIEW cap only when breakout `> control P95`; equality passes | Control-relative | Yes: treatment contributions and prior concentration were known; C10 denominator is new | No claim of independent prospective provenance; explicitly human approved | Yes | Exploratory registered robustness diagnostic | Caps GO at REVIEW only | None |
| Former alpha/beta gate | Absolute alpha sign and HAC lower bound | Removed | Absolute | Treatment return path was known; valid dividend-aware benchmark was not yet frozen | None independent | Yes | Removed | None | None |
| Relative beta | Beta under identical registered regression | REVIEW cap only when breakout `> control P95`; equality passes | Control-relative | Treatment path was known and beta was calculable once benchmark exists | No claim of independent prospective provenance; explicitly human approved | Yes | Registered relative diagnostic | Caps GO at REVIEW only | None |
| Candidate scarcity | `mean_scarcity_rate` with denominator 602 per seed | REVIEW cap only when `> 0.01`; equality passes | Absolute comparability rate across registered controls | No control scarcity result exists; exposure concern was known | Explicit human approval in final freeze, not independent prospective provenance | Rule approved after historical treatment schedule was known | Comparability safeguard | Caps GO at REVIEW only | None |
| Exact-score ties | Frozen-order versus exact-tie permutations | No threshold | Descriptive sensitivity | Treatment scores/order were known | None independent | Yes | Descriptive only | None | None |
| Analytical power | Assumption-based SE, interval width, and MDE scenarios | No financial threshold beyond primary registered interval rules | Hypothetical | Not fitted to treatment outcomes | Declared assumptions only | No outcome fitting, but not a performance gate | Descriptive interpretation | None | None |
| Native-trend / generic-random controls | Secondary portfolio summaries | No threshold | Secondary controls | Treatment results known | None independent | Yes | Descriptive only | None | None |
| SPY data/regression integrity | Coverage, alignment, entitlement, frozen digest, valid regression | Must pass specified integrity checks | Technical/data gate | Existing price-only limitation was known | Provider and accounting requirements, not financial performance bands | Not a return threshold | Mandatory preflight | Failure is `INVALID / BLOCKED` | Pending execution only |

The audit found no additional financial safeguard with authority to create
no-go or add a GO condition. Consequently, `NO-GO_SECONDARY_SAFEGUARD` is not an
active category. Only `NO-GO_NEGATIVE` and `NO-GO_IMMATERIAL` can produce a
financial no-go. The approved secondary decision effects are the REVIEW-only
caps for scarcity, start-date win rate, relative C10, and relative beta.

Native simple-trend arrivals and generic PIT-valid random entry may be retained
only as separately labeled secondary controls with independent streams. They do
not replace the accepted-schedule conditional control or its endpoints.

Ex-ante matching by sector, market capitalization, or additional characteristics
is:

`DEFERRED — NOT PART OF PHASE 4B`

It requires additional PIT reference data and new design choices, is unnecessary
for the primary conditional experiment, and cannot be introduced after seeing
Phase 4B results and represented as pre-registered primary evidence.

The proposed 2015-01-01 through 2021-09-24 historical extension remains
`HISTORICAL_OOS_BLOCKED`: identity, lifecycle, terminal-value, and temporal
independence evidence are not adequate. No synthetic repair is allowed.

## 18. Dividend-aware SPY benchmark prerequisite

**Decision status: APPROVED DESIGN; PRE-FLIGHT B NOT EXECUTED**

The current persisted SPY benchmark is split-adjusted **price return** and
excludes dividends. It must not be called total return.

The existing EODHD integration exposes the necessary candidate interfaces:

- `eod/SPY.US` for daily raw OHLC and provider `adjusted_close`;
- `div/SPY.US` for cash dividends; and
- `splits/SPY.US` for split events.

EODHD is therefore the proposed provider, subject to separate entitlement,
methodology, coverage, and license validation. Provider `adjusted_close` is only
a cross-check because repository evidence says it is split- and
dividend-adjusted and can be recomputed after later dividends; it is not, by
itself, a verified immutable total-return benchmark.

The separately authorized preparation must freeze raw provider responses and
construct a share-and-cash ledger. Starting with one SPY share, apply each split
ratio on its verified effective date, credit each cash dividend to the shares
entitled on its verified ex-date under the provider's unit convention, value at
raw close, and reinvest distributions at that close for the total-return index.
Validate the action sequence and units against provider documentation and
reconcile daily/cumulative results to `adjusted_close` within a tolerance fixed
before comparison.

Requirements:

- coverage from at least the prior XNYS close on 2021-09-24 through 2026-09-22;
- exact alignment to the frozen XNYS calendar, with duplicate/missing/nonfinite
  actions and prices reported; no interpolation or forward fill;
- OHLC integrity, split-factor, dividend ex-date/amount/currency, discontinuity,
  and adjusted-close reconciliation checks;
- explicit subscription entitlement and license/retention permission;
- immutable raw response bytes plus normalized canonical dataset, request
  metadata without credentials, acquisition timestamp, provider revision fields,
  code/config/container digests, and SHA-256 for every raw file and canonical
  manifest/dataset.

Benchmark total-return calculations are context/risk evidence and remain
separate from the unadjusted executable prices and frozen costs used by the
portfolio engine.

Mandatory gate:

`SPY_TOTAL_RETURN_BENCHMARK_VERIFIED_AND_FROZEN`

It passes only after a separately authorized step has selected the exact EODHD
datasets, verified methodology and full coverage, acquired and validated the
data, frozen digests/version/license evidence, and received explicit human
approval. This amendment fetched no data. The gate is currently **not passed**.

## 19. Beta safeguard

**Decision status: APPROVED — FROZEN FOR PREFLIGHT**

After the benchmark gate passes, estimate beta for breakout and every
invariant-valid control using the same dividend-aware SPY total-return series,
frozen XNYS calendar, daily return convention, zero cash-rate convention,
regression specification, alignment, and missing-data rules. Missing dates are
not imputed. Report breakout beta, the full control distribution, median, P95,
breakout inclusive percentile and ties under Section 9, and Newey-West/HAC 95%
intervals with lag 20 as descriptive uncertainty.

If `beta_breakout > P95(beta_controls)`, beta caps GO at REVIEW; equality does
not. Otherwise beta does not restrict GO. It never independently produces
financial no-go or overrides a primary no-go. All former absolute beta, positive
alpha, and HAC lower-bound GO thresholds are removed.

High relative beta indicates unusually high systematic exposure within the
registered control population; it does not itself establish negative alpha,
excessive investment risk, or lack of selection value. If the comparison cannot
be reliably evaluated despite otherwise valid paths, report
`HUMAN_DECISION_REQUIRED` rather than inventing a method, threshold, or
imputation. A benchmark, alignment, or regression integrity failure is
`INVALID / BLOCKED`.

## 20. Prospective holdout and registry status

**Decision status: APPROVED FORMAL DESIGN — REGISTRY INACTIVE**

The append-only registry code is published but inactive. No canonical
prospective signal has been registered. Sessions 2026-09-23 through 2026-10-08,
if reconstructed later, are `RETROACTIVE` and ineligible for contemporaneous
prospective validation.

A session becomes a valid prospective observation only if all of these existed
operationally before its NEXT_OPEN:

- frozen strategy/configuration and operational human approval;
- PIT-valid inputs and snapshot integrity;
- canonical signal/no-signal/failure record generated before the cutoff;
- valid append-only hash chain with no overwrite by later correction; and
- independent server-side timestamp evidence from a separately administered
  service.

Without independent timestamp proof a record is
`NOT_INDEPENDENTLY_TIMESTAMPED` and cannot count toward the verified holdout.
Corrections are new linked records and preserve originals. Registration,
execution simulation, and outcome evaluation remain separate authorizations.

The first holdout session is the **first XNYS session that actually satisfies all
prerequisites**, not a backdated or arbitrary calendar date. Before activation,
the approval record must freeze that rule, authorized operators/reviewers, a
minimum of 1,250 valid registered XNYS sessions, and a 20-XNYS-session maturation
buffer after the last included signal. The unseal date is the later of the
1,250th valid registration and completion of that buffer. Because activation has
not occurred, an exact calendar unseal date does not yet exist and must not be
invented. No outcome-conditioned metric may be viewed before unsealing.

Phase 4B historical work is isolated from the registry and cannot populate,
revise, or inspect the prospective holdout.

Interim operational reviews may examine registration completeness, missing
data, snapshot/timestamp integrity, failures, scheduler reliability, and
reproducibility. They must not examine holdout returns, performance, or any
outcome-conditioned metric. There is no early statistical GO, interim
performance unsealing, or sequential-inference procedure. Any earlier formal
performance evaluation requires a separately approved prospective amendment
before relevant outcomes are unsealed. Local Git or client-controlled commit
timestamps and a late remote push do not establish contemporaneous validity.

## 21. Reproducibility and mandatory preflight

**Decision status: MANDATORY — NOT EXECUTED**

Before Phase 4B financial execution:

1. preserve this approved methodology and obtain separate Phase 4B execution
   authorization;
2. reproduce all frozen checkpoint, PIT-universe, portfolio, and migration gates;
3. complete PRE-FLIGHT A, materializing exactly 602 accepted-entry records with
   stable identity, decision/execution sessions, frozen ordinal, multiplicity,
   source provenance, aggregate reconciliation, and fail-closed digests without
   reconstructing the schedule from a new ranking;
4. complete PRE-FLIGHT B by verifying EODHD entitlement/licensing, acquiring
   and freezing raw SPY prices/dividends/splits, validating actions, building
   and calendar-aligning total return, fixing reconciliation tolerance before
   comparisons, preserving raw/normalized artifacts and digests, and obtaining
   human approval of the benchmark;
5. implement with fixtures/mocks and review the manifest, seed registry,
   selection, insufficient-pool ledger, and bootstrap;
6. seal all inputs, code/config/container versions, seed list, thresholds, and
   output schema before returns are exposed;
7. run once without inspecting partial results, rerun from the same manifest,
   and require byte/canonical-hash deterministic equality; and
8. complete an independent integrity audit before interpretation.

Current statuses:

- `PRE-FLIGHT_A_NOT_EXECUTED`
- `PRE-FLIGHT_B_NOT_EXECUTED`

Neither preflight is authorized by this protocol freeze. Both must pass before
any Phase 4B financial calculation. Neither requires registry activation or
prospective-holdout maturation.

No result-dependent code, threshold, seed, or dataset change is allowed. A
required correction creates a new approved manifest and invalidates the prior
attempt without using its financial results.

## 22. Engineering feasibility and remaining work

**Decision status: TECHNICAL EXECUTION PENDING**

Reusable components include the security-ID-native PIT universe, temporal alias
resolution, daily bars, frozen signal/features, engine, cash/capacity/lifecycle
accounting, XNYS calendar, provider clients, and deterministic diagnostics. The
prospective registry implementation exists but is inactive.

Phase 4B still requires a canonical accepted-schedule exporter/verifier,
experiment-manifest and seed registry, conditional-pool generator, immutable
attempt/incident ledger, stationary bootstrap, SPY total-return preparation and
verification, HAC analysis, and orchestration of the frozen robustness gates.
These are implementation tasks under separate authorization, not changes made
by this document.

## 23. Limitations

**Decision status: FROZEN**

- The historical window is reused in-sample with unknown parameter provenance.
- Conditional controls test selection given accepted timing, not signal-arrival
  value.
- All controls share one market history; 1,000 seeds are not 1,000 histories.
- Different selections legitimately change cash, capacity, exposure, and exits.
- Legitimate path-dependent scarcity can create asymmetric exposure and weaken
  the conditional economic comparison without invalidating the seed.
- The bootstrap does not replay portfolio paths and depends on stationarity.
- Five years may be seriously underpowered for a 2% annual advantage.
- Sector/size matching is deferred and latent risk may differ.
- The current SPY artifact is not dividend-aware total return.
- Older historical PIT evidence remains inadequate.
- No canonical independently timestamped prospective observation exists.
- No backtest establishes investment suitability or future performance.

## 24. Final human-decision audit

**Decision status: METHODOLOGY APPROVED; TECHNICAL EXECUTION PENDING**

### A. Explicitly approved methodology

- conditional research question based on the accepted-entry schedule, without
  claiming to test signal-arrival value;
- exact 602-ticket schedule, causal PIT-valid trend pool, and uniform selection
  without replacement by stable `security_id`;
- retention of every invariant-valid seed experiencing legitimate scarcity;
- 1,000 attempted seeds, minimum 800 invariant-valid controls, non-circular
  deterministic PCG64DXSM derivation, and complete audit trail;
- mean scarcity rate with a strict `> 1%` REVIEW-only GO cap;
- CAGR-minus-median-control economic endpoint and +2-pp materiality threshold;
- mean-individual-control-log-growth estimand, registered stationary bootstrap,
  `NO-GO_NEGATIVE`, and `NO-GO_IMMATERIAL`;
- cost sensitivities as descriptive only;
- start-date strict-win rate with REVIEW-only cap below 50%;
- relative C10 and beta with REVIEW-only cap above their control P95;
- removal of all secondary financial no-go safeguards and unapproved absolute
  concentration, beta, alpha, and path thresholds;
- separation of historical robustness from prospective validation; and
- prospective registration/holdout rules and two separate technical preflights.

### B. Frozen historical facts and limitations

Section 2's baseline, Section 3's parameter evidence, and
`IN_SAMPLE_REUSED / PROVENANCE_UNKNOWN` remain unchanged. The historical
treatment path, including previously observed concentration, was known before
this final freeze. No historical result is promoted to prospective evidence.

### C. Pending technical execution

- `PRE-FLIGHT_A_NOT_EXECUTED`: canonical ledger materialization and verification;
- `PRE-FLIGHT_B_NOT_EXECUTED`: SPY total-return acquisition, validation, and
  frozen approval;
- fixture/mock implementation and verification;
- base-manifest and input sealing;
- deterministic rerun and reproducibility checks;
- independent integrity audit; and
- separate authorization to execute Phase 4B.

These are technical prerequisites, not unresolved statistical-design choices.

### D. Unresolved methodology

`NONE`

The complete provenance audit in Section 17 found no additional financial
no-go or GO condition requiring human resolution.

## 25. Execution prohibition and amendment status

**Decision status: METHODOLOGY APPROVED — EXECUTION NOT AUTHORIZED**

This protocol resolves the previous contradictions between candidate counts and
accepted-entry timing, exposure matching and economic outcomes, CAGR and
log-growth units, seed rejection and complete attempted-seed reporting, and an
arbitrary holdout date versus operational contemporaneous registration.

It authorizes no Phase 4B calculation, data acquisition, registry activation,
database migration, strategy/score/engine change, tag, or push. The only Git
mutation authorized at this stage is the documentation-only local checkpoint of
this protocol; remote publication requires separate human authorization.

Current protocol status:

`PHASE_4A_METHODOLOGY_APPROVED — PHASE_4B_PREFLIGHT_PENDING`

This local methodological freeze is not Phase 4B authorization. Phase 4B remains
blocked until PRE-FLIGHT A and PRE-FLIGHT B pass and a separate execution
authorization is recorded. Prospective registry activation remains separately
prohibited.
