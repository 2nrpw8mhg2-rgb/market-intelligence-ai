# PIT Data Materialization — Final State

**Research window:** 2021-09-27 through 2026-09-22
**Financial backtest:** NOT RUN
**Data readiness:** PASS
**Execution readiness:** READY_FOR_PIT_EXECUTION

## Membership and identity

| Measure | Result |
|---|---:|
| Eligible memberships | 603 |
| Audit-only/non-tradable records | 2 (`MRP_OLD`, old `VSNT_OLD`) |
| Resolved temporal chains | 603 |
| Alias intervals | 619 |
| IDENTITY_BLOCKED | 0 |
| Database validation anomalies | 0 blocking |

The EODHD HistoricalTickerComponents row that linked the 2026 VSNT interval to
old Versant Corp was corrected using S&P DJI, SEC/issuer, stable-identifier, and
cached provider evidence. Versant Media Group is stored as a distinct security:

- security_id `9852cfda-78da-515f-bcda-6652a57bfd55`
- ticker/provider symbol `VSNT`
- CIK `0002067876`
- CUSIP `925283103`
- ISIN `US9252831030`
- FIGI `BBG01Y0M8K11`

Old Versant Corp remains separately recorded as audit-only and supplies no PIT
prices. `MRP_OLD` remains audit-only/non-tradable.

## Market data

The corrected VSNT series materialized 196 adjusted-derived EODHD observations
from the already validated cache. Massive rows were not replaced.

LUV's only EODHD gap, 2023-04-06, is supplied logically from its existing
Massive adjusted aggregate, preserving each provider's stored provenance.
SBNY's 2023-03-13 and 2023-03-14 sessions are proven natural posthistory/halt
limitations and were not filled.

| Measure | Result |
|---|---:|
| Missing price series | 0 |
| MATERIAL_DATA_GAP | 0 |
| Genuine missing-data sessions | 0 |
| Natural lifecycle-unavailable sessions | 30 |
| Natural causal warm-up sessions | 1,632 |
| Eligible security-sessions | 629,414 |
| Complete causal-feature sessions | 627,752 |

No interpolation, forward-fill, synthetic price, OTC substitution, or
ticker-only identity fallback was used.

## Deterministic universe fingerprint

Pre-correction audit hash:
`51c3041e7a1f8d11218dfa056d4171e51cf88c4947b2714e01a9e9af4287b5fd`

Corrected identity-native hash:
`74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d`

Dates, eligibility boundaries, 1,252 sessions, and daily constituent counts are
unchanged. The hash changes because one incorrect security identity was
replaced. The corrected fingerprint has been formally approved and is now the
canonical PIT universe hash.

See `backend/docs/PIT_ALIAS_CONTINUITY_REPORT.md` for evidence and case-level
detail.
