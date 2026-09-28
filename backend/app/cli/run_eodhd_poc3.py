import argparse
import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.eodhd import EODHDClient
from app.eodhd.identity import (
    Confidence, ReuseStatus, StartDateStatus, name_similarity, post_removal_availability,
    reuse_status, stable_security_id,
)
from app.eodhd.models import EODBar, HistoricalConstituent
from app.market_data.calendar import NYSETradingCalendar


COVERAGE_START = date(2012, 4, 1)
COVERAGE_END = date(2026, 9, 22)
HORIZONS = (1, 5, 10, 20, 60)
RELIABILITY_CRITERIA = {
    "membership_count_floor": 490,
    "identity_resolution_pct": 99.0,
    "price_coverage_pct": 99.5,
    "terminal_event_resolution_pct": 95.0,
    "post_removal_20d_pct": 95.0,
    "missing_not_at_random_allowed": False,
}
CRITICAL_EVENTS = {
    "ATVI": "ACQUISITION_CASH", "TWTR": "ACQUISITION_CASH",
    "CELG": "ACQUISITION_MIXED", "MON": "ACQUISITION_CASH",
    "SIVB": "RECEIVERSHIP", "LEH": "BANKRUPTCY",
}


class RateGate:
    def __init__(self, requests_per_minute: int) -> None:
        self.interval = 60 / requests_per_minute
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self) -> None:
        async with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_at - now)
            self.next_at = max(now, self.next_at) + self.interval
        if delay:
            await asyncio.sleep(delay)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="POC 3: full historical data coverage audit")
    command.add_argument("--output", default="data/eodhd_poc3/audit.json")
    command.add_argument("--cache-dir", default="data/eodhd_poc/cache")
    command.add_argument("--concurrency", type=int, default=4)
    command.add_argument("--requests-per-minute", type=int, default=300)
    return command


def identifiers(general: dict[str, Any]) -> dict[str, str]:
    return {key: str(general[key]) for key in ("CIK", "CUSIP", "ISIN", "OpenFigi", "LEI") if general.get(key)}


def identity_confidence(record: HistoricalConstituent, general: dict[str, Any], provider_name: str | None) -> Confidence:
    ids = identifiers(general)
    reference = general.get("Name") or provider_name
    if not reference or name_similarity(record.name, str(reference)) < .5:
        return Confidence.UNRESOLVED
    if len(ids) >= 2:
        return Confidence.HIGH
    if len(ids) == 1:
        return Confidence.MEDIUM
    return Confidence.LOW


def choose_provider_symbol(record: HistoricalConstituent, current: dict[str, dict], delisted: list[dict]) -> tuple[str | None, str | None, list[str]]:
    evidence = []
    if record.code == "MON":
        monsanto = next((row for row in delisted if str(row.get("Code", "")).upper() == "MON_OLD"
                         and "monsanto" in str(row.get("Name", "")).lower()), None)
        if monsanto:
            return str(monsanto["Code"]), str(monsanto.get("Name")), [
                "POC2 verified Monsanto alias by ISIN/CUSIP/CIK/LEI; membership name is provider-overwritten",
            ]
    exact = current.get(record.code)
    if exact and name_similarity(record.name, str(exact.get("Name", ""))) >= .5:
        return record.code, str(exact.get("Name")), ["current directory ticker and name compatible"]
    exact_delisted = [row for row in delisted if str(row.get("Code", "")).upper() == record.code]
    compatible = [row for row in exact_delisted if name_similarity(record.name, str(row.get("Name", ""))) >= .5]
    if len(compatible) == 1:
        return str(compatible[0]["Code"]), str(compatible[0].get("Name")), ["delisted directory ticker and name compatible"]
    return None, None, ["no exact safe current/delisted instrument mapping"]


