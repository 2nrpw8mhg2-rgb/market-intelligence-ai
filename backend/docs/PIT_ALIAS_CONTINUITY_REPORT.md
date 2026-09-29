# PIT Temporal Alias Continuity — Final Blocker Resolution

**Data-readiness dry-run:** **PASS**
**Execution decision:** **READY_FOR_PIT_EXECUTION**
**Research window:** 2021-09-27 through 2026-09-22
**Calendar:** XNYS (1,252 sessions)
**Membership rule:** `valid_from <= session < valid_to`

No financial backtest, return calculation, portfolio simulation, strategy change,
score change, interpolation, or forward-fill was performed.

## Final result

| Measure | Result |
|---|---:|
| Eligible security identities | 603 |
| Resolved temporal chains | 603 |
| Alias intervals | 619 |
| Multi-alias securities | 15 |
| IDENTITY_BLOCKED | **0** |
| MATERIAL_DATA_GAP | **0** |
| NATURAL_PREHISTORY_LIMITATION | 24 |
| NATURAL_POSTHISTORY_LIMITATION | 16 |
| Eligible security-sessions | 629,414 |
| Complete causal-feature sessions | 627,752 |
| Natural causal warm-up sessions | 1,632 |
| Natural lifecycle-unavailable sessions | 30 |
| Genuine missing-data sessions | **0** |

The 603 eligible identities are supplemented by two audit-only/non-tradable
records: `MRP_OLD` and the incorrectly resolved old `VSNT_OLD` source row.

## A. VSNT_OLD resolution

**Final classification:** `RESOLVED_WITH_REPLACEMENT_IDENTITY`

The EODHD HistoricalTickerComponents row says `VSNT_old`, Versant Corp, CIK
`0000865917`, CUSIP `925284101`, for the half-open interval
`[2026-01-05, 2026-01-06)`. That company traded from 1996 through 2012 and is
not the security represented by the 2026 S&P spin-off membership.

Authoritative evidence identifies the 2026 security as:

| Field | Correct value |
|---|---|
| Legal issuer/security | Versant Media Group, Inc., Class A common stock |
| Ticker | VSNT |
| Exchange | Nasdaq Global Select Market |
| First when-issued trading | 2025-12-15 |
| First regular-way trading | 2026-01-05 |
| S&P 500 transient membership | `[2026-01-05, 2026-01-06)` |
| S&P SmallCap 600 effective entry | Before open 2026-01-06 |
| CIK | 0002067876 |
| CUSIP | 925283103 |
| ISIN | US9252831030 |
| FIGI | BBG01Y0M8K11 |
| Correct security_id | 9852cfda-78da-515f-bcda-6652a57bfd55 |
| Price provider symbol | VSNT.US / VSNT |

S&P DJI's 2025-12-23 announcement states that Versant Media Group would enter
the S&P SmallCap 600 before the 2026-01-06 open following its spin-off from S&P
500 constituent Comcast. Versant's SEC-filed release and Form 10-K state that
regular-way VSNT trading began on 2026-01-05. SEC-reported holdings identify the
common stock as CUSIP 925283103 / ISIN US9252831030. The cached EODHD reference
record independently supplies the same ISIN and FIGI.

Primary evidence:

- https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20251223-1481212/1481212_cmcsa-vsnt-snv-546.pdf
- https://www.sec.gov/Archives/edgar/data/2067876/000095010326000080/dp239186_ex9901.htm
- https://www.sec.gov/Archives/edgar/data/2067876/000206787626000010/vsnt-20251231.htm
- https://www.sec.gov/Archives/edgar/data/1616668/000089418926020700/xslFormNPORT-P_X01/primary_doc.xml

The old Versant Corp identity remains separate and audit-only. It was not
renamed, merged, or allowed to contribute prices. The corrected VSNT identity
has 196 cached EODHD bars from 2025-12-15 through 2026-09-25, including valid
OHLCV on 2026-01-05. Its sole eligible session is a natural causal warm-up
limitation because fewer than 200 preceding trading observations exist.

## B. LUV resolution

