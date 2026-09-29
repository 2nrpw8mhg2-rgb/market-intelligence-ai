# POINT_IN_TIME Backtest Comparison — Preflight Result

> Historical pre-correction preflight retained for audit. Its PIT hash and
> blockers are superseded by the approved canonical identity-native hash
> `74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d`
> and `backend/docs/PIT_ALIAS_CONTINUITY_REPORT.md`. No financial PIT backtest
> was run while producing the replacement readiness state.

**Status:** **NOT_VALID_FOR_COMPARISON**
**Code commit:** `7b680f4b37c0321d41be4f02818ccbd92f75ff3e`
**Research window requested:** 2021-09-27 through 2026-09-22
**Calendar:** XNYS
**Validated PIT universe hash:** `51c3041e7a1f8d11218dfa056d4171e51cf88c4947b2714e01a9e9af4287b5fd`

## Executive result

The production-quality PIT research backtest was **not executed** because its
mandatory data-integrity preflight failed. Publishing PIT financial metrics in
this state would require ticker-based inference or incomplete historical price
coverage, both of which are explicitly forbidden.

No strategy, score, execution, portfolio, universe-validation, or market-data
record was changed. No financial-performance run or portfolio simulation was
started, and no run ID was created.

## A. Fixed-universe historical reference

The persisted database contains the requested fixed-universe source run:

| Field | Persisted value |
|---|---|
| Run ID | `cd4da596-8380-5b5c-9b55-252c601be6f6` |
| Config hash | `9fdee279f178447301a837656340c823e5e2a300656b65c9ada69607c702aa22` |
| Universe mode | `FIXED_UNIVERSE_RESEARCH` |
| Research window | 2021-09-27 through 2026-09-22 |
| Entry | `NEXT_OPEN` |
| Events | 4,831 |

The numerical fixed-universe results supplied in the research request remain the
comparison reference. They were not hard-coded as newly computed PIT results.

## B. Point-in-time result

**No valid PIT result exists.** The runtime database contains zero persisted PIT
membership intervals, so the `POINT_IN_TIME` path has no authoritative membership
input to execute.

| PIT runtime preflight | Result |
|---|---:|
| Persisted `universe_memberships` | 0 |
| Validated eligible membership records intersecting the window | 603 |
| Unique required historical ticker aliases | 603 |
| Required aliases with no persisted Massive bars | 102 |
| Existing required aliases whose `symbols.security_id` is null | 501 |
| Total persisted market bars | 611,651 |

The 102 aliases without a persisted price series are:

`AAL`, `AAP`, `ABMD`, `ALK`, `AMTM`, `ANSS`, `ATVI`, `AVB`, `BBWI`, `BF-B`,
`BIO`, `BLDR`, `BRK-B`, `BWA`, `CAG`, `CE`, `CERN`, `CMA`, `CPB`, `CTLT`,
`CTRA`, `CTXS`, `CZR`, `DAY`, `DFS`, `DISCA`, `DISH`, `DRE`, `DXC`, `EA`,
`EMBC`, `EMN`, `ENPH`, `EPAM`, `ETSY`, `FBIN`, `FMC`, `FRC`, `FTRE`, `GPS`,
`HBI`, `HES`, `HOLX`, `INFO_OLD1`, `IPG`, `IPGP`, `JNPR`, `K`, `KD`, `KLG`,
`KMX`, `KSU`, `LEG`, `LKQ`, `LNC`, `LUMN`, `LW`, `MBC`, `MBGL`, `MHK`,
`MKTX`, `MOH`, `MRO`, `MTCH`, `NLSN`, `NWL`, `OGN`, `ONL`, `PAYC`, `PBCT`,
`PENN`, `PHIN`, `POOL`, `PVH`, `PXD`, `QRVO`, `RAL_OLD`, `RHI`, `SBNY`,
`SEDG`, `SEE`, `SIVB`, `SLVM`, `SOLS`, `TAP`, `TFX`, `TTD`, `TWTR`, `UA`,
`UAA`, `VFC`, `VGNT`, `VNO`, `VSNT_OLD`, `WBA`, `WHR`, `WRK`, `WU`, `XLNX`,
`XRAY`, `ZIMV`, `ZION`.

This list includes modern, former, delisted, changed, and provider-specific
aliases. It must not be repaired by blindly substituting a modern ticker.

## C. Fixed versus PIT differences

Not calculated. There is no valid PIT event set, so absolute or relative
performance differences would be misleading.

## D. Survivorship-bias attribution

Not calculated. Common, removed, and added signals require a completed PIT event
set generated from authoritative identity-linked memberships and adequate price
coverage. Inferring these from ticker strings would reintroduce the exact identity
error the PIT architecture is designed to prevent.

## E. Data-integrity checks

| Check | Result |
|---|---|
| Expected universe hash retained | PASS |
| Half-open membership rule available | PASS |
| Audit-only `MRP_OLD` excluded by validated universe | PASS |
| Membership intervals persisted for runtime | **FAIL — zero rows** |
| Every eligible membership linked by `security_id` to its historical alias | **FAIL — 501 existing aliases are not linked** |
| Price series available for every required alias | **FAIL — 102 aliases have no persisted bars** |
| No ticker-only fallback required | **FAIL CLOSED — execution stopped before fallback** |
| Signal-level membership/boundary validation | NOT RUN — no valid event set |
| Ticker-reuse leakage check on produced signals | NOT RUN — no valid event set |
| Duplicate-signal identity check | NOT RUN — no valid event set |
| Look-ahead audit on produced signals | NOT RUN — no valid event set |

## F. Exact blocker and required remediation

Before a production-quality PIT comparison can run:

1. Import the already validated half-open PIT membership records into
   `universe_memberships`, retaining `security_id`, confidence, provenance, and
   explicit non-tradable status.
2. Attach each historical ticker alias to the same proven `security_id`; do not
   infer the association from ticker equality.
3. Ingest and validate the required historical Massive price series, including
   former/delisted aliases where Massive supports them.
4. For provider-specific aliases such as `*_OLD`, use only proven market-data
   mappings. Unresolved mappings must continue to fail closed.
5. Repeat coverage and session-level integrity checks before starting the event
   study.
6. Permit the portfolio research service to consume a validated PIT source run
   without weakening its existing fixed-universe safeguards; the current Phase 6
   service explicitly accepts only `FIXED_UNIVERSE_RESEARCH` sources.

## Limitations

- Universe reconstruction readiness did not itself populate the production
  membership table or prove that every alias had bars in the runtime store.
- The current 611,651 stored bars primarily cover current constituents and are
  insufficient for the requested PIT comparison.
- No missing prices were filled, no alias was substituted, and no identity was
  inferred.
- Historical backtest results are research results and are not expected future
  returns. In this preflight, no new historical performance result was produced.