def event_classification(record: HistoricalConstituent, bars: list[EODBar], has_symbol_change: bool) -> tuple[str, str]:
    if record.code in CRITICAL_EVENTS:
        return CRITICAL_EVENTS[record.code], "HIGH"
    if has_symbol_change and record.end_date:
        return "TICKER_CHANGE", "MEDIUM"
    if not record.end_date:
        return "NONE_ACTIVE", "HIGH"
    if bars and bars[-1].date >= record.end_date:
        return "INDEX_REMOVAL_STILL_TRADING", "HIGH"
    if record.is_delisted:
        return "DELISTING", "LOW"
    return "UNKNOWN", "UNRESOLVED"


def missing_reason(record: HistoricalConstituent, missing: list[date], identity: Confidence,
                   event: str, change_dates: set[date]) -> Counter[str]:
    result: Counter[str] = Counter()
    for session in missing:
        if identity is Confidence.UNRESOLVED:
            reason = "IDENTITY_MAPPING_FAILURE"
        elif any(abs((session - change).days) <= 7 for change in change_dates):
            reason = "SYMBOL_CHANGE_BOUNDARY"
        elif record.end_date and abs((record.end_date - session).days) <= 10 and event not in {"NONE_ACTIVE", "INDEX_REMOVAL_STILL_TRADING"}:
            reason = "TERMINAL_EVENT"
        else:
            reason = "PROVIDER_DATA_GAP"
        result[reason] += 1
    return result


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    gate = RateGate(args.requests_per_minute)
    semaphore = asyncio.Semaphore(args.concurrency)
    errors: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=settings.eodhd_timeout_seconds) as http:
        client = EODHDClient(
            api_key=settings.eodhd_api_key.get_secret_value(), base_url=settings.eodhd_base_url,
            timeout_seconds=settings.eodhd_timeout_seconds, max_retries=settings.eodhd_max_retries,
            retry_base_seconds=settings.eodhd_retry_base_seconds, cache_dir=Path(args.cache_dir), client=http,
        )
        records = await client.historical_constituents()
        delisted = await client.delisted_symbols()
        changes = await client.symbol_changes(date(2012, 1, 1), date(2026, 9, 28))
        current_payload = await client.historical_snapshot(date(2026, 6, 30))
        current_rows = next(iter(current_payload.values()), {}) if current_payload else {}
        current = {str(row.get("Code", "")).upper(): row for row in current_rows.values()}
        changes_by_symbol: dict[str, list[Any]] = defaultdict(list)
        for change in changes:
            changes_by_symbol[change.old_symbol].append(change)
            changes_by_symbol[change.new_symbol].append(change)

        async def wait_if_network(path: str, params: dict[str, Any]) -> None:
            safe_params = {**params, "fmt": "json"}
            cache_file = Path(args.cache_dir) / f"{client._cache_key(path, safe_params)}.json"
            if not cache_file.exists():
                await gate.wait()

        async def audit(record: HistoricalConstituent) -> dict[str, Any]:
            async with semaphore:
                provider_code, provider_name, mapping_evidence = choose_provider_symbol(record, current, delisted)
                if provider_code is None:
                    # A ticker is only a candidate here.  It is accepted only if
                    # independently returned fundamentals match the historical
                    # company name and carry usable identifiers.
                    provider_code = record.code
                    mapping_evidence.append("exact ticker used as candidate pending fundamentals validation")
                try:
                    fundamental_path = f"v1.1/fundamentals/{quote(f'{provider_code}.US'.upper(), safe='.-')}"
                    await wait_if_network(fundamental_path, {"filter": "General"})
                    general = await client.fundamentals_general(f"{provider_code}.US")
                    confidence = (Confidence.HIGH if record.code == "MON" and provider_code == "MON_old"
                                  and len(identifiers(general)) >= 2
                                  else identity_confidence(record, general, provider_name))
                    if confidence is Confidence.UNRESOLVED:
                        return build_row(record, None, general.get("Name") or provider_name, general, [],
                                         mapping_evidence + ["candidate rejected: fundamentals name incompatible"],
                                         changes_by_symbol.get(record.code, []))
                    eod_path = f"eod/{quote(f'{provider_code}.US'.upper(), safe='.-')}"
                    await wait_if_network(eod_path, {"period": "d", "order": "a"})
                    bars = await client.eod(f"{provider_code}.US")
                    return build_row(record, provider_code, provider_name, general, bars, mapping_evidence,
                                     changes_by_symbol.get(record.code, []))
                except Exception as exc:
                    errors.append({"ticker": record.code, "type": type(exc).__name__, "message": str(exc)[:240]})
                    return build_row(record, provider_code, provider_name, {}, [], mapping_evidence + ["API error"],
                                     changes_by_symbol.get(record.code, []))

        calendar = NYSETradingCalendar()
        all_sessions = calendar.trading_days_between(COVERAGE_START, COVERAGE_END)

        def build_row(record: HistoricalConstituent, provider_code: str | None, provider_name: str | None,
                      general: dict[str, Any], bars: list[EODBar], evidence: list[str], symbol_changes) -> dict[str, Any]:
            ids = identifiers(general)
            confidence = (Confidence.HIGH if record.code == "MON" and provider_code == "MON_old"
                          and len(ids) >= 2 else
                          identity_confidence(record, general, provider_name) if provider_code else Confidence.UNRESOLVED)
            temporal_reuse = bool(provider_code and record.end_date and bars and bars[0].date >= record.end_date)
            if temporal_reuse:
                confidence = Confidence.UNRESOLVED
                evidence = evidence + ["candidate series begins on/after historical membership end; ticker reuse confirmed"]
            expected = [day for day in all_sessions if record.is_member_on(day, end_date_inclusive=False)]
            available = {bar.date for bar in bars}
            present = [day for day in expected if day in available]
            missing = [day for day in expected if day not in available]
            expected_by_year = Counter(day.year for day in expected)
            available_by_year = Counter(day.year for day in present)
            missing_by_year = Counter(day.year for day in missing)
            event, event_confidence = event_classification(record, bars, bool(symbol_changes))
            change_dates = {item.effective for item in symbol_changes}
            reasons = missing_reason(record, missing, confidence, event, change_dates)
            post = post_removal_availability(all_sessions, available, record.end_date, HORIZONS)
            return {
                "security_id": str(stable_security_id(record, ids)), "canonical_name": general.get("Name") or provider_name or record.name,
                "membership": {"ticker": record.code, "start": record.start_date,
                               "end": record.end_date, "start_status": (StartDateStatus.PRE_HISTORY_MEMBER if record.start_date is None else StartDateStatus.RESOLVED_EXACT),
                               "left_censored": record.start_date is None, "first_assertable_membership": COVERAGE_START if record.start_date is None else record.start_date,
                               "end_semantics": "EXCLUSIVE"},
                "identity": {"confidence": confidence, "provider_symbol": provider_code,
                             "provider_name": provider_name, "identifiers": ids,
                             "reuse_status": (ReuseStatus.TICKER_REUSE_CONFIRMED
                                              if temporal_reuse or record.code == "MON" and provider_code == "MON_old"
                                              else reuse_status(record.name, provider_name or general.get("Name"))),
                             "evidence": evidence, "symbol_changes": [item.model_dump(mode="json") for item in symbol_changes]},
                "prices": {"first": bars[0].date if bars else None, "last": bars[-1].date if bars else None,
                           "expected_sessions": len(expected), "available_sessions": len(present),
                           "missing_sessions": len(missing),
                           "coverage_pct": (len(present) / len(expected) * 100 if expected else None),
                           "expected_by_year": expected_by_year, "available_by_year": available_by_year,
                           "missing_by_year": missing_by_year, "missing_by_reason": reasons},
                "event": {"classification": event, "confidence": event_confidence,
                          "post_removal_available": post},
                "quality": {"unresolved_flags": (["IDENTITY"] if confidence is Confidence.UNRESOLVED else [])
                            + (["PRICE"] if missing else [])
                            + (["TERMINAL_EVENT"] if event == "UNKNOWN" else [])},
            }

        master = await asyncio.gather(*(audit(record) for record in records))

    annual = annual_quality(records, master, all_sessions)
    snapshots = snapshot_quality(records, master, all_sessions)
    totals = summarize(master)
    reliable = [row for row in annual if row["reliability"] == "RELIABLE"]
    earliest = reliable[0]["first_session"] if reliable else None
    decision = "EODHD_SUFFICIENT_FROM_DATE" if earliest else "EODHD_REQUIRES_SECOND_SOURCE"
    report = {
        "scope": "POC3_FULL_COVERAGE_NO_BACKTEST", "coverage_start": COVERAGE_START,
        "coverage_end": COVERAGE_END, "reliability_criteria_predeclared": RELIABILITY_CRITERIA,
        "decision": decision, "earliest_reliable_pit_date": earliest,
        "summary": totals, "annual": annual, "snapshots": snapshots,
        "security_master": master, "errors": errors,
        "api": {"requests": client.metrics.network_requests, "cache_hits": client.metrics.cache_hits,
                "rate_limits": client.metrics.rate_limit_events, "configured_rpm": args.requests_per_minute,
                "concurrency": args.concurrency},
    }
    output.write_text(json.dumps(report, default=str, indent=2, sort_keys=True))
    print(json.dumps({"output": str(output), "decision": decision, "earliest": earliest,
                      "summary": totals, "api": report["api"], "errors": len(errors)}, default=str, indent=2))


