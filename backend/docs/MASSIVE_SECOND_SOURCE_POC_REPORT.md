# Massive POC 4 — Second-Source Evaluation

**Audit date:** 2026-09-28
**Input:** EODHD POC 3 Historical Security Master v0
**Scope:** reference identity, ticker events, corporate actions and price availability only. No strategy, scanner, financial metric or backtest was executed.
**Decision:** **MASSIVE_PARTIALLY_SUFFICIENT**

## 1. Executive conclusion

Massive adds useful independent evidence, but it does not close the POC 3 gaps. Across the exact requested population—21 unresolved identities, 22 confirmed ticker reuses and 82 LOW-confidence terminal events (104 unique tickers)—it resolved 5/21 unresolved identities and 6/22 ticker-reuse identities using CIK or composite FIGI. It returned ticker-change evidence for nine tickers. It did not provide structured acquisition/merger consideration, successor conversion terms, bankruptcy recoveries or a dependable delisting date for any target.

Historical aggregate-price access was also restricted by the currently configured Massive entitlement: 85 requests returned HTTP 403. This is reported as an access limitation, not as proof that the underlying records do not exist. Fourteen targets returned at least one bar from cache/API responses, but the evidence was insufficient to validate post-removal coverage for the LOW terminal-event population.

Massive is therefore valuable as a reference-identity and ticker-change cross-check, but is not sufficient as the sole second source for a production point-in-time security master or terminal-value ledger.

## 2. Method and controls

The POC consumed the ignored machine-readable EODHD POC 3 audit and selected only:

- 21 rows with identity confidence `UNRESOLVED`;
- 22 rows with `TICKER_REUSE_CONFIRMED`;
- 82 terminal events with confidence `LOW`.

The union contains 104 tickers. The audit queried point-in-time ticker details at the last day of membership, ticker events for reuse candidates, splits, dividends and daily aggregates over the relevant membership/removal interval. Identity was accepted only when CIK/composite FIGI matched, or when compatible company name and historical price overlap were both present. Ticker alone was never treated as identity.

Responses were cached by endpoint and non-secret parameters. The client used a 60 requests/minute cap, concurrency four, retry/backoff for transport, rate-limit and server errors, and sanitized exceptions. The API key was sent only as an authentication parameter and is absent from the report, audit output, cache keys and tests. Mock-based tests cover parsing, caching, empty results without synthetic filling, error redaction, target selection, identifier matching and the decision rule.

## 3. Reference identity results

| Measure | Result |
|---|---:|
| Unique targets | 104 |
| Point-in-time details returned | 52 |
| Unresolved identities resolved | 5 / 21 |
| Reused-ticker identities resolved | 6 / 22 |
| Targets with ticker-change evidence | 9 |
| Targets with `delisted_utc` | 0 |

The five formerly unresolved identities resolved by stable identifier are **BTU, DNB, DO, MNK and NE**. The six reused-ticker identities resolved are the same five plus **MON**. No identity was promoted solely on a name similarity.

The 52 missing detail results comprise 36 HTTP 404 responses and 16 HTTP 400 invalid-symbol responses. The invalid symbols are POC 3 provider aliases ending in `_OLD`, plus `LEN-N`; Massive does not recognize those EODHD-specific aliases. A 404/400 is retained as negative provider evidence and is not converted into a delisting or acquisition classification.

## 4. Ticker events and successor evidence

Ticker-event responses supplied one `ticker_change` event for each of **ADT, BEAM, BTU, EMC, MMI, NE, S, SE and VAL**. Thirteen other queried reuse candidates returned HTTP 404 “No events found for given ID”. Massive's ticker-events resource currently exposes ticker changes; it is not a normalized merger/acquisition/successor ledger.

Several returned events describe the beginning of a newer security's use of a ticker. They are useful evidence of reuse, but do not prove continuity with the former constituent. Successor identity still requires compatible security identifiers and effective legal terms.

## 5. Corporate actions and terminal events

Splits and dividends were queried for reuse candidates and are useful for ordinary adjustment/event checks. They do not answer the requested terminal-economic questions. The evaluated resources supplied:

