# POINT_IN_TIME S&P 500 Universe Validation

**Research window:** 2021-09-27 through 2026-09-22
**Calendar:** XNYS regular trading sessions (`exchange_calendars`)
**Membership semantics:** entry inclusive, exit exclusive
**Decision:** **READY_FOR_PIT_BACKTEST**

## Executive conclusion

All session-level and structural checks passed; all 79 known historical exceptions exit before the research window and are never eligible. This report validates eligibility only. No strategy, signal, score, portfolio return or financial-performance backtest was executed.

## Data sources and provenance

- EODHD `HistoricalTickerComponents`, preserved in the POC 3 security master at `backend/data/eodhd_poc3/audit.json`.
- POC 5 critical-case classifications at `backend/docs/EODHD_CRITICAL_RESOLUTION.csv`.
- Every reconstructed record retains its internal `security_id`, dated half-open membership interval, stable identifiers, identity/reuse status, symbol-change evidence and source label.
- No current-snapshot substitution, synthetic history, forward/backward fill or silent membership repair was performed.

## Session coverage

| Measure | Result |
|---|---:|
| XNYS sessions validated | 1252 |
| Minimum constituents | 502 |
| Maximum constituents | 505 |
| Median constituents | 503 |
| Sessions with a membership transition | 86 |
| Additions observed inside window | 99 |
| Removals observed inside window | 100 |
| Deterministic reconstruction hash | `51c3041e7a1f8d11218dfa056d4171e51cf88c4947b2714e01a9e9af4287b5fd` |

## Boundary and identity rules

- Eligibility is `valid_from <= session < valid_to`; an exit-date security is absent on the exit boundary.
- Repository queries, period selection, importer overlap detection and the backtesting membership predicate now use the same half-open semantics.
- Session transitions are computed by `security_id`, not ticker string.
- The 16 known reused-ticker cases from POC 5 are outside the research window and never become eligible.
- 32 source records carry ticker-change evidence; membership continuity is keyed by security identity where stable evidence exists.
- Tests explicitly cover entry, exit, ticker change, ticker reuse isolation, no out-of-interval eligibility, no duplicate eligible identities and deterministic reconstruction.

## Anomalies

| Category | Count |
|---|---:|
| IMPOSSIBLE_MEMBERSHIP_INTERVAL | 0 |
| MISSING_SECURITY_ID | 0 |
| MISSING_STABLE_IDENTIFIER | 0 |
| OVERLAPPING_IDENTITY_INTERVALS | 0 |
| DUPLICATE_ELIGIBLE_SECURITY | 0 |
| DUPLICATE_ELIGIBLE_TICKER | 0 |
| UNRESOLVED_ELIGIBLE_IDENTITY | 0 |
| TICKER_REUSE_ELIGIBLE | 0 |
| ENTRY_BOUNDARY_VIOLATION | 0 |
| EXIT_BOUNDARY_VIOLATION | 0 |
| EXPLICIT_NON_TRADABLE_RECORD | 1 |

Total findings: **1**; blocking anomalies: **0**.

### Anomaly details

| Category | Ticker | security_id | Affected sessions | Exact evidence required |
|---|---|---|---|---|
| EXPLICIT_NON_TRADABLE_RECORD | MRP_OLD | 6d107392-1574-5d84-9836-defb4f684946 | 2025-01-21–2025-02-07 (14 sessions) | none; retained as an explicit audited exclusion |

## Unresolved exceptions

POC 5 contains 79 historical critical cases: 79 are classified `NOT_RELEVANT_TO_TEST_WINDOW`, including 16 unresolved ticker-reuse identities. They remain unresolved for earlier research but every one has an exclusive membership exit before 2021-09-27. They are preserved as exceptions rather than repaired and do not enter any validated daily universe in this window.

### MRP_OLD final classification

