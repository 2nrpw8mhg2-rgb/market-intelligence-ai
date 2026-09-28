import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.eodhd.identity import name_similarity
from app.market_data.calendar import NYSETradingCalendar
from app.massive_audit import MassiveAuditClient


HORIZONS = (1, 5, 10, 20, 60)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="POC 4: Massive second-source evaluation")
    command.add_argument("--eodhd-audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--output", default="data/massive_second_source_poc/audit.json")
    command.add_argument("--cache-dir", default="data/massive_second_source_poc/cache")
    command.add_argument("--requests-per-minute", type=int, default=60)
    command.add_argument("--concurrency", type=int, default=4)
    return command


def target_groups(master: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        "unresolved": {row["membership"]["ticker"] for row in master
                       if row["identity"]["confidence"] == "UNRESOLVED"},
        "reuse": {row["membership"]["ticker"] for row in master
                  if row["identity"]["reuse_status"] == "TICKER_REUSE_CONFIRMED"},
        "low_terminal": {row["membership"]["ticker"] for row in master
                         if row["event"]["confidence"] == "LOW"},
    }


def identifiers_match(eodhd: dict[str, Any], massive: dict[str, Any]) -> bool:
    pairs = (("CIK", "cik"), ("OpenFigi", "composite_figi"))
    return any(eodhd.get(left) and massive.get(right)
               and str(eodhd[left]).lstrip("0") == str(massive[right]).lstrip("0")
               for left, right in pairs)


async def run(args: argparse.Namespace) -> None:
    source = json.loads(Path(args.eodhd_audit).read_text())
    master = source["security_master"]
    by_ticker = {row["membership"]["ticker"]: row for row in master}
    groups = target_groups(master)
    targets = sorted(set().union(*groups.values()))
    calendar = NYSETradingCalendar()
    semaphore = asyncio.Semaphore(args.concurrency)
    errors: list[dict[str, str]] = []
    settings = get_settings()

    async with httpx.AsyncClient(timeout=settings.massive_timeout_seconds) as http:
        client = MassiveAuditClient(
            api_key=settings.massive_api_key.get_secret_value(), base_url=settings.massive_base_url,
            cache_dir=Path(args.cache_dir), requests_per_minute=args.requests_per_minute,
            timeout_seconds=settings.massive_timeout_seconds, max_retries=settings.massive_max_retries,
            retry_base_seconds=settings.massive_retry_base_seconds, client=http,
        )

        async def audit(ticker: str) -> dict[str, Any]:
            async with semaphore:
                row = by_ticker[ticker]
                membership = row["membership"]
                end = date.fromisoformat(membership["end"]) if membership["end"] else date(2026, 9, 22)
                source_start = date.fromisoformat(membership["start"]) if membership["start"] else date(2012, 4, 2)
                start = max(source_start, date(2012, 4, 2))
                as_of = min(end - timedelta(days=1), date(2026, 9, 22))
                details: dict[str, Any] = {}
                events: dict[str, Any] = {}
                bars: list[dict[str, Any]] = []
                splits: list[dict[str, Any]] = []
                dividends: list[dict[str, Any]] = []
                endpoint_errors: dict[str, str] = {}

                async def collect(endpoint: str, awaitable, fallback):
                    try:
                        return await awaitable
                    except Exception as exc:
                        message = str(exc)[:240]
                        endpoint_errors[endpoint] = message
                        errors.append({"ticker": ticker, "endpoint": endpoint,
                                       "type": type(exc).__name__, "message": message})
                        return fallback

                details = await collect("ticker_details", client.ticker_details(ticker, as_of.isoformat()), {})
                identifier = details.get("composite_figi") or ticker
                if ticker in groups["reuse"]:
                    events = await collect("ticker_events", client.ticker_events(str(identifier)), {})
                    splits = await collect("splits", client.splits(ticker), [])
                    dividends = await collect("dividends", client.dividends(ticker), [])
                price_start = start if ticker in groups["reuse"] else max(start, end - timedelta(days=14))
                price_end = min(date(2026, 9, 22), end + timedelta(days=100))
                bars = await collect("aggregates", client.aggregates(
                    ticker, price_start.isoformat(), price_end.isoformat()), [])

                bar_dates = sorted({datetime.fromtimestamp(item["t"] / 1000, tz=UTC).date().isoformat()
                                    for item in bars if item.get("t") is not None})
                available = {date.fromisoformat(item) for item in bar_dates}
                membership_sessions = calendar.trading_days_between(start, end - timedelta(days=1))
                overlap = sum(day in available for day in membership_sessions)
                after = calendar.trading_days_between(end, min(date(2026, 9, 22), end + timedelta(days=100)))
                price_access_failed = "aggregates" in endpoint_errors
                post = {str(h): (None if price_access_failed or len(after) < h
                                  else all(day in available for day in after[:h]))
                        for h in HORIZONS}
                identity_by_id = identifiers_match(row["identity"]["identifiers"], details)
                identity_by_name = bool(details.get("name") and
                                        name_similarity(row["canonical_name"], str(details["name"])) >= .5)
                historical_price_overlap = overlap > 0
                identity_resolved = identity_by_id or (identity_by_name and historical_price_overlap)
                ticker_events = events.get("events") if isinstance(events.get("events"), list) else []
                return {
                    "ticker": ticker,
                    "groups": sorted(name for name, values in groups.items() if ticker in values),
                    "membership": membership,
                    "eodhd": {"canonical_name": row["canonical_name"],
                              "identifiers": row["identity"]["identifiers"],
                              "event": row["event"]},
                    "massive": {"details": details, "events": ticker_events,
                                "split_count": len(splits), "dividend_count": len(dividends),
                                "endpoint_errors": endpoint_errors,
                                "first_bar": bar_dates[0] if bar_dates else None,
                                "last_bar": bar_dates[-1] if bar_dates else None,
                                "membership_expected": len(membership_sessions),
                                "membership_price_overlap": overlap,
                                "membership_coverage_pct": overlap / len(membership_sessions) * 100
                                if membership_sessions else None,
                                "post_removal": post},
                    "resolution": {"identifier_match": identity_by_id, "name_match": identity_by_name,
                                   "historical_price_overlap": historical_price_overlap,
                                   "identity_resolved": identity_resolved,
                                   "ticker_change_events": sum(item.get("type") == "ticker_change" for item in ticker_events),
                                   "delisted_date_available": bool(details.get("delisted_utc")),
                                   "structured_acquisition_terms": False,
                                   "structured_bankruptcy_recovery": False},
                }

        records = await asyncio.gather(*(audit(ticker) for ticker in targets))

    result = summarize(records, groups)
    decision = decide(result)
    report = {
        "scope": "MASSIVE_SECOND_SOURCE_DATA_QUALITY_NO_BACKTEST",
        "decision": decision, "groups": {key: sorted(value) for key, value in groups.items()},
        "summary": result, "records": records, "errors": errors,
        "api": {"requests": client.metrics.requests, "cache_hits": client.metrics.cache_hits,
                "rate_limits": client.metrics.rate_limits,
                "configured_rpm": args.requests_per_minute, "concurrency": args.concurrency},
        "capability_limits": {
            "ticker_events_supported_type": "ticker_change only",
            "structured_acquisition_consideration": False,
            "structured_merger_consideration": False,
            "structured_bankruptcy_recovery": False,
            "splits_and_dividends": True,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, default=str, indent=2, sort_keys=True))
    print(json.dumps({"output": str(output), "decision": decision, "summary": result,
                      "api": report["api"], "errors": len(errors)}, indent=2))