| Field | Result |
|---|---|
| security_id | 13256678-7f77-52fc-bd03-0bc03e53b96a |
| Missing EODHD eligible session | 2023-04-06 |
| Ticker/identity change | None |
| Exchange closure/halt | No; it was a valid XNYS session |
| EODHD cached bar | Absent |
| Massive persisted adjusted bar | Present |
| Massive OHLCV | O 31.77 / H 31.835 / L 31.36 / C 31.59 / V 2,979,659 |
| Cause | EODHD provider-data gap, not security lifecycle |

The dry-run keeps the EODHD adjusted-derived history as primary because it
contains the causal prehistory and fills only the absent date from the existing
Massive series. The Massive observation remains stored under its original
provider; it is not relabelled or copied. Primary observations always win on an
overlapping date, so no duplicate logical bar is possible. LUV now has 1,252 of
1,252 eligible sessions and complete causal features throughout the window.

## C. SBNY resolution

| Field | Result |
|---|---|
| security_id | 4eebb6ee-13b8-588c-8c90-5aaf4554ef62 |
| Last legitimate regular-session bar | 2023-03-10 |
| Nasdaq halt | 2023-03-13 at 04:00:01 ET; no regular-session resumption |
| Bank closure/receivership | 2023-03-12 |
| S&P 500 removal | Effective before open 2023-03-15 |
| Naturally unavailable eligible sessions | 2023-03-13 and 2023-03-14 |
| Final classification | NATURAL_POSTHISTORY_LIMITATION |

Nasdaq's issuer notice confirms the pre-market halt on 2023-03-13 pending
additional information. The FDIC confirms Signature Bank was closed on
2023-03-12. S&P DJI confirms removal before the 2023-03-15 open. Therefore no
regular-session OHLCV is expected on March 13 or 14 while the half-open index
membership had not yet ended. The tiny EODHD 2023-03-13 aggregate is not treated
as a tradable regular session. No OTC successor or bridge-bank security was
substituted.

Primary evidence:

- https://ir.nasdaq.com/news-releases/news-release-details/nasdaq-halts-signature-bank
- https://www.fdic.gov/news/press-releases/2023/pr23018.html
- https://press.spglobal.com/2023-03-13-Bunge-Set-to-Join-S-P-500

## D. Features-only readiness dry-run

| Measure | Result |
|---|---:|
| Memberships | 603 |
| Provider: EODHD adjusted-derived | 602 |
| Provider: EODHD primary + Massive gap observation | 1 |
| READY | 563 |
| READY_WITH_DOCUMENTED_LIMITATION | 40 |
| Missing price series | 0 |
| Material missing membership sessions | 0 |
| Natural lifecycle sessions | 30 |
| Feature warm-up sessions | 1,632 |
| Complete causal-feature sessions | 627,752 |

The 40 documented limitations are 24 natural prehistory cases and 16 natural
posthistory cases. They fail causally and do not receive synthetic observations.

## E. Integrity and hash consequence

| Check | Result |
|---|---|
| Ticker-only fallback | PASS — forbidden |
| Ticker-reuse isolation | PASS |
| Duplicate logical bars | PASS — rejected |
| Fabricated prices | PASS — none |
| Forward-fill/interpolation | PASS — none |
| Look-ahead | PASS — none |
| MRP_OLD | PASS — audit-only/non-tradable |
| Old Versant Corp | PASS — retained separately, audit-only |
| Provider provenance | PASS — original rows preserved |
| Universe dates/counts | PASS — unchanged, min 502 / max 505 / median 503 |

The previously validated identity-native hash was:

`51c3041e7a1f8d11218dfa056d4171e51cf88c4947b2714e01a9e9af4287b5fd`

After replacing the incorrect old-Versant `security_id` on the single
2026-01-05 snapshot with the proven Versant Media Group `security_id`, the hash
is necessarily:

`74d14b5198a7e64e91127abbbdcaae087e8c9134f6e8f6786446c210e2529b4d`

No membership boundary or constituent count changed. The old fingerprint is
preserved as the pre-correction audit hash, but it cannot truthfully remain the
active identity-native hash: doing so would retain the ticker-reuse defect.

## Final decision

**READY_FOR_PIT_EXECUTION**

All three market-data/identity blockers are resolved, the features-only
data-readiness dry-run passes, and the corrected identity-native hash has been
formally approved as the canonical PIT universe fingerprint. This status does
not itself execute or report a financial PIT backtest.