def summarize(master: list[dict[str, Any]]) -> dict[str, Any]:
    identity = Counter(row["identity"]["confidence"] for row in master)
    reuse = Counter(row["identity"]["reuse_status"] for row in master)
    events = Counter(row["event"]["classification"] for row in master)
    missing = Counter()
    by_event: dict[str, Counter[str]] = defaultdict(Counter)
    expected = available = 0
    for row in master:
        expected += row["prices"]["expected_sessions"]
        available += row["prices"]["available_sessions"]
        missing.update(row["prices"]["missing_by_reason"])
        event = row["event"]["classification"]
        by_event[event]["securities"] += 1
        by_event[event]["expected"] += row["prices"]["expected_sessions"]
        by_event[event]["available"] += row["prices"]["available_sessions"]
        by_event[event]["missing"] += row["prices"]["missing_sessions"]
    post = {}
    for horizon in HORIZONS:
        values = [row["event"]["post_removal_available"][horizon] for row in master
                  if row["event"]["post_removal_available"][horizon] is not None]
        post[str(horizon)] = {"eligible": len(values), "complete": sum(values),
                              "coverage_pct": (sum(values) / len(values) * 100 if values else None)}
    return {
        "membership_records": len(master), "historical_security_ids": len({row["security_id"] for row in master}),
        "identity_confidence": identity, "reuse": reuse, "events": events,
        "left_censored": sum(row["membership"]["left_censored"] for row in master),
        "with_provider_symbol": sum(row["identity"]["provider_symbol"] is not None for row in master),
        "membership_security_days": expected, "with_valid_price": available,
        "missing_sessions": expected - available,
        "coverage_pct": available / expected * 100 if expected else None,
        "missing_by_reason": missing,
        "coverage_by_event": {
            event: {**values, "coverage_pct": (values["available"] / values["expected"] * 100
                                                if values["expected"] else None)}
            for event, values in sorted(by_event.items())
        },
        "post_removal": post,
    }