**EXPLICITLY_NON_TRADABLE_OR_INVALID.** The source record starts on 2025-01-21, which is Lennar's distribution record date, before any public Millrose market existed. Lennar documented when-issued trading as beginning around 2025-02-05 and regular-way NYSE trading under `MRP` on 2025-02-07. Millrose's SEC filing independently states there was no public trading market before 2025-02-05. S&P DJI documented that Lennar remained in the S&P 500 and that Millrose entered the **S&P SmallCap 600**, effective 2025-02-10. EODHD contains no bars or stable identifier for `MRP_OLD`; its separate `MRP.US` series begins 2025-02-05 and has FIGI `BBG01RQYH2X7` and ISIN `US6011371027`. These facts prove that the 2025-01-21–2025-02-10 source interval must not be treated as an independently tradable S&P 500 membership. It remains in the audit data and is explicitly excluded; it is not silently deleted or mapped to `MRP` by ticker similarity.

Primary corroboration: [Lennar spin-off dates](https://investors.lennar.com/press-releases/2025/01-10-2025-230022870), [S&P DJI index announcement](https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20250205-1476446/1476446_5-len-mrp-spin.pdf), and [Millrose SEC filing](https://www.sec.gov/Archives/edgar/data/2017206/000201720626000002/ck0002017206-20251231.htm).

## Representative dates and change boundaries

Additions/removals are differences from the immediately preceding XNYS session. Rows surrounding sampled transition sessions demonstrate the boundary behavior.

| Session | Constituent count | Additions effective | Removals effective | Anomalies |
|---|---:|---|---|---|
| 2021-09-27 | 504 | — | — | — |
| 2021-09-30 | 504 | — | — | — |
| 2021-10-01 | 505 | SLVM | — | — |
| 2021-10-04 | 504 | — | SLVM | — |
| 2022-06-17 | 503 | — | — | — |
| 2022-06-21 | 502 | KDP, ON | IPGP, UA, UAA | — |
| 2022-06-22 | 502 | — | — | — |
| 2023-08-24 | 502 | — | — | — |
| 2023-08-25 | 502 | KVUE | AAP | — |
| 2023-08-28 | 502 | — | — | — |
| 2024-12-20 | 503 | — | — | — |
| 2024-12-23 | 503 | APO, LII, WDAY | AMTM, CTLT, QRVO | — |
| 2024-12-24 | 503 | — | — | — |
| 2025-01-17 | 503 | — | — | — |
| 2025-01-21 | 503 | — | — | EXPLICIT_NON_TRADABLE_RECORD:MRP_OLD |
| 2025-01-22 | 503 | — | — | EXPLICIT_NON_TRADABLE_RECORD:MRP_OLD |
| 2025-02-06 | 503 | — | — | EXPLICIT_NON_TRADABLE_RECORD:MRP_OLD |
| 2025-02-07 | 503 | — | — | EXPLICIT_NON_TRADABLE_RECORD:MRP_OLD |
| 2025-02-10 | 503 | — | — | — |
| 2026-01-02 | 503 | — | — | — |
| 2026-01-05 | 504 | VSNT_OLD | — | — |
| 2026-01-06 | 503 | — | VSNT_OLD | — |
| 2026-09-18 | 503 | — | — | — |
| 2026-09-21 | 503 | BE, ILMN, P | BLDR, TAP, TTD | — |
| 2026-09-22 | 503 | — | — | — |

## Runtime identity integration

The runtime `UniverseMembership` and import/query path is keyed authoritatively by `security_id`, retains source confidence and provenance, verifies the dated ticker alias against the same security, and fails closed for missing/mismatched/unresolved identities. Explicitly proven non-tradable/invalid source records are retained for audit and excluded from tradable membership; no ticker fallback is permitted.

## Readiness decision

**READY_FOR_PIT_BACKTEST**

All session-level and structural checks passed; all 79 known historical exceptions exit before the research window and are never eligible. Readiness is limited to universe reconstruction for 2021-09-27 through 2026-09-22; this validation does not authorize a wider historical window and did not execute the PIT backtest.