def summarize(records: list[dict[str, Any]], groups: dict[str, set[str]]) -> dict[str, Any]:
    resolved = {row["ticker"] for row in records if row["resolution"]["identity_resolved"]}
    changes = {row["ticker"] for row in records if row["resolution"]["ticker_change_events"] > 0}
    details = {row["ticker"] for row in records if row["massive"]["details"]}
    delisted = {row["ticker"] for row in records if row["resolution"]["delisted_date_available"]}
    post = {}
    low_rows = [row for row in records if "low_terminal" in row["groups"]]
    for horizon in HORIZONS:
        values = [row["massive"]["post_removal"][str(horizon)] for row in low_rows
                  if row["massive"]["post_removal"][str(horizon)] is not None]
        post[str(horizon)] = {"eligible": len(values), "complete": sum(value is True for value in values),
                              "coverage_pct": (sum(value is True for value in values) / len(values) * 100
                                               if values else None)}
    return {
        "unique_targets": len(records), "details_available": len(details),
        "unresolved_identity_resolved": len(resolved & groups["unresolved"]),
        "unresolved_identity_total": len(groups["unresolved"]),
        "reuse_identity_resolved": len(resolved & groups["reuse"]),
        "reuse_total": len(groups["reuse"]),
        "ticker_change_evidence": len(changes), "delisted_date_available": len(delisted),
        "low_terminal_total": len(groups["low_terminal"]),
        "low_terminal_with_details": len(details & groups["low_terminal"]),
        "post_removal_low_terminal": post,
        "structured_acquisition_terms": 0, "structured_bankruptcy_recoveries": 0,
        "event_classes": Counter(row["eodhd"]["event"]["classification"] for row in low_rows),
    }


def decide(summary: dict[str, Any]) -> str:
    if (summary["unresolved_identity_resolved"] == summary["unresolved_identity_total"]
            and summary["structured_acquisition_terms"] > 0
            and summary["structured_bankruptcy_recoveries"] > 0):
        return "MASSIVE_SUFFICIENT_AS_SECOND_SOURCE"
    if summary["unresolved_identity_resolved"] or summary["ticker_change_evidence"]:
        return "MASSIVE_PARTIALLY_SUFFICIENT"
    return "MASSIVE_INSUFFICIENT"


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