def annual_quality(records: list[HistoricalConstituent], master: list[dict[str, Any]], sessions: list[date]) -> list[dict[str, Any]]:
    by_ticker = {row["membership"]["ticker"]: row for row in master}
    results = []
    for year in range(2012, 2027):
        year_sessions = [day for day in sessions if day.year == year]
        if not year_sessions:
            continue
        active = [record for record in records if any(record.is_member_on(day, end_date_inclusive=False) for day in year_sessions)]
        expected = available = 0
        confidences = Counter()
        unresolved_terminal_events = 0
        post20 = []
        securities_with_price = 0
        for record in active:
            row = by_ticker[record.code]
            expected += row["prices"]["expected_by_year"].get(year, 0)
            available += row["prices"]["available_by_year"].get(year, 0)
            confidences[row["identity"]["confidence"]] += 1
            securities_with_price += row["prices"]["available_sessions"] > 0
            if record.end_date and record.end_date.year == year:
                unresolved_terminal_events += row["event"]["confidence"] in {"LOW", "UNRESOLVED"}
                value = row["event"]["post_removal_available"][20]
                if value is not None:
                    post20.append(value)
        identity_pct = (sum(confidences[level] for level in ("HIGH", "MEDIUM")) / len(active) * 100) if active else 0
        price_pct = available / expected * 100 if expected else 0
        exits = [record for record in active if record.end_date and record.end_date.year == year]
        terminal_pct = ((len(exits) - unresolved_terminal_events) / len(exits) * 100) if exits else 100
        post_pct = sum(post20) / len(post20) * 100 if post20 else 100
        reliable = (len(active) >= RELIABILITY_CRITERIA["membership_count_floor"]
                    and identity_pct >= RELIABILITY_CRITERIA["identity_resolution_pct"]
                    and price_pct >= RELIABILITY_CRITERIA["price_coverage_pct"]
                    and terminal_pct >= RELIABILITY_CRITERIA["terminal_event_resolution_pct"]
                    and post_pct >= RELIABILITY_CRITERIA["post_removal_20d_pct"])
        condition = "RELIABLE" if reliable else ("CONDITIONALLY_RELIABLE" if len(active) >= 490 and price_pct >= 99 else "UNRELIABLE")
        results.append({"year": year, "first_session": year_sessions[0], "last_session": year_sessions[-1],
                        "derived_constituents_during_year": len(active), "identity": confidences,
                        "unresolved_identity": confidences["UNRESOLVED"], "securities_with_prices": securities_with_price,
                        "securities_without_prices": len(active) - securities_with_price,
                        "membership_security_days": expected, "with_valid_price_estimate": available,
                        "price_coverage_pct": price_pct, "exits_in_year": len(exits),
                        "terminal_event_resolution_pct": terminal_pct,
                        "unresolved_terminal_events": unresolved_terminal_events,
                        "post_removal_20d_pct": post_pct, "reliability": condition})
    return results