| Required evidence | Structured results |
|---|---:|
| Cash/stock acquisition consideration | 0 |
| Merger conversion terms | 0 |
| Bankruptcy/receivership recovery | 0 |
| Reliable delisting date in ticker details | 0 |
| Verified successor-security mapping | 0 |

Accordingly, none of the 82 EODHD LOW generic delistings was upgraded to a specific cash acquisition, stock acquisition, merger, bankruptcy or receivership outcome. Absence of structured evidence is not interpreted as a zero recovery or as proof that no corporate action occurred.

## 6. Historical and post-removal prices

| Horizon after removal | Eligible LOW events | Complete | Coverage |
|---|---:|---:|---:|
| 1 session | 19 | 0 | 0.0% |
| 5 sessions | 19 | 0 | 0.0% |
| 10 sessions | 19 | 0 | 0.0% |
| 20 sessions | 19 | 0 | 0.0% |
| 60 sessions | 19 | 0 | 0.0% |

These zeros mean “not demonstrated by this POC”, not “all securities stopped trading”. Of the 82 LOW events, 63 were non-evaluable because their aggregate request returned HTTP 403; 19 were technically evaluable and none demonstrated a complete post-removal horizon. Across all groups, 85 aggregate requests returned HTTP 403 and only 14 of 104 targets yielded any price bar. No session was filled, inferred or synthesized. The result cannot distinguish unavailable provider history from a plan restriction for the affected queries, so it cannot close post-removal price coverage.

## 7. API execution and failures

The final controlled run made 191 network requests, reused 83 cached responses, encountered no HTTP 429/rate-limit event and left 124 successful response objects in the local ignored cache.

| Endpoint | Errors | Interpretation |
|---|---:|---|
| Aggregates | 85 | HTTP 403 entitlement/access limitation |
| Ticker details | 52 | 36 not found; 16 invalid/provider-specific symbols |
| Ticker events | 13 | no events found for identifier |

Failures were isolated per endpoint: a missing detail/event did not suppress the remaining safe checks. Error output includes endpoint and HTTP status but excludes credentials. Operational JSON and cache remain under ignored `backend/data/` and are not intended for Git.

## 8. Capability assessment

| Capability | Assessment |
|---|---|
| Point-in-time reference ticker details | Partial; useful for 52/104 targets |
| CIK / composite FIGI identity corroboration | Useful but resolves only a minority of target gaps |
| Ticker reuse/change evidence | Partial; nine target tickers have change evidence |
| Splits and dividends | Available, but not terminal-value evidence |
| Delisting reason/effective date | Insufficient in evaluated results |
| Merger/acquisition consideration | Not available as a structured result in evaluated stock resources |
| Successor security and conversion ratio | Insufficient |
| Bankruptcy recovery | Insufficient |
| Historical/post-removal prices | Inconclusive for most targets because of HTTP 403 entitlement failures |

## 9. Decision

**MASSIVE_PARTIALLY_SUFFICIENT**

The result is above `MASSIVE_INSUFFICIENT` because Massive independently resolves five previously unresolved identities, six ticker-reuse identities and provides nine ticker-change traces. It does not reach `MASSIVE_SUFFICIENT_AS_SECOND_SOURCE` because 16/21 unresolved identities and 16/22 reuse cases remain unresolved, all 82 LOW terminal classifications remain economically unresolved, structured M&A/bankruptcy/successor terms are absent, and the historical-price entitlement prevented a conclusive post-removal audit.

This POC does not authorize PIT backtesting. A further source is still required for corporate-action consideration, successor securities, delisting reasons/dates and bankruptcy/receivership recovery. Historical price entitlement may be reassessed separately, without changing this terminal-event conclusion.

## 10. Reproducibility

Machine-readable output is intentionally ignored at `backend/data/massive_second_source_poc/audit.json`. The code entry point is:

```bash
cd backend
python -m app.cli.run_massive_second_source_poc \
  --eodhd-audit data/eodhd_poc3/audit.json \
  --output data/massive_second_source_poc/audit.json \
  --cache-dir data/massive_second_source_poc/cache \
  --requests-per-minute 60 \
  --concurrency 4
```

The local `.env` supplies authentication and must remain ignored. Re-running uses cached successful responses; access/not-found failures are retried and remain explicit.