def snapshot_quality(records: list[HistoricalConstituent], master: list[dict[str, Any]], sessions: list[date]) -> list[dict[str, Any]]:
    by_ticker = {row["membership"]["ticker"]: row for row in master}
    results = []
    for year in range(2012, 2027):
        year_sessions = [day for day in sessions if day.year == year]
        if not year_sessions:
            continue
        for day in sorted({year_sessions[0], year_sessions[len(year_sessions) // 2], year_sessions[-1]}):
            active = [record for record in records if record.is_member_on(day, end_date_inclusive=False)]
            tickers = Counter(record.code for record in active)
            names = {record.name for record in active}
            results.append({"date": day, "securities": len(active), "companies_by_exact_name": len(names),
                            "duplicate_aliases": sorted(code for code, count in tickers.items() if count > 1),
                            "left_censored_memberships": sum(record.start_date is None for record in active),
                            "unresolved_identities": sum(by_ticker[record.code]["identity"]["confidence"] == "UNRESOLVED" for record in active),
                            "without_any_price": sum(by_ticker[record.code]["prices"]["available_sessions"] == 0 for record in active),
                            "ticker_collisions": sorted(record.code for record in active if by_ticker[record.code]["identity"]["reuse_status"] in {ReuseStatus.TICKER_REUSE_CONFIRMED, ReuseStatus.TICKER_REUSE_SUSPECTED})})
    return results


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
